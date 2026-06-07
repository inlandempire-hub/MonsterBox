# StatForge — Master Roadmap

*Synthesised from three planning docs (Legal & Compliance, Feature Spec, Free Content
Sources) into one priority order, plus added notes for things those docs overlooked.
Last updated: 2026-06-07.*

---

## The one-line strategy

**The PDF parser is the business.** No competitor ingests whole books at scale
(CombatFlow parses pasted text; The DM's Toolbox has no import; D&D Beyond only ingests
its own purchases). Everything below protects that wedge first and adds polish second.
Breadth (journals, generators, character builders) is **declined** — it competes on
commodity ground and dilutes the one thing we do that nobody else does.

Three workstreams run through this roadmap, and they are deliberately interleaved rather
than listed separately:

- **🛡 Legal** — due-diligence to keep the anti-piracy / copyright posture defensible.
- **⚙ Parser** — hardening the moat (needs the free test content to make progress).
- **✦ Feature** — table-stakes combat polish, then the headline differentiator.

---

## Current state (what's already built — don't re-spec)

| Area | Status |
|---|---|
| Empty-ship architecture, local-only IndexedDB storage, no server content | ✅ Done — the foundation of the whole legal posture |
| In-browser PDF parse (pdf.js + ported parser), ~400 ToB3 blocks | ✅ Done |
| 16-condition framework with mechanical effects, exhaustion table | ✅ Done (but **no auto-decrement**, see 2.2) |
| Concentration *as a condition* | 🟡 Exists as a tag; **no auto-check-on-damage prompt** (see 2.1) |
| Initiative roller, PC/monster HP bars (green/red) | ✅ Done |
| Encounter planner + runner, save/load encounters | ✅ Done (covers Feature-Spec 3.3 — *presets largely complete*) |
| Compendium search + CR/Type filters, collapsible CR groups | 🟡 Partial — covers some of 3.1; no free-text on traits/actions, no environment/source facets |
| Roll log, mobile UI with slide-out drawers | ✅ Done |
| Live PWA on GitHub Pages | ✅ Done — **already shared with DMs** (this is why P0 legal items are urgent) |

---

## MASTER PRIORITY SEQUENCE

Read top-to-bottom. Tags: 🛡 Legal · ⚙ Parser · ✦ Feature · 🧪 Testing · 🆕 my added note.
Effort: **S** <1wk · **M** 1–3wk · **L** 1mo+.

### ▸ P0 — Do now (you're already distributing the link) — ✅ COMPLETE (2026-06-07)

These were cheap, mostly non-code, and **live exposure** because the PWA was already in DMs'
hands without any disclaimer or use notice. All five are now shipped (plus the local app was
converged onto the PWA build — `StatForge.bat` and the desktop shortcut now launch the PWA).

| # | Item | Tag | Effort | Status |
|---|---|---|---|---|
| 1 | **WotC trademark disclaimer + "5e-compatible" framing.** | 🛡 | S | ✅ In the About & legal panel + README. |
| 2 | **First-run acceptable-use notice.** One-time dialog (+ a copy in About): intended for content you're legally entitled to use; you're solely responsible for legality. | 🛡 | S | ✅ First-run About modal (`sf-ack` flag), reopenable from the import panel. |
| 3 | **Marketing-copy audit.** All framing "import stat blocks from PDFs you own" — never name commercial books, never imply bypassing payment. | 🛡 | S | ✅ README rewritten; removed old "D&D Beyond"/"3rd-party book scan"/vision-LLM framing. The Pages copy *is* this build (About panel). |
| 4 | **AI-disclosure line.** | 🛡 | S | ✅ Locked (see resolved decisions) — in About panel + README. |
| 5 | 🆕 **Persistent storage + backup reminder.** | 🆕✦ | S | ✅ `navigator.storage.persist()` on boot; on-device backup reminder banner appears when the library is non-empty and not exported in 14 days (snooze / Export inline; cleared on export). |

### ▸ P1 — Harden the moat (Feature-Spec Tier 0, powered by the test content)

This is the core of the next stretch. Parser hardening and the free-content test corpus are
**the same project** — you can't harden what you can't measure. Run the testing workflow as
the engine that drives 0.1–0.3.

| # | Item | Tag | Effort |
|---|---|---|---|
| 6 | **Build the regression corpus — ground-truth pass.** Parse **SRD 5.1** then **SRD 5.2** (CC-BY-4.0; two official layouts, and 5.2 deliberately omits Beholder/Strahd/Orcus/Tiamat — that's expected, *not* a bug). Diff every field against the clean web references (5thsrd.org, a5esrd.com). Commit the **expected JSON**, not the PDFs (see note 🆕-A). | 🧪⚙ | M |
| 7 | **Layout-robustness pass.** Parse community-reformatted SRDs (itch.io bookmarked/bilingual editions) and **Free5e** manuscripts (Wyrmworks, DriveThruRPG). Same data, different structure → any new failures are *layout* bugs, isolated from data bugs. | 🧪⚙ | M |
| 8 | **Wild pass.** Parse **Khyberia SRD** (CC-BY) and assorted free/PWYW third-party monster packs (itch.io / Gumroad / DriveThruRPG). Surfaces the real-world formatting chaos future users will throw at it. | 🧪⚙ | M |
| 9 | **0.2 Graceful-failure + manual-correction path.** When a field won't parse, flag it for one-click fix instead of dropping it or rejecting the whole import. This is what makes a 400-block bulk import *trustworthy* — scan flags, don't re-check everything. | ✦⚙ | M |
| 10 | **0.3 Per-block parse-confidence indicator.** Green/amber/red per imported block so the user knows which ~2% to eyeball. Cheap on top of #9, outsized trust payoff. | ✦⚙ | S |
| 11 | 🆕 **Unify the two parsers' test surface.** There are now **two parsers** (Python desktop + JS PWA) that can silently drift. Run the corpus (#6–8) against **both** so a fix in one doesn't regress the other. Long-term, consider a single source of truth. | 🆕⚙ | M |
| 12 | **Volume pass (private only).** Run the **Sly Flourish Artisanal Monster DB** (2,400+ blocks) for performance/robustness at scale. **CC-BY-NC → private testing only; never bundle or ship it.** | 🧪 | S |

### ▸ P2 — Combat table-stakes (Feature-Spec Tier 1)

Without these the superior import is wrapped in a tracker that feels *less* finished than free
alternatives during the moment that matters most — live combat.

| # | Item | Tag | Effort |
|---|---|---|---|
| 13 | **1.1 Auto concentration-check prompts.** On damage to a concentrating creature, auto-calc DC (max(10, ½ damage)) and prompt. Concentration already exists as a condition — this wires the trigger. Small build, high perceived polish. | ✦ | S |
| 14 | **1.3 Death-save workflow.** Track successes/failures for downed PCs/creatures, with stabilise/revive states. Well-understood, contained. | ✦ | S |
| 15 | **1.5 Damage/healing history with undo.** Per-combatant log so a misclick in a tense round is recoverable. Removes a common in-play frustration. | ✦ | S |
| 16 | **1.2 Auto-decrementing conditions.** Conditions that count down each round and clear themselves. Build on the existing condition framework. Complexity is in edge cases (start- vs end-of-turn expiry, save-tied conditions) — budget for fiddliness. | ✦ | M |
| 17 | **1.4 Smart auto-grouping of identical monsters.** Collapse "Goblin 1–8" into an expandable initiative group. Pairs directly with the parser's strength (big imports are what make grouping necessary). Complexity: keep individual HP/conditions correct under a grouped view. | ✦ | M |

> **Milestone A — "Credibly shippable":** P0 + P1 + P2 complete. Parser bulletproofed, tracker no longer feels less finished than free competitors.

### ▸ P3 — The headline differentiator + library showcase (Tiers 2.1 & 3.1)

| # | Item | Tag | Effort |
|---|---|---|---|
| 18 | **2.1 Second-screen / player view.** Cast-able player-facing view (initiative order, names, visible status, bloodied <50% HP) while the DM keeps stat blocks private. The feature most likely to make someone *switch* to StatForge — treat it as the launch headline. High effort/complexity (multi-window state sync, audience-facing layout); it sits *after* table-stakes so a player view doesn't just expose an unpolished tracker to more eyes. | ✦ | L |
| 19 | **3.1 Full-library compendium search & filter.** Powerful search across the whole library — CR, type, environment, source book, free-text on traits/actions. At 400+ monsters this is a selling point tools without bulk import *literally cannot match*. Extends the existing search/filters. | ✦ | M |

> **Milestone B — "Talked about":** ship 2.1 as the headline, supported by 3.1 to showcase what bulk import uniquely unlocks.

### ▸ P4 — Rounding out library leverage (Tier 3)

| # | Item | Tag | Effort |
|---|---|---|---|
| 20 | **3.2 Encounter-difficulty calculator.** Party level/size vs creatures → difficulty bands. **Use the 5e 2014 encounter-building maths** (decided). | ✦ | S |
| 21 | **3.3 Saved encounter presets.** *Largely already done* (save/load exists). Audit for gaps (naming, duplication, reorder) and close them. | ✦ | S |

> **Milestone C — "Rounding out":** remaining Tier 3 polish.

### ▸ P5 — Pre-monetisation legal gate (Legal §8)

**Do not charge money or distribute widely until this is cleared.** Commercial distribution
raises the stakes on every P0 item.

| # | Item | Tag | Effort |
|---|---|---|---|
| 22 | **IP-lawyer consultation** (games-industry-familiar). The secondary-liability / inducement analysis is fact-specific and jurisdiction-dependent; a consult is cheap relative to the exposure. | 🛡 | — |
| 23 | **Terms of use + privacy statement.** Local-only storage is a *genuine selling point* here — say so. Finalise disclaimers. | 🛡 | S |
| 24 | **Re-confirm WotC Fan Content Policy** compliance (policies change — recheck periodically). | 🛡 | S |
| 25 | **Lock the AI-disclosure position** in shipped copy (from #4). | 🛡 | S |

### ▸ Backlog — demand-driven only

| # | Item | Decision |
|---|---|---|
| — | **4.1 Lightweight battle map / VTT** | Defer; revisit only on loud, specific demand. Large build that pulls toward out-resourced VTTs (Roll20/Foundry/EncounterPlus). |
| — | **4.2 Journal, generators, full character builder** | **Decline.** Each is its own crowded free category; none reinforces the parsing wedge. |

---

## 🆕 My added notes (things the three docs overlooked)

Lettered so they can be referenced; several are folded into the sequence above.

**A. Keep CC-BY *PDFs* out of git; commit the parsed ground-truth instead.**
The SRD is CC-BY so it's *legally* fine to store, but committing ~400-page PDFs bloats the
repo, and a stray commercial test PDF would be a real problem (we already had the
`.gitignore` near-miss). Pattern: keep test PDFs in a gitignored local `tests/fixtures/pdf/`,
commit only the **expected JSON** as the regression baseline. Belt-and-braces for the
anti-piracy posture *and* repo hygiene. (Drives #6.)

**B. The two-parser drift risk is real and growing.**
Every feature now ships twice (Python `src/` + JS `docs/`). Without a shared test corpus
they *will* diverge silently. #11 addresses testing; flag a longer-term decision on whether the
PWA's JS parser becomes the single source of truth and the desktop calls into it.

**C. "Empty compendium" cold-start — ❌ decided: leave empty.** *(Resolved.)*
Considered a one-click "Get the free SRD" onboarding step, but **declined**: StatForge is the
tool, not a signpost to free material, and won't advertise or link any content. First-run
stays empty by design; the About panel explains the bring-your-own-content model instead.

**D. PWA update-notification.**
Updates currently rely on a manual `sw.js` cache bump; DMs can run stale cached builds
without knowing. Add a "new version available — reload" prompt when the service worker
detects an update. Low effort, saves support headaches as features land. (Slot into P1.)

**E. Privacy-preserving feedback channel.**
DMs are testing on books you'll never see. A lightweight "report a parse problem" link
(that uploads **nothing** — just opens an issue/email the DM fills in) would surface failures
from layouts you can't reproduce. Keep it strictly opt-in and content-free to stay consistent
with the privacy posture.

**F. Mobile input ergonomics.**
The mobile UI just landed; do a quick pass on touch-target sizes and numeric inputs (HP/init
should trigger the numeric keypad, `inputmode="numeric"`). Cheap, and these are the
moments a tool feels cheap if neglected. (Slot into P2.)

**G. SRD attribution string — prepare it once, now.**
If any demo/screenshot ever uses SRD content, you need the exact CC-BY-4.0 attribution
ready. Draft it once and keep it in `About`; costs minutes, avoids a scramble later.

**H. 5.2 exclusions are a *test fixture* gotcha.**
When the corpus shows "Beholder missing" on SRD 5.2, that's correct behaviour — bake the
expectation into the fixtures so nobody "fixes" a non-bug.

---

## Resolved decisions (2026-06-07)

1. **Onboarding SRD (note C):** ❌ **Declined.** No link to or mention of the SRD or any
   free material — StatForge is the tool, not a content signpost. First-run stays empty.
2. **Parser / build source of truth (note B):** ✅ **Converge on the PWA.** The client-side
   build in `docs/` is now the single product for **both web and desktop**; the local
   launcher (`StatForge.bat`) and the desktop shortcut run the PWA. The `src/` Flask app is
   legacy and may be retired. New work lands in the PWA only.
3. **Ruleset for difficulty calc (#20):** ✅ **5e 2014.** Build the difficulty calculator on
   the 2014 encounter-building maths.
4. **AI-disclosure wording (#4):** ✅ **Locked:** *"AI-Assisted code only, No AI-generated
   Content or Artwork."* Now shown in the app's About & legal panel and the README.

> *Legal items are an organisational checklist, not legal advice. Before charging money or
> distributing widely, consult an IP lawyer familiar with the games industry (Legal §8).*
