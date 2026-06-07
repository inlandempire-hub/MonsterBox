# StatForge

A DM-side, solo-first tool for **5e-compatible** stat blocks: point it at a
stat-block PDF **you own**, get back a structured, *rollable* stat block, and
run the encounter in a built-in initiative tracker.

StatForge ships **empty** and stores everything **locally on your device**. It's
a tool for working with content you are legally entitled to use — it bundles no
monsters, no books, and no stat blocks of its own.

## Two faces, one build

The web app and the local app are the **same** client-side build (in `docs/`):

- **On the web** — a Progressive Web App hosted on GitHub Pages. Open the link,
  optionally "Install" it from your browser, and it works offline.
- **On your desktop** — double-click **`StatForge.bat`** (Windows). It serves the
  same build locally and opens it in a clean app window. The desktop shortcut
  points here. *(Requires Python, for a tiny local static file server.)*

Either way, your compendium lives in that browser's local storage (IndexedDB) —
nothing is uploaded, synced, or shared.

## What it does

- **Import a PDF you own.** Parsing happens entirely **on your device** — the
  file never leaves your machine. Works on digital (text-layer) PDFs; scanned /
  image-only PDFs are detected and declined (no OCR or vision model in the
  browser).
- **Get rollable stat blocks.** Every number — attacks, saves, ability checks,
  initiative — is a button that rolls and logs the result.
- **Run encounters.** Initiative tracker with HP, conditions (full 5e condition
  set with mechanical effects), exhaustion, and a player-vs-monster HP view.
- **Search your library.** Filter the whole compendium by CR and type.
- **Back up and move it.** *Export / Import Compendium* writes a single JSON file
  you can keep as a backup or carry to another device.

## Your content, your responsibility

StatForge is intended for stat-block PDFs you are **legally entitled to use**.
You are solely responsible for the legality of the content you import and store.
The app's *About & legal* panel (shown on first run, and reopenable from the
import panel) restates this alongside the points below.

## Privacy

Everything is local. Your library is stored only in your browser; nothing is
uploaded or shared. Export the compendium JSON periodically to keep a backup —
clearing browser data will otherwise remove it.

## Trademarks

StatForge is an independent, **5e-compatible** tool. It is **not affiliated with,
endorsed by, or sponsored by Wizards of the Coast**. Any reference to the game
system is nominative, to describe compatibility only.

## AI disclosure

StatForge's **code** is AI-assisted. It contains **zero AI-generated art or
content**, and that will never change.

## Layout

```
docs/                    # the app — web + local are this one build
  index.html             # UI
  engine.js              # client-side store (IndexedDB) + roll/tracker engine + fetch shim
  pdfimport.js           # in-browser PDF parser (pdf.js port of the ingest pipeline)
  sw.js                  # service worker (offline app shell)
  manifest.webmanifest   # PWA install metadata
StatForge.bat            # local launcher (serves docs/ and opens an app window)
ROADMAP.md               # prioritised roadmap
PWA.md                   # web-build / deploy notes
src/statforge/           # legacy Python/Flask desktop build (superseded by the PWA)
```

> The `src/` Flask app is the original desktop implementation; the project has
> since **converged on the client-side PWA** as the single build for both web and
> desktop. `src/` is retained for reference and may be retired.

## Deploy / develop

See **`PWA.md`** for serving the build locally and deploying to GitHub Pages.

---

*The legal notes above are an organisational summary, not legal advice. See
`ROADMAP.md` (P5) for the pre-monetisation legal checklist.*
