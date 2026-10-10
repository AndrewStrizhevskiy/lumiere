# Phase 0 (offline titles) and interaction refinements — implementation record

Status: implemented **in the design sandbox only** (a local working copy (not part of this repository)); nothing is committed, merged into the public candidate or installed.
Approved scope: offline title cleanup, a better Continue Watching presentation using information the application already has, and low-risk interaction refinements.
**Not done, on purpose:** no online metadata of any kind, no provider, no credentials, no posters, no new setting, no change to the format of `recent.json` or `settings.json`, no change to how timestamps are written, no change to how recent entries are identified (still the torrent infohash).

## 1. The title cleaner (`kino_stream/titles.py`, pure)
`clean_release_name(name, max_year=None) -> CleanedTitle(original, display, year, kind)`; kinds: `cleaned` (release noise removed on clear evidence), `readable` (no confident cleaning: only the extension dropped and separators shown as spaces, never a year), `declined` (episode / season pack / collection: shown as a readable name, never as a film).
It imports only `re`, `unicodedata`, `dataclasses`, `datetime`; it does no I/O, no network, loads no Qt; the plausible-year ceiling is an argument (the clock is only the default). A test runs it with sockets disabled and asserts that no Qt, libtorrent or HTTP module gets loaded.

**Rules (all conservative):**
* A title is cut only at the first *strong* release tag (resolution, source, video/audio codec, HDR). Weak words (`EXTENDED`, `REMASTERED`, `Cut`…) are noise only after a year or a strong tag, so "The Final Cut 1999" keeps "Cut".
* A **year** is reported only when (a) it sits directly before the release tags, (b) it is in a plausible range (1888 … ceiling), (c) it is not immediately preceded by another plausible year, or (d) it is the only year in parentheses/brackets. `Blade.Runner.2049.2017…` → "Blade Runner 2049", 2017 (2049 is not a possible release year); `2001.A.Space.Odyssey.1968…` → year 1968, "2001" stays in the title.
* **No year without release evidence:** `Sintel.2010.mkv` stays "Sintel 2010" with no year; `IMG_2048.mov` → "IMG 2048", no year; `Movie.Night.2024.2025.1080p.mkv` → "Movie Night 2024 2025", no year; `1917.2019.1080p…` → "1917 2019", no year (honest, if less elegant, than a guess).
* Episodes (`S01E03`, `1x03`, `E05`, "Episode 4"), season packs (`S01`, "Season 2", "Complete Series") and collections ("Trilogy", "Collection", "Box Set") are **declined**.
* Spelling, case, accents and meaningful punctuation are preserved (`Wall-E`, `Don't Look Up`, `What Ever Happened to Baby Jane?`, `Dr. Strangelove`); dots count as separators only in dot-separated names; non-ASCII names work (`Левиафан`, `千と千尋の神隠し`, `Amélie`); decomposed accents are normalised to composed form for comparison/display, the stored original is untouched.
* **Nothing is invented**: a property test checks that every word of a result and every year occurs in the original name.

**Known limitations (deliberate):** `Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p…` becomes "Le Fabuleux Destin d Amelie Poulain" with year 2001 — **not** "d'Amélie", as in the example in the request: restoring an apostrophe and an accent would be inventing spelling, and a generic elision rule misfires on names such as `L.A.Confidential` ("L'A"). Dotted acronyms lose their dots (`L.A.Confidential` → "L A Confidential"). A year at the very end of a name without any release tag is not extracted. Release words in other languages are not recognised. A title that is itself a plausible year followed by another year stays ambiguous.

**Boundary for the interface:** `DisplayTitle(text, year, original, source)` and `for_recent_item(item)` (reads only the existing `title` field, never modifies the item). `source` is `"filename-cleaned"` or `"filename"`; a future metadata source could return the same structure with another value without UI changes. No provider registry or abstraction beyond this was built.

## 2. Continue watching (`kino_stream_ui/home.py`)
Hierarchy per card: **title** (editorial serif, one line, elided), then one quiet line **`2024 · Resume at 5:00`** (the year only when the cleaner found clear evidence; progress wording unchanged: "Watched", "Resume at m:ss", "Not started"), then the existing progress bar. No poster, no placeholder artwork, no empty label ("Untitled" if there is no title at all). Card size is fixed (212×150), so a title that changes can never move the layout.
The tooltip shows the stored original name and, **labelled "Last opened: …"**, when the item was opened (the stored timestamp is `last_opened`; it is not claimed to be when the film was watched). Tooltip text is converted to safe rich text, so a hostile file name cannot inject markup (tested). The player's title bar uses the cleaned title for display only.
**Identity and data are unchanged:** entries are still keyed by infohash; two entries whose cleaned titles are equal stay two entries; clicking a card opens the *stored* source with the *stored* title, so the engine's and the saved title are the raw ones; building the list never writes `recent.json` (tested: bytes and modification time unchanged); positions and the watched flag are untouched across re-opening (tested).
**Multiple videos in one torrent — documented problem, not changed here:** a torrent has one entry and the played file is not stored (the engine re-picks the largest video file each time), so a pack with several films is shown under one title that is derived from the file that was picked at that time. Representing several files correctly would need `file_index`/`file_name` in `recent.json` (an additive change) and a decision about identity; this is a **separate change to be proposed and approved**, not part of this phase.

## 3. Interaction refinements (Qt animation classes only; no dependency)
| change | behaviour | notes |
|---|---|---|
| interruptible screen fade (`fade_in` / `_Fade`) | 200 ms ease-out; one effect and one animation per fade; starting a fade while one runs continues from the current opacity; the effect is removed only when the current animation really ran to the end | **Defect fixed:** the old version created a new opacity effect on every call and removed it from a `finished` callback, so rapid navigation could strip a newer fade's effect or leave a stale one. Never applied to the playback screen (GL surface). Stopped when the window closes |
| card hover / pressed / focus | 120 ms eased tone and hairline on hover, immediate pressed tone, 2 px focus ring; one repaint of one card per frame | replaces a per-event style sheet (which re-polished the card on every enter/leave) |
| banner | grows/collapses by animating its height (≈160 ms) instead of jumping the page; interruptible in both directions; the height target respects text wrapping; instant under reduced motion; the dismiss button collapses it | |
| spinner | static arc under reduced motion (it ignored the setting before) | |
| keyboard focus | recent cards show a ring (they had no visible focus), the invisible Tab stop of each scroll area is gone, primary/checked buttons have the two-band ring | pre-existing defects, present in the public candidate too |
Nothing waits for an animation: `go()` returns and changes the screen synchronously (measured 40 consecutive rapid calls, under 40 ms each, in a test), opening a file during a fade proceeds immediately, a card click is delivered while its hover transition runs. Callbacks only update a number and request a repaint.

### Playback-control fade — measured, **not implemented**
Real Wayland display, real libmpv playback of a 25 fps test video, every video repaint timestamped, three consecutive 6-second windows:
| condition | video repaints | mean / p95 / max interval | repaints later than 80 ms | mean `paintGL` |
|---|---|---|---|---|
| A: controls static | 153 | 39.4 / 48.4 / 54.3 ms | 0 | 28.5 ms |
| B: controls shown/hidden instantly every 400 ms | 150 | 40.0 / 50.0 / 54.0 ms | 0 | 28.1 ms |
| C: both bars faded with an opacity effect (200 ms) every 400 ms | **141** | 39.9 / 46.7 / 59.1 ms | 0 | **30.6 ms** |
A single run on one machine: not conclusive. Reading: the fade added about 2 ms per video repaint (+7 %) and fewer repaints were counted in the window, without a late frame; a fade over the GL surface also keeps an opacity-0 bar as a live, focusable widget unless it is additionally hidden, which is an accessibility and fullscreen risk. The owner's condition was "implement only if it improves the experience without usability or accessibility problems"; the measured benefit is negligible and the risk is real, so **the controls keep their instant show/hide**. Recorded so the decision can be revisited.

## 4. Tests
`tests/test_titles.py` (29: ordinary names, years, season packs/episodes, Unicode, punctuation, empty input, misleading numbers, "nothing is invented", purity/no-network), `tests/test_continue_watching.py` (14: card content, fallbacks, hostile names, same-title entries stay distinct, no write to `recent.json`, positions preserved, no network, list update during playback, card click uses the stored title), `tests/test_motion.py` (40, both themes: rapid navigation, interruption continuity, resize and close during animation, no fade on the player, actions not delayed, reduced motion, banner smoothness/interruption/resize, hover/pressed/focus/disabled pixel states, keyboard activation).

**Results (final code, Ubuntu 24.04, GNOME/Wayland, Python 3.12, PyQt6 6.6.1 on Qt 6.4.2; 2026-10-09 evening):**

| command | exit | result |
|---|---|---|
| `python3 -X faulthandler -m unittest tests.test_titles tests.test_continue_watching tests.test_motion tests.test_accessibility tests.test_theme tests.test_ui tests.test_tour tests.test_launch` | 0 | **153 tests OK**, 99.0 s |
| full discovery, stress round 1: `python3 -X faulthandler -m unittest discover -s <sandbox>/tests -t <sandbox> -v` (two other GUI test loops running at the same time) | 0 | **294 tests, OK, 7 skipped**, 831.7 s |
| full discovery, stress round 2 (same conditions) | 0 | **294 tests, OK, 7 skipped**, 877.5 s |
| real-display player tests: `python3 -X faulthandler -m unittest -v tests.test_ui_player` (Wayland, real libmpv/OpenGL) | 0 | **9 tests OK**, 47.6 s |
* The 7 skipped tests in discovery are the OpenGL player tests (they skip themselves on the offscreen platform and run in the last row). No failure and no intermittent result occurred in these runs; real-internet tests were not run; no live metadata exists to test.
* These two full runs are the only full runs of the **final** tree, and both ran under deliberate concurrent load. The earlier full runs (211 tests) belong to the previous tree state.
* Verified by tests: file opening still goes through the existing workflow with the stored title; magnet/file workflows are untouched (existing tests in the same runs); positions and the watched flag survive re-opening; the cleaner and the cards make no network access (sockets disabled in the tests); ambiguous names fall back safely; the list updates while a video is open without disturbing it; keyboard focus is visible on every focusable control of Home and Settings (both themes); reduced motion makes every animation instant and the spinner static; animations can be interrupted, resized and closed mid-way without error; the application layout was exercised at small window sizes by the existing layout tests and the banner/fade resize tests.


## 5. Crash diagnostics (separate task)
Evidence of the original crash is preserved outside every repository in the maintainer's local crash-investigation archive (not part of this repository) (`original_crash/y_discover.log`, SHA-256 `2a441d67…`, killed by signal 11 in `test_ui.Window.test_open_failure_maps_to_dialog_and_hides_overlay`; its start/end times; the real-display run that followed), together with every later run and the scripts.
**Method (time-boxed, no unrelated behaviour changed, no test weakened):** crash tracer on (`python3 -X faulthandler`), `ulimit -c unlimited` with the core files directed to a scratch directory outside the repositories, and the concurrency hypothesis tested directly — in each of two rounds one full discovery run executed while two other GUI test loops (`test_ui`, `test_tour`, `test_launch`, `test_continue_watching`, `test_accessibility`, animations enabled) ran at the same time on 8 CPUs. Script: `CRASH_INVESTIGATION/scripts/crash_stress.sh`.
**Results:** both full runs finished with exit 0 (294 tests, 831.7 s and 877.5 s); **64 concurrent background iterations, all exit 0**; no "Fatal Python error" in any log; **no core file**. A second hypothesis — that the *old* `fade_in` (which replaced and removed opacity effects while animations were still running, in a run where animations were enabled) could crash natively — was hammered with overlapping fades and widgets destroyed mid-animation (6 seeds on the old code imported read-only from the public candidate, 3 on the new): all survived.
**Tally for the sandbox:** 8 full discovery runs in total — 1 crashed (exit 139; the tree of the earlier design phase, tracer off, other Qt processes of mine were running at the time) and 7 passed (one earlier run before the accessibility refinements, four later runs with the tracer on on the same tree as the crash, and the two final-tree runs under deliberate concurrent load) — plus 94 clean iterations of the GUI-module loops (30 + 64). **The crash did not recur; its cause is unknown; it is an intermittent, unresolved issue, not a fixed one.** Neither the concurrency hypothesis nor the animation-lifetime hypothesis is supported by the experiments, and neither is excluded (each experiment can only fail to reproduce). Whether the crash relates to the design changes remains unknown.
**Update 2026-10-10:** 9 full runs now (1 crash, 8 passes), plus 60 aggressive-GC iterations (thresholds 1/3/10/50) and 11 gdb-wrapped iterations, all clean; classification of the evidence and the recommended next step are in the maintainer's local crash-investigation archive (not part of this repository). Unresolved.
**Visibility:** recorded in `docs/RELEASE_READINESS.md` (a short appended section, the only edit this work makes to an engineering-owned file) and in `docs/design/LUMIERE_DESIGN.md`. If it recurs: keep the tracer on and the core-dump directory outside the repositories, and keep the log together with the exact command and the other processes running at the time.

## 6. Remaining risks and decisions
* The cleaner is a heuristic; it prefers an honest imperfect name to a wrong identity, and will sometimes show a noisier name or omit a year.
* The multi-file-torrent identity problem is documented, not solved (needs an approved, separate data-model change).
* "Last opened" is shown only in a tooltip; a visible "last watched" would need a new timestamp (not approved).
* The motion tests use real-time waits (about 70 s); they are the slowest part of the GUI suite.
* The intermittent native crash is unresolved (section 5).
* Decisions still open: adopting the visual identity, the product name and trademark checks, font bundling, an appearance setting, any online metadata (provider, privacy, legal review), the release configuration and commit identity.

## 7. Files
**Pre-existing engineering work (not touched by this design work; identical to the public candidate, except the one appended section noted below):** `CHANGELOG.md`, `RELEASE_NOTES.md`, `docs/INSTALL.md`, `docs/KNOWN_ISSUES.md`, `docs/LICENSING.md`, `docs/RELEASE_READINESS.md`, `kino_stream/lt_store.py`, `packaging/install.sh`, `packaging/kino-stream.desktop.in`, `tests/test_packaging.py`, `tests/test_stalls.py`.
**This phase — new:** `kino_stream/titles.py`, `tests/test_titles.py`, `tests/test_continue_watching.py`, `tests/test_motion.py`, this document. **This phase — changed:** `kino_stream_ui/home.py`, `kino_stream_ui/widgets.py`, `kino_stream_ui/mainwindow.py`, `kino_stream_ui/player.py`, `docs/design/CONTINUE_WATCHING_AND_INTERACTION_PROPOSAL.md`.
**Earlier design phases (already in delta v1/v2):** `kino_stream_ui/theme.py`, `brand.py`, `assets/`, `app.py`, `dialogs.py`, `messages.py`, `settings_screen.py`, `tour.py`, `packaging/kino-stream.svg`, `pyproject.toml`, `THIRD_PARTY_NOTICES.md`, `tools/make_brand_assets.py`, `tests/test_theme.py`, `tests/test_accessibility.py`, `tests/test_cache_restart_reuse.py`, `docs/design/*`, `docs/investigations/CACHE_RESTART_TEST.md`.
