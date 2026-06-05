/* StatForge PWA engine — a fully client-side backend.
 *
 * The UI (index.html) talks to "/api/..." via fetch(). Here we monkey-patch
 * fetch() to answer those same routes locally, backed by IndexedDB and a small
 * JS roll/tracker engine. No server, no network — works offline on GitHub Pages.
 *
 * Storage is per-browser (each DM has their own compendium). Use the Export /
 * Import JSON buttons to back up or share libraries.
 */
(function () {
  "use strict";

  const realFetch = window.fetch.bind(window);
  const OWNER = "local-user";
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : "id-" + Date.now() + "-" + Math.random().toString(16).slice(2));

  // ---------------------------------------------------------------- IndexedDB
  let _db = null;
  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open("statforge", 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("statblocks")) db.createObjectStore("statblocks", { keyPath: "id" });
        if (!db.objectStoreNames.contains("encounters")) db.createObjectStore("encounters", { keyPath: "id" });
        if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv", { keyPath: "k" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  function tx(store, mode) { return _db.transaction(store, mode).objectStore(store); }
  function pr(req) { return new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); }); }
  const dbGet = (s, k) => pr(tx(s, "readonly").get(k));
  const dbAll = (s) => pr(tx(s, "readonly").getAll());
  const dbPut = (s, v) => pr(tx(s, "readwrite").put(v));
  const dbDel = (s, k) => pr(tx(s, "readwrite").delete(k));
  const dbClear = (s) => pr(tx(s, "readwrite").clear());
  async function kvGet(k, dflt) { const r = await dbGet("kv", k); return r ? r.v : dflt; }
  const kvPut = (k, v) => dbPut("kv", { k, v });

  // ------------------------------------------------------------- live state
  let currentEnc = { round: 0, active_index: 0, combatants: [] };
  let rolls = [];
  const saveEnc = () => kvPut("currentEncounter", currentEnc);
  const saveRolls = () => kvPut("rolls", rolls);

  // ------------------------------------------------------------------- dice
  const abMod = (score) => Math.floor(((score == null ? 10 : score) - 10) / 2);
  function rollDie(n) { return 1 + Math.floor(Math.random() * n); }
  function rollD20(modifier, advantage) {
    let dice, pick;
    if (advantage === "advantage" || advantage === "disadvantage") {
      const a = rollDie(20), b = rollDie(20); dice = [a, b];
      pick = advantage === "advantage" ? Math.max(a, b) : Math.min(a, b);
    } else { pick = rollDie(20); dice = [pick]; }
    return { dice, total: pick + (modifier || 0) };
  }
  function rollDiceExpr(diceStr, bonus) {
    const out = { results: [], total: bonus || 0 };
    const m = /(\d+)\s*d\s*(\d+)/i.exec(diceStr || "");
    if (m) { const c = +m[1], f = +m[2]; for (let i = 0; i < c; i++) { const r = rollDie(f); out.results.push(r); out.total += r; } }
    return out;
  }
  function makeEvent(o) {
    return {
      id: uuid(), owner_id: OWNER, timestamp: new Date().toISOString(),
      source: o.source, roll_type: o.roll_type, label: o.label,
      expression: o.expression, dice_results: o.dice_results,
      modifier: o.modifier || 0, total: o.total, target: null,
      advantage: o.advantage || null, private: true,
    };
  }
  const signed = (n) => (n >= 0 ? "+" + n : "" + n);

  // -------------------------------------------------------------- statblocks
  function crValue(cr) {
    if (!cr) return Infinity;
    cr = String(cr).trim();
    try { if (cr.includes("/")) { const [a, b] = cr.split("/"); return (+a) / (+b); } return parseFloat(cr); }
    catch (e) { return Infinity; }
  }
  async function listStatblocks() {
    const all = await dbAll("statblocks");
    const items = all.map(sb => ({
      id: sb.id, name: sb.name, challenge_rating: sb.challenge_rating,
      armor_class: sb.armor_class, hit_points: sb.hit_points,
      creature_type: sb.creature_type, size: sb.size, parse_confidence: sb.parse_confidence,
    }));
    items.sort((a, b) => (crValue(a.challenge_rating) - crValue(b.challenge_rating)) ||
      (a.name || "").toLowerCase().localeCompare((b.name || "").toLowerCase()));
    return items;
  }
  function findAction(sb, name) {
    for (const bucket of [sb.actions, sb.legendary_actions, sb.bonus_actions, sb.reactions, sb.traits]) {
      for (const a of (bucket || [])) if (a.name === name) return a;
    }
    return null;
  }

  // ---------------------------------------------------------------- tracker
  function encDump() {
    return {
      round: currentEnc.round, active_index: currentEnc.active_index,
      combatants: currentEnc.combatants.map(c => ({
        id: c.id, display_name: c.display_name, initiative: c.initiative,
        current_hp: c.current_hp, max_hp: c.max_hp, temp_hp: c.temp_hp || 0,
        armor_class: c.armor_class, statblock_id: c.statblock_id,
        is_player: !!c.is_player, conditions: (c.conditions || []).slice(),
      })),
    };
  }
  function sortEnc() { currentEnc.combatants.sort((a, b) => (b.initiative ?? -99) - (a.initiative ?? -99)); }
  function renumber() {
    const groups = {};
    currentEnc.combatants.forEach(c => { if (c.is_player) return; (groups[c.statblock_id] = groups[c.statblock_id] || []).push(c); });
    Object.values(groups).forEach(list => {
      if (list.length > 1) list.forEach((c, i) => { c.display_name = `${c.base || c.display_name.replace(/\s*#\d+$/, "")} #${i + 1}`; });
      else if (list.length === 1) list[0].display_name = list[0].base || list[0].display_name;
    });
  }
  async function spawn(statblockId, count) {
    const sb = await dbGet("statblocks", statblockId);
    if (!sb) return;
    const dex = abMod(sb.abilities && sb.abilities.dexterity);
    for (let i = 0; i < (count || 1); i++) {
      currentEnc.combatants.push({
        id: uuid(), statblock_id: sb.id, base: sb.name, display_name: sb.name,
        initiative: rollD20(dex).total, current_hp: sb.hit_points || 1,
        max_hp: sb.hit_points || 1, temp_hp: 0, armor_class: sb.armor_class || 10,
        is_player: false, conditions: [],
      });
    }
    renumber(); sortEnc(); await saveEnc();
  }

  // ----------------------------------------------------------------- rolling
  async function doRoll(d) {
    const sb = await dbGet("statblocks", d.statblock_id);
    if (!sb) return { _status: 404, error: "stat block not found" };
    const source = d.source || sb.name;
    const kind = d.kind || "attack";
    const adv = d.advantage || null;
    let ev;
    if (kind === "attack") {
      const a = findAction(sb, d.action_name); if (!a) return { _status: 404, error: "action not found" };
      const toHit = (a.attack && a.attack.to_hit) || 0;
      const r = rollD20(toHit, adv);
      ev = makeEvent({ source, roll_type: "attack", label: `${a.name} to hit`, expression: `1d20${signed(toHit)}`, dice_results: r.dice, modifier: toHit, total: r.total, advantage: adv });
    } else if (kind === "damage") {
      const a = findAction(sb, d.action_name); if (!a) return { _status: 404, error: "action not found" };
      const comps = a.damage || []; let dice = [], total = 0, parts = [];
      comps.forEach(c => {
        const reps = d.crit ? 2 : 1; let local = [];
        for (let k = 0; k < reps; k++) { const rr = rollDiceExpr(c.dice, 0); local = local.concat(rr.results); total += rr.total; }
        total += (c.bonus || 0); dice = dice.concat(local);
        parts.push(`${c.dice || ""}${c.bonus ? signed(c.bonus) : ""}`.trim());
      });
      ev = makeEvent({ source, roll_type: "damage", label: `${a.name} damage`, expression: parts.join(" + ") || "—", dice_results: dice, total });
    } else if (kind === "skill") {
      const bonus = (() => { for (const [k, v] of Object.entries(sb.skills || {})) if (k.toLowerCase() === String(d.skill).toLowerCase()) return v; return 0; })();
      const r = rollD20(bonus, adv);
      ev = makeEvent({ source, roll_type: "check", label: `${d.skill} check`, expression: `1d20${signed(bonus)}`, dice_results: r.dice, modifier: bonus, total: r.total, advantage: adv });
    } else if (kind === "initiative") {
      const m = abMod(sb.abilities && sb.abilities.dexterity); const r = rollD20(m, adv);
      ev = makeEvent({ source, roll_type: "check", label: "Initiative", expression: `1d20${signed(m)}`, dice_results: r.dice, modifier: m, total: r.total, advantage: adv });
    } else if (kind === "save" || kind === "check") {
      const ab = d.ability; const mod = abMod(sb.abilities && sb.abilities[{ str: "strength", dex: "dexterity", con: "constitution", int: "intelligence", wis: "wisdom", cha: "charisma" }[ab]]);
      let modifier = mod, label;
      if (kind === "save") {
        const ov = (() => { for (const [k, v] of Object.entries(sb.saving_throws || {})) if (k.toLowerCase() === ab) return v; return null; })();
        modifier = ov != null ? ov : mod; label = `${ab.toUpperCase()} save`;
      } else label = `${ab.toUpperCase()} check`;
      const r = rollD20(modifier, adv);
      ev = makeEvent({ source, roll_type: kind === "save" ? "save" : "check", label, expression: `1d20${signed(modifier)}`, dice_results: r.dice, modifier, total: r.total, advantage: adv });
    } else return { _status: 400, error: `unknown roll kind '${kind}'` };
    rolls.push(ev); if (rolls.length > 200) rolls = rolls.slice(-200); await saveRolls();
    return ev;
  }

  // -------------------------------------------------------------- API router
  function jsonResp(obj, status) {
    const st = (obj && obj._status) || status || 200;
    if (obj && obj._status) delete obj._status;
    return new Response(JSON.stringify(obj), { status: st, headers: { "Content-Type": "application/json" } });
  }
  async function route(path, method, body) {
    let m;
    if (path === "/api/statblocks" && method === "GET") return jsonResp(await listStatblocks());
    if (path === "/api/statblocks" && method === "DELETE") { const n = (await dbAll("statblocks")).length; await dbClear("statblocks"); return jsonResp({ deleted: n }); }
    if ((m = path.match(/^\/api\/statblocks\/([^/]+)$/))) {
      const id = decodeURIComponent(m[1]);
      if (method === "GET") { const sb = await dbGet("statblocks", id); return sb ? jsonResp(sb) : jsonResp({ error: "not found" }, 404); }
      if (method === "POST") { body.id = id; body.owner_id = OWNER; await dbPut("statblocks", body); return jsonResp(body); }
      if (method === "DELETE") { await dbDel("statblocks", id); return jsonResp({ deleted: true }); }
    }
    if (path === "/api/encounter" && method === "GET") return jsonResp(encDump());
    if (path === "/api/encounter/spawn" && method === "POST") { await spawn(body.statblock_id, body.count || 1); return jsonResp(encDump()); }
    if (path === "/api/encounter/damage" && method === "POST") {
      const c = currentEnc.combatants.find(x => x.id === body.combatant_id);
      if (!c) return jsonResp({ error: "combatant not found" }, 404);
      const amt = +body.amount;
      if (amt >= 0) c.current_hp = Math.max(0, c.current_hp - amt);
      else c.current_hp = Math.min(c.max_hp, c.current_hp - amt);
      await saveEnc(); return jsonResp(encDump());
    }
    if (path === "/api/encounter/remove" && method === "POST") { currentEnc.combatants = currentEnc.combatants.filter(c => c.id !== body.combatant_id); renumber(); await saveEnc(); return jsonResp(encDump()); }
    if (path === "/api/encounter/add-player" && method === "POST") {
      const hp = parseInt(body.max_hp || 0, 10) || 1;
      currentEnc.combatants.push({ id: uuid(), statblock_id: "", base: body.name || "Player", display_name: body.name || "Player", initiative: parseInt(body.initiative || 0, 10), current_hp: hp, max_hp: hp, temp_hp: 0, armor_class: 10, is_player: true, conditions: [] });
      sortEnc(); await saveEnc(); return jsonResp(encDump());
    }
    if (path === "/api/encounter/condition" && method === "POST") {
      const c = currentEnc.combatants.find(x => x.id === body.combatant_id);
      if (!c) return jsonResp({ error: "combatant not found" }, 404);
      c.conditions = c.conditions || [];
      if (body.action === "remove") c.conditions = c.conditions.filter(n => n !== body.name);
      else if (!c.conditions.includes(body.name)) c.conditions.push(body.name);
      await saveEnc(); return jsonResp(encDump());
    }
    if (path === "/api/encounter/next" && method === "POST") {
      const n = currentEnc.combatants.length;
      if (n) { currentEnc.active_index++; if (currentEnc.active_index >= n) { currentEnc.active_index = 0; currentEnc.round++; } }
      await saveEnc(); return jsonResp(encDump());
    }
    if (path === "/api/encounter/clear" && method === "POST") { currentEnc = { round: 0, active_index: 0, combatants: [] }; await saveEnc(); return jsonResp(encDump()); }
    if (path === "/api/encounter/save" && method === "POST") {
      const rec = { id: uuid(), owner_id: OWNER, name: body.name || "Encounter", round: currentEnc.round, active_index: currentEnc.active_index, combatants: JSON.parse(JSON.stringify(currentEnc.combatants)) };
      await dbPut("encounters", rec); return jsonResp({ id: rec.id, name: rec.name });
    }
    if (path === "/api/encounters" && method === "GET") { const all = await dbAll("encounters"); return jsonResp(all.map(e => ({ id: e.id, name: e.name, combatants: e.combatants.length, round: e.round }))); }
    if (path === "/api/encounter/load" && method === "POST") {
      const e = await dbGet("encounters", body.encounter_id);
      if (e) { currentEnc = { round: e.round, active_index: e.active_index || 0, combatants: JSON.parse(JSON.stringify(e.combatants)) }; await saveEnc(); }
      return jsonResp(encDump());
    }
    if ((m = path.match(/^\/api\/encounters\/([^/]+)$/)) && method === "DELETE") { await dbDel("encounters", decodeURIComponent(m[1])); return jsonResp({ deleted: true }); }
    if (path === "/api/roll" && method === "POST") return jsonResp(await doRoll(body));
    if (path === "/api/rolls" && method === "GET") return jsonResp(rolls.slice(-30));
    if (path === "/api/rolls" && method === "DELETE") { rolls = []; await saveRolls(); return jsonResp({ cleared: true }); }
    if (path === "/api/ping" && method === "POST") return jsonResp({ ok: true });
    // PDF import is desktop-only in this web version
    if (path === "/api/import/start") return jsonResp({ error: "PDF import isn't available in the web app. Use “Import JSON”, or add monsters with “New Compendium Entry”." });
    if (path.startsWith("/api/import/status")) return jsonResp({ finished: true, error: "PDF import unavailable in the web app." });
    return jsonResp({ error: "not found: " + path }, 404);
  }

  // ------------------------------------------------------------ fetch shim
  const dbReady = (async function init() {
    _db = await openDB();
    currentEnc = (await kvGet("currentEncounter", null)) || { round: 0, active_index: 0, combatants: [] };
    rolls = (await kvGet("rolls", null)) || [];
    // No stat blocks ship with the app — each DM imports their own PDF locally.
    if (navigator.storage && navigator.storage.persist) { try { await navigator.storage.persist(); } catch (e) {} }
  })();

  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path.indexOf("/api/") === -1) return realFetch(input, init);
    await dbReady;
    init = init || {};
    const method = (init.method || "GET").toUpperCase();
    let body = null;
    if (init.body && typeof init.body === "string") { try { body = JSON.parse(init.body); } catch (e) { body = {}; } }
    else if (init.body) body = {};   // FormData (PDF upload) — handled as unavailable
    try { return await route(path, method, body || {}); }
    catch (e) { return jsonResp({ error: String(e) }, 500); }
  };

  // ---------------------------------------------- JSON export / import (UI)
  window.sfExport = async function () {
    await dbReady;
    const all = await dbAll("statblocks");
    const blob = new Blob([JSON.stringify(all, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "statforge-compendium.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  window.sfImport = async function (file) {
    if (!file) return;
    await dbReady;
    let data;
    try { data = JSON.parse(await file.text()); } catch (e) { alert("That file isn't valid JSON."); return; }
    const arr = Array.isArray(data) ? data : (data.statblocks || []);
    let n = 0;
    for (const sb of arr) { if (!sb || !sb.name) continue; sb.id = sb.id || uuid(); sb.owner_id = OWNER; await dbPut("statblocks", sb); n++; }
    if (typeof loadLibrary === "function") loadLibrary();
    alert(`Imported ${n} ${n === 1 ? "monster" : "monsters"}.`);
  };

  // ------------------------------------------------------ service worker
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
})();
