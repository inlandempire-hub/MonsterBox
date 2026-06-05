/* In-browser PDF import for the StatForge PWA.
 *
 * A JavaScript port of the desktop ingest pipeline (columns.py + parser.py +
 * pipeline.py), using pdf.js to extract word positions + fonts. Runs entirely
 * client-side: the DM's own PDF never leaves their browser, and the parsed stat
 * blocks are stored only in their local IndexedDB.
 */
(function () {
  "use strict";

  // =========================================================== pdf.js extraction
  function normFont(name) {
    return String(name || "").split("+").pop().split("-")[0].split(",")[0];
  }

  // group words into (text, dominant-font) lines, top->bottom, left->right
  function linesFromWords(words) {
    words = words.slice().sort((a, b) => (a.top - b.top) || (a.x0 - b.x0));
    const lines = [];
    let cur = [], curTop = null;
    const flush = () => {
      if (!cur.length) return;
      const ordered = cur.slice().sort((a, b) => a.x0 - b.x0);
      const text = ordered.map(w => w.text).join(" ").replace(/\s+/g, " ").trim();
      const counts = {};
      ordered.forEach(w => { counts[w.font] = (counts[w.font] || 0) + 1; });
      let best = "", bn = -1;
      for (const k in counts) if (counts[k] > bn) { bn = counts[k]; best = k; }
      if (text) lines.push([text, best]);
    };
    for (const w of words) {
      if (curTop === null || Math.abs(w.top - curTop) <= 4) { cur.push(w); if (curTop === null) curTop = w.top; }
      else { flush(); cur = [w]; curTop = w.top; }
    }
    flush();
    return lines;
  }

  function pageLines(words, pageWidth) {
    if (!words.length) return [];
    const mid = pageWidth / 2;
    const left = words.filter(w => (w.x0 + w.x1) / 2 < mid);
    const right = words.filter(w => (w.x0 + w.x1) / 2 >= mid);
    return linesFromWords(left).concat(linesFromWords(right));
  }

  async function extractColumnLinePages(arrayBuffer, progress) {
    const pdfjsLib = window.pdfjsLib;
    pdfjsLib.GlobalWorkerOptions.workerSrc = "vendor/pdf.worker.min.js";
    const pdf = await pdfjsLib.getDocument({ data: arrayBuffer }).promise;
    const pages = [];
    for (let p = 1; p <= pdf.numPages; p++) {
      const page = await pdf.getPage(p);
      const vp = page.getViewport({ scale: 1 });
      const tc = await page.getTextContent();
      const styles = tc.styles || {};
      const words = [];
      for (const it of tc.items) {
        const s = it.str;
        if (!s || !s.trim()) continue;
        const x0 = it.transform[4];
        const top = vp.height - it.transform[5];
        const size = Math.hypot(it.transform[0], it.transform[1]) || (it.height || 10);
        const fam = (styles[it.fontName] && styles[it.fontName].fontFamily) || it.fontName || "";
        words.push({ text: s, x0, x1: x0 + (it.width || 0), top, font: normFont(fam) + "#" + Math.round(size) });
      }
      pages.push(pageLines(words, vp.width));
      page.cleanup && page.cleanup();
      if (progress) progress(p, pdf.numPages);
    }
    pdf.destroy && pdf.destroy();
    return pages;
  }

  // ===================================================================== regexes
  const TYPES = "aberration|beast|celestial|construct|dragon|elemental|fey|fiend|giant|humanoid|monstrosity|ooze|plant|undead";
  const RE_META = new RegExp("^(Tiny|Small|Medium|Large|Huge|Gargantuan)\\s+((?:swarm of \\w+ )?(?:" + TYPES + ")s?(?:\\s*\\([^)]*\\))?)\\s*,\\s*(.+)$", "i");
  const RE_META_LOOSE = new RegExp("^\\w+\\s+((?:" + TYPES + ")s?(?:\\s*\\([^)]*\\))?)\\s*,\\s*(.+)$", "i");
  const RE_AC = /Armor Class\s+(\d+)\s*(\([^)]*\))?/i;
  const RE_HP = /Hit Points\s+(\d+)\s*(?:\(([^)]*)\))?/i;
  const RE_SPEED = /Speed\s+(.+)/i;
  const RE_ABILITY_PAIR = /(\d+)\s*\(\s*[^)\d]*?(\d+)\s*\)/g;
  const RE_CHALLENGE = /Challenges?\s+([0-9/]+)\s*(?:\(([\d,]+)\s*XP\)?)?/i;
  const RE_PROF = /Proficiency Bonus\s+\+?(\d+)/i;
  const RE_SPEED_PART = /(?:(\w+)\s+)?(\d+)\s*ft/gi;
  const RE_AC_LINE = /^\s*Armor Class\b/i;
  const RE_SAVES = /Saving Throws\s+(.+)/i;
  const RE_SKILLS = /Skills\s+(.+)/i;
  const RE_SENSES = /Senses\s+(.+)/i;
  const RE_LANGS = /Languages\s+(.+)/i;
  const RE_PASSIVE = /passive Perception\s+(\d+)/i;
  const RE_DMG = /Damage (Vulnerabilities|Resistances|Immunities)\s+(.+)/gi;
  const RE_COND = /Condition Immunities\s+(.+)/i;
  const RE_BONUS_PAIR = /(.+?)\s*([+-]\d+)/;
  const RE_ATTACK = /(Melee|Ranged)\s+(Weapon|Spell)\s+Attack:\s*\+?(\d+)\s*to hit(?:,\s*(?:reach\s+(\d+)\s*ft|range\s+([\d/]+)\s*ft))?/i;
  const RE_DAMAGE = /(\d+)\s*\(\s*(\d+d\d+)\s*([+-]\s*\d+)?\s*\)\s*([a-zA-Z]+)?\s*damage/gi;
  const RE_SAVE = /DC\s*(\d+)\s*(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s*saving throw/i;
  const RE_LEG_COUNT = /(\d+)\s+legendary action/i;
  const SECTION_SRC = "^[ \\t]*(LEGENDARY ACTIONS|BONUS ACTIONS|REACTIONS|ACTIONS)[ \\t]*$";
  const RE_SECTION_LINE = new RegExp(SECTION_SRC, "i");
  const reSectionG = () => new RegExp(SECTION_SRC, "gim");
  const RE_ENTRY_SRC = "^[ \\t>\\u2022*\\-]*([A-Z][A-Za-z0-9:\\u2019'/\\-]+(?:\\s+[A-Za-z0-9:\\u2019'/\\-]+){0,5}?(?:\\s*\\([^)]*\\))?)[ \\t]*\\.[ \\t]+(?=[A-Z(])";
  const reEntryG = () => new RegExp(RE_ENTRY_SRC, "gm");

  const SIZES = { tiny: "Tiny", small: "Small", medium: "Medium", large: "Large", huge: "Huge", gargantuan: "Gargantuan" };
  const ABIL_BY_NAME = { strength: "str", dexterity: "dex", constitution: "con", intelligence: "int", wisdom: "wis", charisma: "cha" };
  const SECTION_HEADER_WORDS = new Set(["aberrations", "beasts", "celestials", "constructs", "dragons", "elementals", "fey", "fiends", "giants", "humanoids", "monstrosities", "oozes", "plants", "undead"]);
  const NON_NAME_WORDS = new Set(["alignment", "actions", "reactions", "traits", "description"]);
  const NON_HEADER_NAMES = new Set(["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]);
  const NAME_CONNECTORS = new Set(["of", "with", "and", "the", "to", "a", "an", "in", "or", "from", "by", "for", "on", "at", "as", "into", "upon", "but"]);
  const STAT_FIELD_PREFIXES = ["armor class", "hit points", "speed", "saving throws", "skills", "senses", "languages", "challenge", "damage ", "condition ", "proficiency"];
  const SENTENCE_END = ".!?\"')’”";
  const HEADER_TO_CAT = { ACTIONS: "action", "BONUS ACTIONS": "bonus_action", REACTIONS: "reaction", "LEGENDARY ACTIONS": "legendary" };

  // ===================================================================== helpers
  const titleCase = (s) => String(s || "").toLowerCase().replace(/\b[a-z]/g, c => c.toUpperCase());
  const isUpper = (c) => c >= "A" && c <= "Z";
  const stripEdge = (s, chars) => { let i = 0, j = s.length; while (i < j && chars.includes(s[i])) i++; while (j > i && chars.includes(s[j - 1])) j--; return s.slice(i, j); };

  function parseSpeed(text) { const out = {}; let m; RE_SPEED_PART.lastIndex = 0; while ((m = RE_SPEED_PART.exec(text))) out[(m[1] || "walk").toLowerCase()] = +m[2]; return out; }
  function parseSenses(text) { const out = {}; let m; RE_SPEED_PART.lastIndex = 0; while ((m = RE_SPEED_PART.exec(text))) if (m[1]) out[m[1].toLowerCase()] = +m[2]; return out; }
  function parseAbilities(text) {
    const pairs = []; let m; RE_ABILITY_PAIR.lastIndex = 0;
    while ((m = RE_ABILITY_PAIR.exec(text))) pairs.push(+m[1]);
    if (pairs.length < 6) return null;
    return { strength: pairs[0], dexterity: pairs[1], constitution: pairs[2], intelligence: pairs[3], wisdom: pairs[4], charisma: pairs[5] };
  }
  function parseBonuses(text) { const out = {}; for (const part of String(text).split(",")) { const m = RE_BONUS_PAIR.exec(part); if (m && m[1].trim()) out[m[1].trim()] = +m[2]; } return out; }
  function parseList(text) { text = String(text).trim(); if (["none", "-", "—", "–", ""].includes(text.toLowerCase())) return []; return text.split(/[,;]/).map(s => s.trim()).filter(Boolean); }
  function parseDamage(text) {
    const comps = []; let m; RE_DAMAGE.lastIndex = 0;
    while ((m = RE_DAMAGE.exec(text))) comps.push({ dice: m[2], bonus: m[3] ? +m[3].replace(/\s+/g, "") : 0, average: +m[1], damage_type: (m[4] || "").toLowerCase() || null, notes: null });
    return comps;
  }

  function looksLikeTitle(line) {
    const s = line.trim();
    if (!s || s.length > 50 || s.split(/\s+/).length > 6) return false;
    if (".,:;".includes(s[s.length - 1])) return false;
    if (!isUpper(s[0])) return false;
    if (SECTION_HEADER_WORDS.has(s.toLowerCase())) return false;
    return !RE_AC_LINE.test(s);
  }
  function nameLike(line) {
    const s = line.trim();
    if (!s || s.length > 45) return false;
    const words = s.split(/\s+/);
    if (words.length > 6 || ".,:;".includes(s[s.length - 1])) return false;
    const low = s.toLowerCase();
    if (SECTION_HEADER_WORDS.has(low) || NON_NAME_WORDS.has(low) || RE_AC_LINE.test(s)) return false;
    if (RE_SECTION_LINE.test(s)) return false;
    if (RE_META.test(s) || RE_META_LOOSE.test(s)) return false;
    if (STAT_FIELD_PREFIXES.some(k => low.startsWith(k))) return false;
    const toks = s.toUpperCase().split(/\s+/);
    if (toks.filter(t => ["STR", "DEX", "CON", "INT", "WIS", "CHA"].includes(t)).length >= 3) return false;
    const letters = (s.match(/[A-Za-z]/g) || []);
    if (letters.length < 2) return false;
    if (letters.filter(c => isUpper(c)).length / letters.length >= 0.6) return true;
    const sig = words.filter(w => !NAME_CONNECTORS.has(w.toLowerCase()));
    return sig.length > 0 && sig.every(w => !/[A-Za-z]/.test(w[0]) || isUpper(w[0]));
  }
  function findName(lines, metaI, lower) {
    lower = lower || 0;
    const titles = [];
    let j = metaI - 1;
    while (j >= lower && lines[j].trim() && looksLikeTitle(lines[j]) && titles.length < 3) { titles.unshift(lines[j].trim()); j--; }
    if (titles.length) return titles.join(" ");
    j = metaI - 1; let steps = 0;
    while (j >= lower && steps < 30) { const s = lines[j].trim(); if (s && nameLike(s)) return s; j--; steps++; }
    return "";
  }
  function stripFooter(body) { return body.replace(/[ \t\r\n]+\d{1,4}\s*$/, "").replace(/\s+$/, ""); }
  const hasActionsSection = (text) => reSectionG().test(text);

  function isFeatureName(name) {
    const words = name.replace(/\([^)]*\)/g, "").split(/\s+/);
    for (let i = 1; i < words.length; i++) {
      const token = stripEdge(words[i], ".,:;'’\"");
      if (token && token[0] === token[0].toLowerCase() && /[a-z]/i.test(token[0]) && !NAME_CONNECTORS.has(token.toLowerCase())) return false;
    }
    return true;
  }

  function buildAction(name, body, category) {
    const cleanName = name.replace(/\s*\([^)]*\)/g, "").trim() || name.trim();
    const action = { name: cleanName, category, raw_text: body.trim(), attack: null, damage: [], save: null, recharge: null, usage: null, legendary_cost: 1 };
    const paren = /\(([^)]*)\)/.exec(name);
    if (paren) {
      const p = paren[1]; let mm;
      if ((mm = /recharge\s+([0-9–\-]+)/i.exec(p))) action.recharge = "Recharge " + mm[1];
      else if (/\d+\s*\/\s*day/i.test(p)) action.usage = p.trim();
      else if ((mm = /costs?\s+(\d+)\s+actions?/i.exec(p))) action.legendary_cost = +mm[1];
    }
    const am = RE_ATTACK.exec(body);
    if (am) action.attack = { kind: am[1].toLowerCase() + "_" + am[2].toLowerCase(), to_hit: +am[3], reach_ft: am[4] ? +am[4] : null, range_ft: am[5] || null, targets: "one target" };
    action.damage = parseDamage(body);
    const sm = RE_SAVE.exec(body);
    if (sm) action.save = { ability: ABIL_BY_NAME[sm[2].toLowerCase()], dc: +sm[1], on_success: /half/i.test(body) ? "half damage" : null };
    return action;
  }

  function parseEntries(sectionText, category) {
    if (!sectionText.trim()) return [];
    const accepted = []; let m; const re = reEntryG();
    while ((m = re.exec(sectionText))) {
      const nm = m[1].replace(/\s*\([^)]*\)/g, "").trim().toLowerCase();
      if (NON_HEADER_NAMES.has(nm)) continue;
      if (!isFeatureName(m[1])) continue;
      const prev = sectionText.slice(0, m.index).replace(/\s+$/, "");
      if (!prev || SENTENCE_END.includes(prev[prev.length - 1])) accepted.push({ name: m[1], start: m.index, end: re.lastIndex });
    }
    const entries = [];
    for (let i = 0; i < accepted.length; i++) {
      const end = i + 1 < accepted.length ? accepted[i + 1].start : sectionText.length;
      entries.push(buildAction(accepted[i].name, sectionText.slice(accepted[i].end, end), category));
    }
    return entries;
  }

  function trimStatHeader(region) {
    let cut = 0;
    for (const reSrc of [RE_PROF, RE_CHALLENGE]) {
      const re = new RegExp(reSrc.source, "gi"); let m, last = null;
      while ((m = re.exec(region))) last = m;
      if (last) { const nl = region.indexOf("\n", last.index + last[0].length); cut = Math.max(cut, nl !== -1 ? nl + 1 : last.index + last[0].length); }
    }
    return region.slice(cut);
  }
  function splitSections(text) {
    const matches = []; let m; const re = reSectionG();
    while ((m = re.exec(text))) matches.push({ head: m[1], start: m.index, end: re.lastIndex });
    const first = matches.length ? matches[0].start : text.length;
    const traitsText = trimStatHeader(text.slice(0, first));
    const sections = {};
    for (let i = 0; i < matches.length; i++) {
      const cat = HEADER_TO_CAT[matches[i].head.toUpperCase()];
      const end = i + 1 < matches.length ? matches[i + 1].start : text.length;
      sections[cat] = text.slice(matches[i].end, end);
    }
    return { traitsText, sections };
  }

  // ============================================================ split into blocks
  function splitIntoBlocks(pageText, fonts) {
    const lines = pageText.split("\n");
    if (fonts && fonts.length !== lines.length) fonts = null;
    const acIdxs = []; lines.forEach((ln, i) => { if (RE_AC_LINE.test(ln)) acIdxs.push(i); });
    if (!acIdxs.length) return [];
    const specs = acIdxs.map(ac => { let mi = ac - 1; while (mi >= 0 && !lines[mi].trim()) mi--; return [mi, ac]; });
    const blocks = [];
    for (let k = 0; k < specs.length; k++) {
      const [metaI, ac] = specs[k];
      const lower = k > 0 ? specs[k - 1][1] + 1 : 0;
      const name = findName(lines, metaI, lower) || "Unknown Creature";
      const hardEnd = k + 1 < specs.length ? specs[k + 1][0] : lines.length;
      let rest;
      if (fonts) {
        const sampleEnd = Math.min(ac + 8, hardEnd);
        const sample = [];
        for (let j = ac + 1; j < sampleEnd; j++) if (j < fonts.length && fonts[j]) sample.push(fonts[j]);
        let sbFont;
        if (sample.length) { const c = {}; let bn = -1; sample.forEach(f => { c[f] = (c[f] || 0) + 1; if (c[f] > bn) { bn = c[f]; sbFont = f; } }); }
        else sbFont = fonts[ac];
        const kept = [lines[metaI]];
        for (let i = metaI + 1; i < hardEnd; i++) if (i === ac || fonts[i] === sbFont || RE_SECTION_LINE.test(lines[i])) kept.push(lines[i]);
        rest = kept.join("\n");
      } else rest = lines.slice(metaI, hardEnd).join("\n");
      const body = stripFooter((name + "\n" + rest).trim());
      if (body) blocks.push(body);
    }
    return blocks;
  }

  // ===================================================================== parseText
  function parseText(text, sourcePage, source) {
    const lines = text.split(/\r?\n/).map(l => l.replace(/\s+$/, "")).filter(l => l.trim());
    let found = 0;
    const sb = {
      name: lines.length ? lines[0].trim() : "Unknown Creature",
      size: null, creature_type: null, alignment: null,
      armor_class: 10, armor_desc: null, hit_points: 1, hit_dice: null,
      speed: {}, abilities: { strength: 10, dexterity: 10, constitution: 10, intelligence: 10, wisdom: 10, charisma: 10 },
      saving_throws: {}, skills: {}, damage_vulnerabilities: [], damage_resistances: [], damage_immunities: [],
      condition_immunities: [], senses: {}, passive_perception: null, languages: [],
      challenge_rating: null, xp: null, proficiency_bonus: null,
      traits: [], actions: [], bonus_actions: [], reactions: [], legendary_actions: [], legendary_action_count: 0,
      spellcasting: null, source: source || null, source_page: sourcePage || null,
      raw_text: text || null, parse_confidence: 0, parse_warnings: [],
    };
    for (const ln of lines.slice(1, 5)) {
      let m = RE_META.exec(ln.trim());
      if (m) { sb.size = SIZES[m[1].toLowerCase()] || null; sb.creature_type = titleCase(m[2]); sb.alignment = m[3].trim(); break; }
      const lm = RE_META_LOOSE.exec(ln.trim());
      if (lm) { sb.creature_type = titleCase(lm[1]); sb.alignment = lm[2].trim(); break; }
    }
    let m;
    if ((m = RE_AC.exec(text))) { sb.armor_class = +m[1]; sb.armor_desc = (m[2] || "").replace(/^[()\s]+|[()\s]+$/g, "") || null; found++; }
    if ((m = RE_HP.exec(text))) { sb.hit_points = +m[1]; sb.hit_dice = (m[2] || "").trim() || null; found++; }
    if ((m = RE_SPEED.exec(text))) { sb.speed = parseSpeed(m[1]); found++; }
    const ab = parseAbilities(text); if (ab) { sb.abilities = ab; found++; }
    if ((m = RE_CHALLENGE.exec(text))) { sb.challenge_rating = m[1]; if (m[2]) sb.xp = +m[2].replace(/,/g, ""); found++; }
    if ((m = RE_PROF.exec(text))) sb.proficiency_bonus = +m[1];
    if ((m = RE_SAVES.exec(text))) sb.saving_throws = parseBonuses(m[1]);
    if ((m = RE_SKILLS.exec(text))) sb.skills = parseBonuses(m[1]);
    if ((m = RE_SENSES.exec(text))) sb.senses = parseSenses(m[1]);
    if ((m = RE_PASSIVE.exec(text))) sb.passive_perception = +m[1];
    if ((m = RE_LANGS.exec(text))) sb.languages = parseList(m[1]);
    let dm; RE_DMG.lastIndex = 0;
    while ((dm = RE_DMG.exec(text))) { const lst = parseList(dm[2]); const k = dm[1].toLowerCase(); if (k === "vulnerabilities") sb.damage_vulnerabilities = lst; else if (k === "resistances") sb.damage_resistances = lst; else if (k === "immunities") sb.damage_immunities = lst; }
    if ((m = RE_COND.exec(text))) sb.condition_immunities = parseList(m[1]);

    const { traitsText, sections } = splitSections(text);
    sb.traits = parseEntries(traitsText, "trait");
    sb.actions = parseEntries(sections["action"] || "", "action");
    sb.bonus_actions = parseEntries(sections["bonus_action"] || "", "bonus_action");
    sb.reactions = parseEntries(sections["reaction"] || "", "reaction");
    const legText = sections["legendary"] || "";
    sb.legendary_actions = parseEntries(legText, "legendary");
    const lm = RE_LEG_COUNT.exec(legText); if (lm) sb.legendary_action_count = +lm[1];

    sb.parse_confidence = Math.round((found / 5) * 100) / 100;
    return sb;
  }

  // ============================================================= page chrome strip
  const SIZE_WORDS = new Set(["tiny", "small", "medium", "large", "huge", "gargantuan"]);
  const CHROME_PROTECT = ["armor class", "hit points", "speed", "saving throws", "skills", "senses", "languages", "challenge", "damage ", "condition ", "proficiency"];
  function isStructuralLine(s) {
    if (RE_SECTION_LINE.test(s)) return true;
    const toks = s.toUpperCase().split(/\s+/);
    if (toks.filter(t => ["STR", "DEX", "CON", "INT", "WIS", "CHA"].includes(t)).length >= 3) return true;
    const low = s.toLowerCase(); const w0 = low.split(/\s+/)[0];
    if (SIZE_WORDS.has(w0)) return true;
    return CHROME_PROTECT.some(p => low.startsWith(p));
  }
  const RE_FURNITURE = /^(?:[A-Za-z]|\d{1,4}|[A-Za-z]\s+\d{1,4}|\d{1,4}\s+[A-Za-z])$/;
  const isFurniture = (s) => RE_FURNITURE.test(s.trim());
  function stripPageChrome(linePages) {
    const n = linePages.length;
    if (n < 4) return linePages;
    const freq = {};
    for (const page of linePages) { const seen = new Set(page.map(([t]) => t.trim()).filter(Boolean)); for (const s of seen) freq[s] = (freq[s] || 0) + 1; }
    const threshold = Math.max(5, Math.floor(0.03 * n));
    const chrome = new Set();
    for (const s in freq) if (freq[s] >= threshold && s.length <= 30 && !".!?".includes(s[s.length - 1]) && !isStructuralLine(s)) chrome.add(s);
    return linePages.map(page => page.filter(([t]) => { const s = t.trim(); return !chrome.has(s) && !isFurniture(s); }));
  }

  // ============================================================ blocks from pages
  const RE_AC_PLAIN = /^\s*Armor Class\b/i;
  // NOTE: unlike the desktop parser, we do NOT font-filter blocks. pdf.js gives
  // much coarser font info than pdfplumber (it doesn't cluster a stat block's
  // body into one font), so a majority-font filter wrongly discards the ability
  // row and the whole actions section. The two-column split already isolates
  // each stat block from its lore, so a font-less split is both simpler and far
  // more reliable in the browser (ToB3: 12/406 with actions -> 405/406).
  const pageAllText = (page) => page.map(([t]) => t).join("\n");
  function preAcText(page) { const kept = []; for (const [t] of page) { if (RE_AC_PLAIN.test(t)) break; kept.push(t); } return kept.join("\n"); }

  function blocksFromPages(linePages, source) {
    linePages = stripPageChrome(linePages);
    const results = [];
    let pending = null;
    const flush = () => { if (pending !== null) { try { results.push(parseText(pending.body, pending.page, source)); } catch (e) {} pending = null; } };
    for (let i = 0; i < linePages.length; i++) {
      const page = linePages[i];
      const pageText = pageAllText(page);
      const blocks = splitIntoBlocks(pageText);   // font-less
      if (!blocks.length) {
        // whole page is continuation of a block truncated at the previous page break
        if (pending !== null && pageText.trim()) pending.body += "\n" + pageText;
        continue;
      }
      if (pending !== null) { const pre = preAcText(page); if (pre.trim()) pending.body += "\n" + pre; flush(); }
      for (let j = 0; j < blocks.length; j++) {
        const isLast = j === blocks.length - 1;
        if (isLast && !hasActionsSection(blocks[j])) pending = { body: blocks[j], page: i + 1 };
        else { try { results.push(parseText(blocks[j], i + 1, source)); } catch (e) {} }
      }
    }
    flush();
    return results;
  }

  // ================================================================ public: import
  async function sfImportPdf(file) {
    const msg = document.getElementById("importmsg");
    const show = (html, busy) => { if (msg) { msg.className = busy ? "busy" : ""; msg.innerHTML = html; } };
    if (!file) return;
    if (!/\.pdf$/i.test(file.name)) { show("Please choose a .pdf file."); return; }
    if (!window.pdfjsLib) { show("PDF engine failed to load."); return; }
    show("Reading " + escapeHtml(file.name) + "…", true);
    let buf;
    try { buf = await file.arrayBuffer(); } catch (e) { show("Couldn't read the file."); return; }
    let pages;
    try {
      pages = await extractColumnLinePages(buf, (cur, total) => {
        const pct = total ? Math.round((100 * cur) / total) : 0;
        show("Reading " + escapeHtml(file.name) + "… page " + cur + "/" + total +
          '<div class="pbar"><div style="width:' + pct + '%"></div></div>', true);
      });
    } catch (e) { show("Couldn't parse the PDF: " + escapeHtml(String(e))); return; }
    // text-layer check (scanned PDFs have ~no text)
    const totalChars = pages.reduce((a, pg) => a + pg.reduce((b, [t]) => b + t.length, 0), 0);
    if (!pages.length || totalChars < 40 * pages.length) {
      show("No text layer found — this looks like a scanned PDF, which the web app can't read. (The desktop app can OCR / use the vision parser.)");
      return;
    }
    show("Parsing stat blocks…", true);
    let blocks;
    try { blocks = blocksFromPages(pages, file.name); } catch (e) { show("Parse error: " + escapeHtml(String(e))); return; }
    let n = 0;
    for (const sb of blocks) {
      sb.id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "sb-" + Date.now() + "-" + n;
      try { await fetch("/api/statblocks/" + sb.id, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sb) }); n++; } catch (e) {}
    }
    const low = blocks.filter(b => b.parse_confidence < 0.6).length;
    show("Imported <b>" + n + "</b> " + (n === 1 ? "monster" : "monsters") + " from " + escapeHtml(file.name) +
      (low ? ' <span class="warn">(' + low + " low-confidence — check them)</span>" : ""));
    if (typeof window.loadLibrary === "function") window.loadLibrary();
  }
  function escapeHtml(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

  window.sfImportPdf = sfImportPdf;
})();
