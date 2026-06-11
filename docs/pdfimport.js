/* In-browser PDF import for the MonsterBox PWA.
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

  // Return the page as an array of COLUMNS (each a list of lines). A stat block
  // that flows from the bottom of one column to the top of the next is then
  // handled by the same continuation logic that joins a block across a page break
  // — far more reliable than mashing both columns into one text and guessing
  // boundaries. Single-column pages return one column.
  function pageColumns(words, pageWidth) {
    if (!words.length) return [[]];
    // Detect a real two-column layout by finding a vertical GUTTER: a central x
    // position where most text rows have a gap. This is robust to a full-width
    // header sitting above a two-column body (which defeats a simple straddle
    // ratio), and it splits at the actual gutter rather than the page midpoint.
    const sorted = words.slice().sort((a, b) => a.top - b.top);
    const rows = []; let cur = [], curTop = null;
    for (const w of sorted) {
      if (curTop === null || Math.abs(w.top - curTop) <= 4) { cur.push(w); if (curTop === null) curTop = w.top; }
      else { rows.push(cur); cur = [w]; curTop = w.top; }
    }
    if (cur.length) rows.push(cur);
    const left = Math.min(...words.map(w => w.x0));
    const right = Math.max(...words.map(w => w.x1));
    const span = right - left;
    if (span < 80 || rows.length < 6) return [linesFromWords(words)];
    let bestX = -1, bestEmpty = -1;
    for (let f = 0.34; f <= 0.66; f += 0.02) {
      const gx = left + span * f;
      let empty = 0;
      for (const row of rows) if (!row.some(w => w.x0 <= gx && w.x1 >= gx)) empty++;
      const frac = empty / rows.length;
      if (frac > bestEmpty) { bestEmpty = frac; bestX = gx; }
    }
    // need a clear gutter (most rows gap here) AND real content on both sides
    if (bestEmpty < 0.60) return [linesFromWords(words)];
    const L = words.filter(w => (w.x0 + w.x1) / 2 < bestX);
    const R = words.filter(w => (w.x0 + w.x1) / 2 >= bestX);
    if (L.length / words.length < 0.12 || R.length / words.length < 0.12) return [linesFromWords(words)];
    return [linesFromWords(L), linesFromWords(R)];
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
      const seen = new Set();   // drop double-rendered text (shadow/stroke "LAIR LAIR")
      for (const it of tc.items) {
        const s = it.str;
        if (!s || !s.trim()) continue;
        // skip rotated / vertical text — sidebar watermarks (e.g. "WYRMLING",
        // "SUMMER") that pdf.js interleaves into the stat-block lines
        if (Math.abs(it.transform[1]) > 0.5 * Math.abs(it.transform[0] || 1)) continue;
        const x0 = it.transform[4];
        const top = vp.height - it.transform[5];
        const key = s + "@" + Math.round(x0 / 2) + "," + Math.round(top / 2);
        if (seen.has(key)) continue;     // same glyphs drawn twice at one spot
        seen.add(key);
        const size = Math.hypot(it.transform[0], it.transform[1]) || (it.height || 10);
        const fam = (styles[it.fontName] && styles[it.fontName].fontFamily) || it.fontName || "";
        words.push({ text: s, x0, x1: x0 + (it.width || 0), top, font: normFont(fam) + "#" + Math.round(size) });
      }
      for (const col of pageColumns(words, vp.width)) pages.push(col);
      page.cleanup && page.cleanup();
      if (progress) progress(p, pdf.numPages);
    }
    pdf.destroy && pdf.destroy();
    return pages;
  }

  // ===================================================================== regexes
  const TYPES = "aberration|beast|celestial|construct|dragon|elemental|fey|fiend|giant|humanoid|monstrosity|ooze|plant|undead";
  const SIZE_ALT = "Tiny|Small|Medium|Large|Huge|Gargantuan";
  // allow a dual size like "Medium or Small" (2024 SRD) — capture the first size
  const RE_META = new RegExp("^(" + SIZE_ALT + ")(?:\\s+or\\s+\\w+)?\\s+((?:swarm of \\w+ )?(?:" + TYPES + ")s?(?:\\s*\\([^)]*\\))?)\\s*,\\s*(.+)$", "i");
  const RE_META_LOOSE = new RegExp("^\\w+\\s+((?:" + TYPES + ")s?(?:\\s*\\([^)]*\\))?)\\s*,\\s*(.+)$", "i");
  const RE_META_SIZETYPE = new RegExp("^(" + SIZE_ALT + ")(?:\\s+or\\s+\\w+)?\\s+((?:" + TYPES + ")s?(?:\\s*\\([^)]*\\))?)\\s*$", "i");
  // Compact layouts print the NAME and the size/type/alignment on ONE line, e.g.
  // "Kyanos B'lot Large Aberration (Shapechanger), Chaotic" — split name off the meta.
  const RE_NAME_META = new RegExp("^(.+?)\\s+(" + SIZE_ALT + ")\\s+((?:swarm of \\w+ )?(?:" + TYPES + ")s?(?:\\s*\\([^)]*\\))?)\\s*,?\\s*(.*)$", "i");
  // an optional ":" after every field label — some books write "Armor Class: 16"
  const RE_AC = /(?:Armor Class|AC):?\s+(\d+)\s*(\([^)]*\))?/i;
  const RE_HP = /(?:Hit Points|HP):?\s+(\d+)\s*(?:\(([^)]*)\))?/i;
  const RE_SPEED = /Speed:?\s+(.+)/i;
  const RE_ABILITY_PAIR = /(\d+)\s*\(\s*[^)\d]*?(\d+)\s*\)/g;
  // matches 2014 "Challenge 5 (1,800 XP)", Free5e "Challenge 21", and 2024 "CR 2 (XP 450; PB +2)"
  const RE_CHALLENGE = /(?:Challenges?|\bCR):?\s+([0-9/]+)\s*(?:\(\s*(?:([\d,]+)\s*XP|XP\s*([\d,]+))[^)]*\))?/i;
  const RE_PROF = /Proficiency Bonus:?\s+\+?(\d+)/i;
  const RE_SPEED_PART = /(?:(\w+)\s+)?(\d+)\s*ft/gi;
  const RE_AC_LINE = /^\s*[•▪◦·*\-]?\s*(?:Armor Class|AC):?\s+\d/i;
  const RE_SAVES = /Saving Throws:?\s+(.+)/i;
  const RE_SKILLS = /Skills:?\s+(.+)/i;
  const RE_SENSES = /Senses:?\s+(.+)/i;
  const RE_LANGS = /Languages:?\s+(.+)/i;
  const RE_PASSIVE = /passive Perception:?\s+(\d+)/i;
  const RE_DMG = /Damage (Vulnerabilities|Resistances|Immunities):?\s+(.+)/gi;
  const RE_COND = /Condition Immunities:?\s+(.+)/i;
  const RE_BONUS_PAIR = /(.+?)\s*([+-]\d+)/;
  const RE_ATTACK = /(Melee|Ranged)\s+(Weapon|Spell)\s+Attack[.:]?\s*\+?(\d+)\s*to hit(?:,\s*(?:reach\s+(\d+)\s*ft|range\s+([\d/]+)\s*ft))?/i;
  // 2024 form: "Melee Attack Roll: +5, reach 5 ft." / "Ranged Attack Roll: +5, range 30/90 ft."
  const RE_ATTACK_2024 = /(Melee|Ranged)\s+Attack Roll:\s*\+?(\d+)(?:,\s*(?:reach\s+(\d+)\s*ft|range\s+([\d/]+)\s*ft))?/i;
  const RE_DAMAGE = /(\d+)\s*\(\s*(\d+d\d+)\s*([+-]\s*\d+)?\s*\)\s*([a-zA-Z]+)?\s*damage/gi;
  const RE_SAVE = /DC\s*(\d+)\s*(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)\s*saving throw/i;
  const RE_LEG_COUNT = /(\d+)\s+legendary action/i;
  const SECTION_SRC = "^[ \\t]*(LEGENDARY ACTIONS?|BONUS ACTIONS?|REACTIONS?|ACTIONS?)[ \\t]*$";
  const RE_SECTION_LINE = new RegExp(SECTION_SRC, "i");
  const reSectionG = () => new RegExp(SECTION_SRC, "gim");
  const RE_ENTRY_SRC = "^[ \\t>\\u2022*\\-]*([A-Z][A-Za-z0-9:\\u2019'/\\-]+(?:\\s+[A-Za-z0-9:\\u2019'/\\-]+){0,5}?(?:\\s*\\([^)]*\\))?)[ \\t]*\\.[ \\t]+(?=[A-Z(])";
  const reEntryG = () => new RegExp(RE_ENTRY_SRC, "gm");

  const SIZES = { tiny: "Tiny", small: "Small", medium: "Medium", large: "Large", huge: "Huge", gargantuan: "Gargantuan" };
  const ABIL_BY_NAME = { strength: "str", dexterity: "dex", constitution: "con", intelligence: "int", wisdom: "wis", charisma: "cha" };
  const SECTION_HEADER_WORDS = new Set(["aberrations", "beasts", "celestials", "constructs", "dragons", "elementals", "fey", "fiends", "giants", "humanoids", "monstrosities", "oozes", "plants", "undead"]);
  const NON_NAME_WORDS = new Set(["alignment", "actions", "reactions", "traits", "description"]);
  const NON_HEADER_NAMES = new Set(["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma",
    // stat-field labels that get absorbed from interleaved rules/archetype text
    "skills", "senses", "languages", "hd", "cr", "hit dice", "proficiency bonus", "ability score increase",
    "natural armor", "damage vulnerabilities", "damage immunities", "damage resistances", "condition immunities"]);
  const NAME_CONNECTORS = new Set(["of", "with", "and", "the", "to", "a", "an", "in", "or", "from", "by", "for", "on", "at", "as", "into", "upon", "but"]);
  const STAT_FIELD_PREFIXES = ["armor class", "hit points", "speed", "saving throws", "skills", "senses", "languages", "challenge", "damage ", "condition ", "proficiency",
    "ac ", "hp ", "cr ", "initiative", "immunities", "resistances", "vulnerabilities", "gear ", "mod save"];
  const SENTENCE_END = ".!?\"')’”";
  const HEADER_TO_CAT = { ACTIONS: "action", ACTION: "action", "BONUS ACTIONS": "bonus_action", "BONUS ACTION": "bonus_action", REACTIONS: "reaction", REACTION: "reaction", "LEGENDARY ACTIONS": "legendary", "LEGENDARY ACTION": "legendary" };

  // ===================================================================== helpers
  const titleCase = (s) => String(s || "").toLowerCase().replace(/\b[a-z]/g, c => c.toUpperCase());
  const isUpper = (c) => c >= "A" && c <= "Z";
  const stripEdge = (s, chars) => { let i = 0, j = s.length; while (i < j && chars.includes(s[i])) i++; while (j > i && chars.includes(s[j - 1])) j--; return s.slice(i, j); };

  function parseSpeed(text) { const out = {}; let m; RE_SPEED_PART.lastIndex = 0; while ((m = RE_SPEED_PART.exec(text))) out[(m[1] || "walk").toLowerCase()] = +m[2]; return out; }
  function parseSenses(text) { const out = {}; let m; RE_SPEED_PART.lastIndex = 0; while ((m = RE_SPEED_PART.exec(text))) if (m[1]) out[m[1].toLowerCase()] = +m[2]; return out; }
  const ABIL_KEY = { str: "strength", dex: "dexterity", con: "constitution", int: "intelligence", wis: "wisdom", cha: "charisma" };
  function parseAbilities(text) {
    // 2014 / Free5e: "18 (+4)" pairs, six in a row (score then modifier in parens)
    const pairs = []; let m; RE_ABILITY_PAIR.lastIndex = 0;
    while ((m = RE_ABILITY_PAIR.exec(text))) pairs.push(+m[1]);
    if (pairs.length >= 6) return { strength: pairs[0], dexterity: pairs[1], constitution: pairs[2], intelligence: pairs[3], wisdom: pairs[4], charisma: pairs[5] };
    return parseAbilities2024(text);
  }
  // 2024 SRD ability TABLE: "Str 15 +2 +4 Dex 16 +3 +5 Con 14 +2 +2" over two rows.
  // pdf.js often splits the first letter ("S tr", "W IS"), so allow inner spaces.
  function parseAbilities2024(text) {
    const norm = text
      .replace(/\bS[ \t]*tr\b/gi, "Str").replace(/\bD[ \t]*ex\b/gi, "Dex")
      .replace(/\bC[ \t]*on\b/gi, "Con").replace(/\bI[ \t]*nt\b/gi, "Int")
      .replace(/\bW[ \t]*is\b/gi, "Wis").replace(/\bC[ \t]*ha\b/gi, "Cha");
    // mod + save follow the score; pdf.js sometimes drops a +/− sign, so keep them optional
    const re = /\b(Str|Dex|Con|Int|Wis|Cha)\b\s+(\d{1,2})\s+[+\-−]?\d+\s+[+\-−]?\d+/gi;
    const out = {}; let m;
    while ((m = re.exec(norm))) { const k = ABIL_KEY[m[1].toLowerCase()]; if (k && !(k in out)) out[k] = +m[2]; }
    if (Object.keys(out).length >= 6) return out;
    return null;
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
    // reject stat-field lines (e.g. "Challenge 21", "AC 17") — not creature names
    if (STAT_FIELD_PREFIXES.some(k => s.toLowerCase().startsWith(k))) return false;
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
  // Resolve a creature name from the 1–2 title lines above the meta line. Layouts
  // that print a family/group header above the name produce "Aboleth Aboleth",
  // "Air Elemental Air Elemental", "Bandits Bandit", "Black Dragons Black Dragon
  // Wyrmling" — collapse those, but still join a genuinely wrapped two-line name.
  function resolveName(titles) {
    titles = titles.map(t => t.trim()).filter(Boolean);
    if (titles.length <= 1) return titles[0] || "";
    const a = titles[0], b = titles[1], al = a.toLowerCase(), bl = b.toLowerCase();
    if (al === bl) return a;                                   // exact doubling
    const aLast = a.split(/\s+/).pop();
    if (/s$/i.test(aLast) && aLast.length > 3) return b;       // plural family header above the name
    if (bl.startsWith(al + " ")) return b;                     // "Azer" + "Azer Sentinel"
    if (al.startsWith(bl + " ")) return a;
    return a + " " + b;                                        // a genuinely wrapped name
  }
  function findName(lines, metaI, lower, titleFonts) {
    lower = lower || 0;
    const titles = [];
    let j = metaI - 1;
    // cap at 2 lines: the creature name sits directly above the meta line; grabbing
    // more pulls in family/running headers ("Monsters A–Z", "Bronze Dragons")
    while (j >= lower && lines[j].trim() && looksLikeTitle(lines[j]) && titles.length < 2) {
      // a wrapped two-line name shares one font; a section heading above the name
      // is set in a DIFFERENT font ("Urban Fauna" over "Cat") — stop at the change
      if (titles.length === 1 && titleFonts && titleFonts[j] && titleFonts[j + 1]
          && titleFonts[j] !== titleFonts[j + 1]) break;
      titles.unshift(lines[j].trim()); j--;
    }
    // title path: titles sit directly above the meta line, so the body starts at meta
    if (titles.length) return { name: resolveName(titles), bodyStart: metaI };
    // fallback: name is further up (e.g. a flavour line or a "Challenge N" line sits
    // between it and the meta line). Include those in-between lines in the body so
    // fields printed above the meta line (some layouts put Challenge there) aren't lost.
    j = metaI - 1; let steps = 0;
    while (j >= lower && steps < 30) { const s = lines[j].trim(); if (s && nameLike(s)) return { name: s, bodyStart: j + 1 }; j--; steps++; }
    return { name: "", bodyStart: metaI };
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
    else { const a2 = RE_ATTACK_2024.exec(body); if (a2) action.attack = { kind: a2[1].toLowerCase() + "_weapon", to_hit: +a2[2], reach_ft: a2[3] ? +a2[3] : null, range_ft: a2[4] || null, targets: "one target" }; }
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

  // A line that belongs to a stat block (a field, a section header, the ability
  // row, or anything carrying combat mechanics). Used to tell stat-block content
  // apart from the lore/rules prose some books pack between creatures.
  function isStatLine(s) {
    s = (s || "").trim(); if (!s) return false;
    if (RE_AC_LINE.test(s) || RE_SECTION_LINE.test(s)) return true;
    const low = s.toLowerCase().replace(/^[•▪◦·*\-\s]+/, "");
    if (STAT_FIELD_PREFIXES.some(p => low.startsWith(p))) return true;
    const up = s.toUpperCase();
    if ((up.match(/\b(STR|DEX|CON|INT|WIS|CHA)\b/g) || []).length >= 3) return true;   // ability header
    if ((s.match(/\d+\s*\(\s*[+\-−]?\d+\s*\)/g) || []).length >= 3) return true;        // "12 (+1) 15 (+2) ..."
    if (RE_ATTACK.test(s) || RE_ATTACK_2024.test(s) || RE_SAVE.test(s)) return true;
    if (/\bHit:?\s/i.test(s) || /\d+d\d+/.test(s) || /recharge/i.test(s)) return true;
    if (/^[•▪◦·*\-\s]*Multiattack\b/i.test(s)) return true;
    if (RE_CHALLENGE.test(s) || RE_PROF.test(s)) return true;
    return false;
  }
  // Trim trailing lore/rules prose that gets swept into a block when stat blocks
  // are packed between pages of flavour (e.g. Fateforge's bestiary). Cut at the
  // start of the first long run of non-stat-block lines after the Armor Class.
  const FLAVOR_RUN = 16;
  function trimFlavor(lines) {
    const ac = lines.findIndex(l => RE_AC_LINE.test(l));
    if (ac < 0) return lines;
    // Splice out long runs of non-stat-block lines (lore/rules prose) wherever
    // they appear — at the end of the block OR sandwiched between the traits and
    // the actions (a two-column NPC whose halves were stitched together). Keep
    // the real stat content on both sides; short runs (entry descriptions) stay.
    const out = lines.slice(0, ac);
    let run = [];
    const flush = () => { if (run.length) { if (run.filter(l => l.trim()).length < FLAVOR_RUN) out.push(...run); run = []; } };
    for (let i = ac; i < lines.length; i++) {
      if (lines[i].trim() && isStatLine(lines[i])) { flush(); out.push(lines[i]); }
      else run.push(lines[i]);
    }
    flush();
    return out;
  }

  // ============================================================ split into blocks
  function splitIntoBlocks(pageText, fonts, titleFonts) {
    const lines = pageText.split("\n");
    if (fonts && fonts.length !== lines.length) fonts = null;
    if (titleFonts && titleFonts.length !== lines.length) titleFonts = null;
    const acIdxs = []; lines.forEach((ln, i) => { if (RE_AC_LINE.test(ln)) acIdxs.push(i); });
    if (!acIdxs.length) return [];
    const specs = acIdxs.map(ac => { let mi = ac - 1; while (mi >= 0 && !lines[mi].trim()) mi--; return [mi, ac]; });
    const blocks = [];
    for (let k = 0; k < specs.length; k++) {
      const [metaI, ac] = specs[k];
      const lower = k > 0 ? specs[k - 1][1] + 1 : 0;
      const nm = findName(lines, metaI, lower, titleFonts);
      const name = nm.name || "Unknown Creature";
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
      } else rest = trimFlavor(lines.slice(nm.bodyStart, hardEnd)).join("\n");
      const body = stripFooter((name + "\n" + rest).trim());
      if (body) blocks.push(body);
    }
    return blocks;
  }

  // ===================================================================== parseText
  // PDF text artifacts. Print layouts hyphenate words across line breaks
  // ("sav-\ning throws"); when lines are joined for display that surfaces as
  // "sav- ing". Rejoin them here, before any parsing. Also map ligature glyphs
  // (ﬁ ﬂ …) to plain letters and strip soft hyphens.
  const LIGATURES = { "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st" };
  // true prefix compounds keep their hyphen when rejoined: "half-\norc" -> "half-orc"
  const KEEP_HYPHEN = new Set(["self", "off", "non", "half", "well", "ill", "quasi", "semi", "pseudo", "demi", "anti", "multi"]);
  function cleanExtractedText(text) {
    text = String(text).replace(/[ﬁﬂﬀﬃﬄﬅﬆ]/g, c => LIGATURES[c] || c).replace(/\u00AD/g, "");
    // a word fragment + hyphen at a line end, continued by a lowercase fragment:
    // merge across the break ("sav-\ning" -> "saving"). Uppercase continuations
    // are left alone — they're headings/names, not split words.
    text = text.replace(/([A-Za-z]+)-\n([a-z][A-Za-z]*)/g, (m, a, b) =>
      KEEP_HYPHEN.has(a.toLowerCase()) ? a + "-" + b : a + b);
    // hyphen + SPACE mid-line ("30-foot- radius", "pre- defined"): the source
    // text broke a compound after its hyphen — rejoin keeping the hyphen, but
    // leave suspended hyphens alone ("one- or two-handed").
    return text.replace(/([A-Za-z])- (?!(?:and|or|nor|to)\b)([a-z][A-Za-z]*)/g, "$1-$2");
  }

  function parseText(text, sourcePage, source) {
    text = cleanExtractedText(text);
    let lines = text.split(/\r?\n/).map(l => l.replace(/\s+$/, "")).filter(l => l.trim());
    lines = trimFlavor(lines);          // drop trailing lore/rules prose (any assembly path)
    text = lines.join("\n");            // so the regexes + raw_text use the trimmed body
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
    for (const ln of lines.slice(1, 7)) {
      const t = ln.trim();
      let m = RE_META.exec(t);
      if (m) { sb.size = SIZES[m[1].toLowerCase()] || null; sb.creature_type = titleCase(m[2]); sb.alignment = m[3].trim(); break; }
      const lm = RE_META_LOOSE.exec(t);
      if (lm) { sb.creature_type = titleCase(lm[1]); sb.alignment = lm[2].trim(); break; }
      // size + type with no alignment, e.g. "Large Celestial" (Free5e layout)
      const sm = RE_META_SIZETYPE.exec(t);
      if (sm) { sb.size = SIZES[sm[1].toLowerCase()] || null; sb.creature_type = titleCase(sm[2]); break; }
    }
    // compact layout: the name line itself carries the size/type (alignment may
    // wrap to the next line), e.g. "Kyanos B'lot Large Aberration (Shapechanger), Chaotic"
    if (!sb.creature_type) {
      const nmeta = RE_NAME_META.exec(sb.name);
      if (nmeta && SIZES[nmeta[2].toLowerCase()]) {
        sb.name = nmeta[1].trim();
        sb.size = SIZES[nmeta[2].toLowerCase()] || null;
        sb.creature_type = titleCase(nmeta[3]);
        let align = (nmeta[4] || "").trim();
        const nxt = (lines[1] || "").trim();   // alignment often wraps: "...Chaotic" / "Neutral"
        if (/^(Lawful|Chaotic|Neutral|Any)$/i.test(align) && /^(Good|Evil|Neutral)$/i.test(nxt)) align += " " + nxt;
        if (align) sb.alignment = align;
      }
    }
    // strip a single-word family-header prefix written as "FAMILY - Name"
    // (e.g. "BUGBEAR - BUGBEAR ASCETIC" -> "BUGBEAR ASCETIC", "LYCANTHROPE - WEREBAT" -> "WEREBAT")
    sb.name = sb.name.replace(/^[A-Za-z][\w'’]*\s+[-–—]\s+(?=[A-Za-z])/, "");
    // strip a running-header prefix glued to the name, e.g.
    // "Z-Coin | Crystalline Dragons | Agate Adult Agate Dragon"
    if (sb.name.includes(" | ")) sb.name = sb.name.replace(/^.*\s\|\s/, "").trim();
    // drop a leading family word that repeats later ("Agate Adult Agate Dragon" -> "Adult Agate Dragon")
    { const w = sb.name.split(/\s+/);
      if (w.length > 2 && w.slice(1).some(x => x.toLowerCase() === w[0].toLowerCase())) sb.name = w.slice(1).join(" "); }
    let m;
    let acF = false, hpF = false, spdF = false, abF = false, crF = false;
    if ((m = RE_AC.exec(text))) { sb.armor_class = +m[1]; sb.armor_desc = (m[2] || "").replace(/^[()\s]+|[()\s]+$/g, "") || null; found++; acF = true; }
    if ((m = RE_HP.exec(text))) { sb.hit_points = +m[1]; sb.hit_dice = (m[2] || "").trim() || null; found++; hpF = true; }
    if ((m = RE_SPEED.exec(text))) { sb.speed = parseSpeed(m[1]); found++; spdF = true; }
    const ab = parseAbilities(text); if (ab) { sb.abilities = ab; found++; abF = true; }
    if ((m = RE_CHALLENGE.exec(text))) { sb.challenge_rating = m[1]; const xp = m[2] || m[3]; if (xp) sb.xp = +xp.replace(/,/g, ""); found++; crF = true; }
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

    // Some books (e.g. Fey Dragons) omit the "Actions" header, so attacks land in
    // the traits bucket. If there are no actions, split the traits at the first
    // action-like entry (Multiattack / an attack roll) and move the rest across.
    if (!sb.actions.length && sb.traits.length > 1) {
      const isAct = (e) => /^multiattack\b/i.test(e.name) || e.attack
        || RE_ATTACK.test(e.raw_text || "") || RE_ATTACK_2024.test(e.raw_text || "");
      const idx = sb.traits.findIndex(isAct);
      if (idx >= 0) { sb.actions = sb.traits.slice(idx).map(e => (e.category = "action", e)); sb.traits = sb.traits.slice(0, idx); }
    }

    // ---- quality scoring: weighted confidence + human-readable warnings ----
    // Unlike a raw field count, this catches the failure modes that matter:
    // a block missing its actions, or with ability scores that never parsed.
    const warns = [];
    const hasName = sb.name && sb.name !== "Unknown Creature" && sb.name.trim().length > 1;
    const bodyCount = sb.actions.length + sb.traits.length + sb.reactions.length
                    + sb.bonus_actions.length + sb.legendary_actions.length;
    if (!hasName) warns.push("No name parsed");
    if (!acF)     warns.push("No armor class");
    if (!hpF)     warns.push("No hit points");
    if (!abF)     warns.push("Ability scores look unparsed");
    if (!crF)     warns.push("No challenge rating");
    if (!bodyCount) warns.push("No actions or traits");
    const score = (hasName ? 0.12 : 0) + (acF ? 0.15 : 0) + (hpF ? 0.15 : 0)
                + (abF ? 0.20 : 0) + (crF ? 0.10 : 0) + (spdF ? 0.08 : 0)
                + (bodyCount ? 0.20 : 0);
    sb.parse_confidence = Math.round(score * 100) / 100;
    sb.parse_warnings = warns;
    return sb;
  }

  // ============================================================= page chrome strip
  const SIZE_WORDS = new Set(["tiny", "small", "medium", "large", "huge", "gargantuan"]);
  // Never strip stat-block field lines as "page furniture" — identical field
  // lines legitimately repeat across creatures (every CR-2 monster prints the
  // same "CR 2 (XP 450; PB +2)"), so they must be protected from the chrome strip.
  const CHROME_PROTECT = ["armor class", "hit points", "speed", "saving throws", "skills", "senses", "languages", "challenge", "damage ", "condition ", "proficiency",
    "ac ", "hp ", "cr ", "initiative", "immunities", "resistances", "vulnerabilities", "gear "];
  function isStructuralLine(s) {
    if (RE_SECTION_LINE.test(s)) return true;
    const toks = s.toUpperCase().split(/\s+/);
    if (toks.filter(t => ["STR", "DEX", "CON", "INT", "WIS", "CHA"].includes(t)).length >= 3) return true;
    // de-bullet before matching: Fateforge prints fields as "• Armor Class 12",
    // and identical short field lines repeat across its many small creatures —
    // without this they get classified as page chrome and stripped (losing the
    // AC anchor, and with it the whole stat block)
    const low = s.toLowerCase().replace(/^[•▪◦·*\-\s]+/, "");
    const w0 = low.split(/\s+/)[0];
    if (SIZE_WORDS.has(w0)) return true;
    return CHROME_PROTECT.some(p => low.startsWith(p));
  }
  const RE_FURNITURE = /^(?:[A-Za-z]|\d{1,4}|[A-Za-z]\s+\d{1,4}|\d{1,4}\s+[A-Za-z])$/;
  const isFurniture = (s) => RE_FURNITURE.test(s.trim());
  function stripPageChrome(linePages) {
    const n = linePages.length;
    if (n < 4) return linePages;
    // Count repeats per (text, font) pair, not text alone: real running
    // headers/footers repeat in ONE font, while a creature's name legitimately
    // recurs across the book in DIFFERENT fonts (contents list, stat-block
    // title, lore heading, index) — Nerzugal's bestiary hit the threshold that
    // way and lost real names to the chrome filter.
    const key = (t, f) => t + "\u0000" + (f || "");
    const freq = {};
    for (const page of linePages) {
      const seen = new Set();
      for (const [t, f] of page) { const s = t.trim(); if (s) seen.add(key(s, f)); }
      for (const k of seen) freq[k] = (freq[k] || 0) + 1;
    }
    const threshold = Math.max(5, Math.floor(0.03 * n));
    const chrome = new Set();
    for (const k in freq) {
      const s = k.slice(0, k.indexOf("\u0000"));
      if (freq[k] >= threshold && s.length <= 30 && !".!?".includes(s[s.length - 1]) && !isStructuralLine(s)) chrome.add(k);
    }
    return linePages.map(page => page.filter(([t, f]) => { const s = t.trim(); return !chrome.has(key(s, f)) && !isFurniture(s); }));
  }

  // ============================================================ blocks from pages
  const RE_AC_PLAIN = /^\s*[•▪◦·*\-]?\s*(?:Armor Class|AC):?\s+\d/i;
  // NOTE: unlike the desktop parser, we do NOT font-filter blocks. pdf.js gives
  // much coarser font info than pdfplumber (it doesn't cluster a stat block's
  // body into one font), so a majority-font filter wrongly discards the ability
  // row and the whole actions section. The two-column split already isolates
  // each stat block from its lore, so a font-less split is both simpler and far
  // more reliable in the browser (ToB3: 12/406 with actions -> 405/406).
  const pageAllText = (page) => page.map(([t]) => t).join("\n");
  function preAcTextLines(lines) { const kept = []; for (const t of lines) { if (RE_AC_PLAIN.test(t)) break; kept.push(t); } return kept.join("\n"); }

  // A creature name stranded at the bottom of a column (its stat block starts in
  // the NEXT column). Detect a trailing title line with no AC after it so we can
  // carry it forward instead of losing the name / polluting the previous block.
  function orphanStart(lines) {
    // Scan the last few lines for a creature name that has no Armor Class after it
    // in this column (its stat block starts in the next column). The lead-in may
    // include flavour and a "Challenge N" line (Free5e prints it before the block),
    // so don't stop at stat-field lines — only stop at an actual stat block (AC).
    let found = -1;
    for (let i = lines.length - 1; i >= 0 && i >= lines.length - 6; i--) {
      const s = (lines[i] || "").trim();
      if (!s) continue;
      if (RE_AC_LINE.test(s)) break;
      if (looksLikeTitle(s)) found = i;
    }
    return found;
  }
  const allTen = (ab) => ab.strength === 10 && ab.dexterity === 10 && ab.constitution === 10 && ab.intelligence === 10 && ab.wisdom === 10 && ab.charisma === 10;
  // a "block" with no name, no real AC, no real abilities and no real HP is a false
  // anchor (e.g. an "AC" mentioned in rules prose), not a creature — drop it
  const isFalseAnchor = (sb) => (!sb.name || sb.name === "Unknown Creature") && sb.armor_class === 10 && sb.hit_points === 1 && allTen(sb.abilities);

  function blocksFromPages(linePages, source) {
    linePages = stripPageChrome(linePages);
    const results = [];
    let pending = null, carry = [];
    const push = (sb) => { if (sb && !isFalseAnchor(sb)) results.push(sb); };
    const flush = () => { if (pending !== null) { try { push(parseText(pending.body, pending.page, source)); } catch (e) {} pending = null; } };
    let carryF = [];
    for (let i = 0; i < linePages.length; i++) {
      let lines = carry.concat(linePages[i].map(([t]) => t));
      let lfonts = carryF.concat(linePages[i].map(([, f]) => f || ""));
      carry = []; carryF = [];
      // peel a stranded trailing name off this column to prepend to the next one
      const oi = orphanStart(lines);
      if (oi >= 0) { carry = lines.slice(oi); carryF = lfonts.slice(oi); lines = lines.slice(0, oi); lfonts = lfonts.slice(0, oi); }
      const pageText = lines.join("\n");
      const blocks = splitIntoBlocks(pageText, null, lfonts);   // body stays font-less; fonts only inform the title scan
      if (!blocks.length) {
        if (pending !== null && pageText.trim()) pending.body += "\n" + pageText;
        continue;
      }
      if (pending !== null) { const pre = preAcTextLines(lines); if (pre.trim()) pending.body += "\n" + pre; flush(); }
      for (let j = 0; j < blocks.length; j++) {
        const isLast = j === blocks.length - 1;
        if (isLast && !hasActionsSection(blocks[j])) pending = { body: blocks[j], page: i + 1 };
        else { try { push(parseText(blocks[j], i + 1, source)); } catch (e) {} }
      }
    }
    flush();
    return results;
  }

  // ================================================================ public: import
  // a stat block's identity for de-duplication: same name + AC + HP + CR means
  // it is the same creature, so re-importing a PDF won't add it twice
  const fingerprint = (b) => `${(b.name || "").trim().toLowerCase()}|${b.armor_class}|${b.hit_points}|${b.challenge_rating}`;

  // parse + insert ONE file, skipping any block already in the compendium.
  // Returns a summary; never touches the shared progress UI itself.
  async function importOneFile(file, onProgress) {
    if (!/\.pdf$/i.test(file.name)) return { ok: false, name: file.name, error: "Not a PDF file." };
    let buf;
    try { buf = await file.arrayBuffer(); } catch (e) { return { ok: false, name: file.name, error: "Couldn't read the file." }; }
    let pages;
    try { pages = await extractColumnLinePages(buf, onProgress); }
    catch (e) { return { ok: false, name: file.name, error: "Couldn't parse the PDF." }; }
    const totalChars = pages.reduce((a, pg) => a + pg.reduce((b, [t]) => b + t.length, 0), 0);
    if (!pages.length || totalChars < 40 * pages.length)
      return { ok: false, name: file.name, error: "No text layer found. This looks like a scanned or image-only PDF, which MonsterBox can't read." };
    let blocks;
    try { blocks = blocksFromPages(pages, file.name); } catch (e) { return { ok: false, name: file.name, error: "Parse error." }; }
    // de-dupe against what's already stored (re-fetched per file so a duplicate
    // shared across several dropped PDFs is caught too)
    let existing = [];
    try { existing = await (await fetch("/api/statblocks")).json(); } catch (e) {}
    const seen = new Set((existing || []).map(fingerprint));
    let added = 0, dup = 0, flagged = 0;
    for (const sb of blocks) {
      const f = fingerprint(sb);
      if (seen.has(f)) { dup++; continue; }
      seen.add(f);
      sb.id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "sb-" + Date.now() + "-" + added;
      try {
        await fetch("/api/statblocks/" + sb.id, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sb) });
        added++; if (sb.parse_confidence < 0.85) flagged++;
      } catch (e) {}
    }
    return { ok: true, name: file.name, parsed: blocks.length, added, dup, flagged };
  }

  // import one OR MANY PDFs in sequence, with shared progress + a combined result
  async function sfImportPdfs(files) {
    const prog = document.getElementById("importprogress");
    const empty = document.getElementById("emptylabel");
    const showProg = (html) => { if (prog) { prog.innerHTML = html || ""; prog.classList.toggle("show", !!html); } };
    let emptyWasShown = false;
    const hideEmpty = () => { if (empty && getComputedStyle(empty).display !== "none") { emptyWasShown = true; empty.style.display = "none"; } };
    const showEmpty = () => { if (empty && emptyWasShown) { empty.style.display = "flex"; emptyWasShown = false;
      if (empty.animate) try { empty.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 450, easing: "ease" }); } catch (e) {} } };

    const list = Array.from(files || []).filter(Boolean);
    if (!list.length) return;
    if (!window.pdfjsLib) { hideEmpty(); showProg("PDF engine failed to load."); setTimeout(() => { showProg(""); showEmpty(); }, 4000); return; }
    const pdfs = list.filter(f => /\.pdf$/i.test(f.name));
    if (!pdfs.length) { hideEmpty(); showProg("Please choose PDF files."); setTimeout(() => { showProg(""); showEmpty(); }, 4000); return; }

    hideEmpty();
    let totAdded = 0, totDup = 0, totFlagged = 0; const errors = [];
    for (let i = 0; i < pdfs.length; i++) {
      const file = pdfs[i];
      const head = (pdfs.length > 1 ? "Importing " + (i + 1) + " of " + pdfs.length + ": " : "Importing ") + escapeHtml(file.name);
      showProg(head + "…");
      const res = await importOneFile(file, (cur, total) => {
        const pct = total ? Math.round((100 * cur) / total) : 0;
        showProg(head + "<br>" + cur + "/" + total + " pages complete" +
          '<div class="pbar"><div style="width:' + pct + '%"></div></div>');
      });
      if (!res.ok) { errors.push(escapeHtml(res.name) + ": " + escapeHtml(res.error)); continue; }
      totAdded += res.added; totDup += res.dup; totFlagged += res.flagged;
    }
    if (typeof window.loadLibrary === "function") window.loadLibrary();

    // combined result message
    const dupNote = totDup ? " " + totDup + " already in your compendium." : "";
    let result;
    if (totAdded > 0) {
      const from = pdfs.length > 1 ? " from " + pdfs.length + " PDFs" : "";
      const review = totFlagged ? totFlagged + (totFlagged === 1 ? " needs" : " need") + " review." : "All parsed cleanly.";
      result = "<b>Imported " + totAdded + " " + (totAdded === 1 ? "monster" : "monsters") + from + ":</b><br><i>" + review + dupNote + "</i>";
    } else if (totDup > 0) {
      result = "<b>These monsters have already been imported.</b>";
    } else if (errors.length) {
      result = "<b>Import failed:</b><br><i>" + errors.join("<br>") + "</i>";
    } else {
      result = "<b>No stat blocks found in " + (pdfs.length > 1 ? "these PDFs." : "this PDF.") + "</b>";
    }
    if (errors.length && totAdded > 0) result += "<br><i>" + errors.join("<br>") + "</i>";
    showProg(result);
    setTimeout(() => { showProg(""); showEmpty(); }, 4500);
  }
  function escapeHtml(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

  // single-file entry point kept for compatibility (delegates to the batch path)
  window.sfImportPdf = (file) => sfImportPdfs(file ? [file] : []);
  window.sfImportPdfs = sfImportPdfs;
})();
