# R1–R6 implementation checklist (owner decisions of 2026-10-10 → code)

Scope: sandbox only; no new dependency, no persistent-data change, no online metadata, no player-screen change, no texture/grain, no system packages. Status marks are filled in at the end (`[x]` done and tested, `[~]` done with a stated limit, `[ ]` not done).

- [x] **R1 Home hero** — balanced, centred column (max 880 px) with left-aligned text; larger serif headline (role `hero` 40 px); icon removed from the hero; lead and action row left-aligned (magnet field takes the free width); **two** crop marks (top-left, bottom-right); tonal fill + the new resting edge; top spacing grows gently with window height so 1440 px feels composed, no decorative filler. Check 720 / 1040 / 1440 px.
- [x] **R2 Section headings** — serif 20 with a hairline rule (new `SectionHead` widget), readable in both themes and at 720 px; serif used only for display/section/title/film titles/settings row titles.
- [x] **R3 Title cards** — year line, serif title wrapped to 2 lines then elided (no overflow), progress text, 2 px progress line on the bottom edge; original name stays in the tooltip; cleaner untouched. Compare *balanced uniform cards* vs *one emphasised wide card* in screenshots and recommend; the code default stays uniform (no automatic emphasis).
- [x] **R4 Radii** — a small system instead of one value: `R_CARD` 3 px (editorial surfaces: cards, drop zone), `R_CTRL` 5 px (buttons, inputs, menus), pills unchanged.
- [x] **R5 Rhythm** — named gaps `GAP_SECTION` 32 / `GAP_GROUP` 16 / `GAP_TIGHT` 8 used the same way on Home, Continue Watching and Settings (header margins aligned).
- [x] **R6 Settings row titles** — serif role `rowtitle`; layout unchanged.
- [x] **Resting card edge** — new token `EDGE` (dark ≈2.0:1, light ≈1.9:1 against the page), used on cards and the drop zone; hover/pressed/focus unchanged in behaviour.
- [~] **Interaction/accessibility** — hover, pressed, focus (keyboard), disabled checked; reduced motion; interrupted transitions; Tab never lands on hidden controls (existing tests re-run + new tests).
- [x] **Not touched** — playback screen and controls, motion durations, data model, cleaner rules, engine, packaging, names.
- [x] **Verification** — tests (new + full suite + real-display player), before/after screenshots at 720/1040/1440 in both themes (+ empty, long titles, settings, card-layout comparison), delta v6 rebuilt and verified against the untouched public tree, safeguards re-checked, crash still documented as unresolved.

Notes on `[~]`: hover, pressed, keyboard focus, disabled (hero buttons), reduced motion and interrupted transitions are covered by `tests/test_motion.py`, `tests/test_accessibility.py`, `tests/test_craft.py` and the `states_*` screenshots; Tab order was exercised offscreen only, with no screen reader and no real-display manual keyboard session of the new Home.
