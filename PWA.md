# StatForge — Web (PWA) build

A fully client-side version of StatForge that runs from a static host (GitHub
Pages) with **no server**. Send a DM a link, they open it, and it works —
including offline, "install to home screen / desktop," and **importing their own
PDFs**. Everything lives in `docs/`.

## No content ships — this is the anti-piracy model

**No stat blocks are bundled, seeded, or stored anywhere shareable.** The hosted
site is just code. Each DM imports **their own legally-owned PDF**, which is
parsed *on their device* and stored only in *their* browser. Nothing is uploaded
and nothing copyrighted is ever served from the site.

## How it differs from the desktop app

The desktop app is a Flask server (Python). The web build moves everything into
the browser:

| Concern | Desktop | Web (PWA) |
|---|---|---|
| Storage | JSON files on disk | **IndexedDB** in the browser |
| Roll / tracker / conditions | Python engine | JS engine (`engine.js`) |
| PDF import | pdfplumber + parser | **pdf.js + a JS port of the parser** (`pdfimport.js`) |

`docs/engine.js` monkey-patches `fetch()` so the existing UI's `/api/...` calls
are answered locally from IndexedDB — the UI is identical to the desktop one.
`docs/pdfimport.js` is a faithful port of the desktop ingest pipeline
(column-aware extraction → block splitting → regex parse), so an imported PDF
yields the same stat blocks. *(Verified: on a real two-column book it produced
the same 26 stat blocks, with the same names and parsed fields, as the desktop
parser.)*

## Local compendium storage

- Each DM's compendium lives in **their own browser** (IndexedDB) — per-device,
  no accounts, no server.
- It **persists** across sessions and works **fully offline** (service worker).
- **Export / Import JSON** (buttons in the import panel) back up a library or
  move it between a DM's own devices.
- **Caveats:** clearing browser data wipes it, and a browser *can* evict storage
  under pressure (installing the PWA makes it durable; the app also requests
  persistent storage). Export JSON for backups.

## PDF import (in the browser)

Drop a PDF on the import panel (or click *browse*). It's parsed locally with
`pdf.js` and the ported parser; a progress bar shows page-by-page reading. Works
on **digital (text-layer) PDFs**; scanned/image-only PDFs are detected and
politely declined (no OCR / vision model in the browser — use the desktop app
for those).

## Deploy to GitHub Pages

1. Commit and push (the build is in `docs/`).
2. Repo **Settings → Pages → Source: "Deploy from a branch" → Branch: `main`
   / folder: `/docs`** → Save.
3. After a minute it's live at `https://<you>.github.io/<repo>/`. Send that link.

All asset paths are relative and the manifest uses `start_url: "."`, so it works
correctly under the `/<repo>/` sub-path.

### When you update the build

The service worker caches the app shell. Bump `CACHE` in `docs/sw.js` (e.g.
`statforge-v2` → `v3`) whenever you change a cached asset so users get the new
version on next load.

## Test locally

```bash
py -m http.server 8055 --directory docs
# open http://127.0.0.1:8055/
```

(Localhost counts as a secure context, so the service worker / install work. If
you change files during dev and see stale behaviour, clear the site's service
worker + cache in DevTools → Application.)

## Personal backup / migration (optional)

`py tools/export_compendium.py --out compendium.json` bundles **your own**
desktop library into one JSON you can re-import into the web app on another of
your devices. (This is for your own use — don't post copyrighted content to a
public site.)

## Vendored

`docs/vendor/pdf.min.js` + `pdf.worker.min.js` are pdf.js v3 (legacy/UMD build),
vendored so the app works offline with no CDN dependency.
