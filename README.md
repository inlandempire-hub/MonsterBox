# StatForge

Scan a 5e stat block, run the encounter. Point it at a PDF (including a phone
**scan** of a physical or 3rd-party book), get back a structured, *rollable*
stat block you can drop into a live initiative tracker — a DM-side, solo-first
analogue to D&D Beyond + Beyond20.

> Status: **early**. The data model, ingestion boundary (with a **working
> vision-LLM parser**), roll engine, initiative tracker, and owner-scoped
> storage are in place and runnable. The desktop UI is the next milestone.

## Why it's built the way it is

The design was driven by a real input: a 3-page PDF that turned out to be a
**scanned book** — every page a single full-page image with **no text layer**.
Plain text extraction returns nothing. That one fact shaped three decisions:

1. **Image-first ingestion.** The primary parse path sends the page *image* to a
   vision model and asks for the stat block schema directly (most robust on
   dense, two-column scans). OCR→text is the offline fallback.
2. **Fidelity over cleverness.** Every parsed action keeps its original
   `raw_text`, so the sheet can always show the printed wording when structured
   parsing is imperfect.
3. **Relocatable parse boundary.** Everything flows through
   `parse(page, owner_id, source) -> StatBlock`, so parsing can run locally
   today or behind a hosted, per-tenant endpoint later — unchanged.

Two more principles run throughout:

- **Template vs. instance.** A `StatBlock` is the parsed template; a `Combatant`
  is a live instance in an encounter with its own HP/conditions. One goblin
  block → three independent combatants.
- **Owner-scoped from day one.** Every entity carries an `owner_id`
  (`"local-user"` for now). Solo today, multi-tenant-ready without a migration.

## Layout

```
src/statforge/
  models.py            # StatBlock (template), Combatant (instance), RollEvent, Encounter
  ingest/
    render.py          # PDF -> page images (+ detects scanned vs text-layer)
    extract.py         # OCR fallback -> text + quality score
    parser.py          # parse() boundary: VisionLLMParser (primary) | OcrHeuristicParser (fallback)
    pipeline.py        # ingest_pdf(path, owner_id, parser) -> IngestResult
  combat/
    dice.py            # NdM + advantage roller
    roller.py          # Action -> structured RollEvent (every number is a button)
    tracker.py         # InitiativeTracker: spawn templates into instances
  storage/
    repository.py      # owner-scoped local JSON store + JSONL roll log
  cli.py               # ingest / list / show / demo
```

## Quick start

```bash
pip install -e .            # core (pydantic, pypdf)
pip install -e ".[ocr]"     # + OCR fallback (also needs the Tesseract binary)
pip install -e ".[dev]"     # + pytest

# See the whole loop without needing a PDF:
python -m statforge demo

# Ingest a real PDF (scanned PDFs degrade gracefully without OCR/LLM):
python -m statforge ingest path/to/book.pdf
python -m statforge list
python -m statforge show <statblock-id>
```

`demo` parses a sample stat block, spawns two combatants, rolls initiative and
an attack, and prints the structured roll log — the end-to-end skeleton in one
command.

## See it in your browser (the UI)

**Easiest (Windows, no terminal needed):**

1. Double-click **`setup.bat`** once (installs StatForge + loads sample monsters).
2. Double-click **`StatForge.bat`** to launch — it starts the local server
   **invisibly** (no console window) and opens the app (a clean Chrome app-window
   if Chrome is installed, otherwise your default browser). Just **close the app
   window** to stop — the server sends itself a heartbeat while the page is open
   and shuts down automatically a few seconds after you close it.

To make a desktop shortcut: right-click `StatForge.bat` → **Send to → Desktop
(create shortcut)**.

**Manual / other platforms:**

```bash
pip install -e ".[web]"
python -m statforge seed --reset     # load 2 sample monsters
python -m statforge serve            # then open http://127.0.0.1:8000
```

The page has three columns: a **library** of imported monsters, a clickable
**stat sheet** (attacks roll with a click), and an **initiative tracker** plus
a live **roll log**. No API key needed — it runs entirely on your machine.

## Using the vision parser

The primary path needs an Anthropic API key (never committed — read from the
environment, so the project is safe to hand to another DM):

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=sk-ant-...      # Windows: $env:ANTHROPIC_API_KEY="sk-ant-..."
python -m statforge ingest book.pdf --parser vision
```

`--parser auto` (the default) uses vision when a key is present and falls back
to OCR otherwise. It calls `claude-opus-4-8` with adaptive thinking and
structured outputs, returning one or more `StatBlock`s per page.

## Two kinds of PDF, one command

`ingest_pdf` auto-detects the input:

- **Digital PDF** (real e-book, selectable text) → read straight from the text
  layer. No AI, no OCR — fastest and most accurate.
- **Scanned PDF** (phone photo of a physical book) → vision model (with a key)
  or offline OCR fallback.

### Offline OCR fallback

OCR needs the Tesseract program (not just the Python package):

```bash
pip install -e ".[ocr]"
# Windows: winget install UB-Mannheim.TesseractOCR
python -m statforge ingest scan.pdf --parser ocr
```

OCR is best-effort on dense scans; `parse_confidence` flags low-quality reads
so you know when to double-check or rerun with the vision parser.

## Shipping to a friend (planned — not built yet)

Decision: package as a **standalone Windows app via PyInstaller** so a non-technical
user just unzips and double-clicks `StatForge.exe` (no Python, no pip, no internet).
When we build it, handle these:

- Bundle the web static files (`--add-data "src/statforge/web/static;statforge/web/static"`).
- A packaged entry point that runs `serve` and opens the browser, defaulting the
  data dir to a user-writable location (`%LOCALAPPDATA%\StatForge\data`), not next
  to the exe.
- Set the app/exe icon to `StatForge.ico`.
- Note for the recipient: Windows SmartScreen may show a one-time "unrecognized
  app" prompt (unsigned) — choose *More info → Run anyway*.
- The AI-scan API key stays optional; the digital + OCR paths work without it.

(Alternative, smaller but higher-friction: zip the repo + `setup.bat`, which needs
Python installed and internet for the first run.)

## Roadmap

- [x] Wire `VisionLLMParser` to a real client (image → StatBlock JSON).
- [x] Digital-PDF path: read born-digital PDFs from their text layer.
- [x] Offline OCR fallback (Tesseract) for scans with no API key.
- [x] Full trait / action / legendary parsing from text (attacks, saves, recharge, costs).
- [x] Real two-column rulebooks: column-aware reading, multiple monsters per page,
      names taken from the stat block (not the page header), lore pages skipped.
- [x] Robust against book quirks: anchors on the "Armor Class" line (survives size
      typos), multi-line names, full secondary stats (saves/skills/senses/languages/
      immunities), footer/page-number stripping, and headers detected by sentence
      structure (no more wrapped lore mistaken for actions).
- [x] Edit a stat block in-app (fix any field, edit/delete trait & action entries).
- [x] Roll saving throws, ability checks, and skill checks from the sheet.
- [x] Font-aware block bounding: keep only the stat-block-font lines, dropping lore,
      encounter sidebars, and art credits that the page interleaves into a block.
- [x] Spellcasting over-split fixed: feature headers must be title-cased noun
      phrases, so a sentence fragment ("Its spellcasting ability is Wisdom") is
      no longer mistaken for a feature.
- [x] Conditions on combatants (toggle chips), player characters in initiative,
      and save / reload / delete named encounters (conditions + PCs persist).
- [x] Name detection for official layouts (name header sits above the flavor
      text, not inside the stat box); reject structural lines as names.
- [x] Resilient import: a bad block can't abort a whole book; damage bonuses that
      wrap across lines parse correctly.
- [x] Validated on a full clean book (Tome of Beasts 3, 426 pp → 406 stat blocks,
      0 unknown names, 64s, 0 entries with no traits+actions). Five new bug
      classes found and fixed: Unicode-minus ability mods (−), section headers
      in a decorative font dropped by the font filter, word order scrambled by
      italic baseline jitter, three multi-page / mis-typeset patterns (stat
      blocks truncated at page breaks, stitched via pending-block continuation;
      entry names with a space before their period, "Bite ."; AC lines in the
      wrong font poisoning the body-font filter), and running headers/footers in
      the title font (book title + thumb-index letter + page number) swallowed
      into the monster name — now removed by a cross-page "page chrome" stripper
      that protects structural lines (section headers, ability row, stat fields,
      the size/type/alignment meta line). Re-validated name-for-name against the
      book's by-Challenge appendix: 406 = 406, 0 missing, 0 duplicates.
- [ ] **Column-layout detection — top priority for official books.** Full-width
      stat blocks (big creatures, much of the MM) get scrambled by the fixed
      midpoint column split (jumbled ability rows, names unfindable → "Unknown").
      Detect single- vs two-column per page/region and read accordingly. Validate
      on a *clean* MM PDF — a corrupted/pirated copy's text garbling muddies it.
- [ ] Rare stragglers on heavily mixed-layout pages — a two-click fix via Edit.
- [x] Light D&D-Beyond-style theme (neutral grays + crimson, framed cards,
      character-sheet styling); library sorted by challenge rating.
- [x] Live import progress bar (background job + "page X / Y" polling).
- [x] Library grouped into collapsible CR sections (expand the CR you're building for).
- [ ] Faster big-book import (optional — the progress bar makes the wait visible;
      speed-ups like skipping non-stat-block pages can come if needed).
- [x] In-app drag-and-drop PDF import.
- [ ] Faster big-book import (pdfplumber is slow on some PDFs; ~100s for a full book).
- [ ] Desktop / web UI: the rollable sheet + initiative tracker.
- [ ] Phone ingestion (manual drop now → local Wi-Fi upload later).
- [ ] Optional VTT export (design toward Foundry; Roll20 has no clean API).
```
