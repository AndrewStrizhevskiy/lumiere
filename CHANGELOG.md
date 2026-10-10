# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-1.0: anything may change.

## [0.3.0-rc.2] — unreleased (proposed)

### Changed (breaking for anything that used the old names)
- **Lumière is now the name everywhere, not only the display name.** Commands `lumiere` and `lumiere-gui`; Python packages `lumiere` and `lumiere_ui` (no import shim: pre-1.0); desktop entry, icon and window class `lumiere`; environment variables `LUMIERE_THEME`, `LUMIERE_REDUCE_MOTION`, `LUMIERE_BIN` (the old `KINO_STREAM_THEME` and `KINO_REDUCE_MOTION` are still honoured as a fallback). The interface strings now say "Lumière" directly (the `KINO_STREAM_BRAND` display switch is gone).
- **User folders moved to the new name, recoverably:** `~/.config|.local/state|.cache/kino-stream` become `…/lumiere` on first start (atomic rename, no copy, link left at the old name, journal for an interrupted run, nothing is merged or overwritten; see `docs/FILES_AND_DATA.md`). Settings, `recent.json`, cache indexes and cache contents are unchanged. New caches carry the marker `.lumiere-managed`; caches with the old marker `.kino-stream-managed` are still recognised.
- **Installer:** installs the new names, replaces a former installation (its app folder, menu entry and icon), leaves small compatibility launchers `kino-stream` / `kino-stream-gui`, and never touches user data; the uninstaller removes both generations (`--purge-data` also removes the old names' links).
- Tests: `tests/test_migration.py` (16 tests: migration, recovery from interruption, relocated folders, legacy marker), installer upgrade tests.

### Fixed
- **Option smuggling through a video's title (security hardening).** The GUI passed the title (taken from the torrent's file name, i.e. untrusted) to mpv as a `loadfile` option; python-mpv joins options with commas, so a name such as `x,script=…` could add extra mpv options. The title is now set as a property (never parsed as options). Regression test: `tests/test_mpv_load.py`. The command-line tool was not affected (the title is a single argument).

### Removed
- The optional outlined wordmark artwork, its generator and the `KINO_STREAM_WORDMARK_ART` switch (the header name is plain text in the system serif; no font-derived artwork is shipped). The `KINO_STREAM_BRAND` display switch is gone too.

### Documentation
- `docs/NAMING.md` records the naming check (working name, not legally cleared) and the old-to-new identity map; README screenshots regenerated; the known-issues and readiness documents were consolidated (detailed history moved to `docs/archive/`); local-machine references removed; the unexplained crash is described in plain language.
- Engine messages and the version string say Lumière / `0.3.0rc2`; SPDX header on the desktop-entry template.

*Entries for 0.3.0-rc.1 and earlier use the names of their time (`kino_stream`, `kino-stream`, …).*


## [0.3.0-rc.1] — 2026-10-10 (pre-release)

### Changed
- **Product renamed to Lumière** (display name only: window title, menus, dialogs, messages, tutorial, desktop entry `Name=`, installer text, documentation). At this release the technical names were still `kino-stream`, `kino_stream`, … (renamed in rc.2).

### Added
- Desktop app (PyQt6 + libmpv): Home with drop zone / magnet field / "Continue watching", Settings, first-run tutorial, error dialogs and a
  connection check, embedded player (play/pause, seek bar with on-disk availability, volume, fullscreen, audio/subtitle menus, connection
  panel, resume).
- Install/uninstall scripts for Ubuntu 24.04 (user-level, no root), `.desktop` launcher with `.torrent`/`magnet:` handling, single running instance,
  rotating `gui.log`, `kino-stream --version`.
- Documentation: how streaming and the bounded cache work, troubleshooting, files and data, install/uninstall, known limitations.

### Interface refinements (design direction "Lumière")
- Warm charcoal and ivory themes with documented contrast ratios; the player screen is always dark. Editorial serif for headings and film titles, local fonts only.
- Home: balanced column, larger headline, two crop marks; "Continue watching" with serif heading and rule; cards show year, title (two lines, elided between words), progress and a thin progress line; original file name in the tooltip.
- Offline title cleaner (`kino_stream/titles.py` (now `lumiere/titles.py`)): removes release noise, takes a year only on clear evidence, declines episodes/season packs/collections, never contacts a network. Stored history format is unchanged.
- Interruptible screen fades, hover/pressed states, animated banner, static spinner under reduced motion; keyboard-focus fixes (visible focus on every focusable control, no focus left on hidden controls).
- New tests (title cleaner, Continue Watching, motion, accessibility, themes, composition).

### Engine (from the 0.1–0.2 development line)
- Bounded sparse-file cache with admission control, eviction, durable index, journal and crash recovery.
- Fixed a native crash caused by `wait_for_alert()` use-after-free in the libtorrent Python binding (alerts are now read with `pop_alerts()` only; guarded by a test).
- Network diagnostics (`doctor --network`) with confirmed / observed / hypothesis verdicts.

### Fixed (since the first internal build)
- Installer: a launcher directory containing a space (or other shell/desktop-entry special characters) produced a desktop entry that GNOME silently refused to launch. The executable is now quoted per the Desktop Entry
  specification and the generated launcher script uses safe quoting; `%` in the launcher directory and control characters in any install path are refused with an explanation.
- Engine: **served zeros for a completed piece under heavy CPU load.** libtorrent can report a piece as complete before its bytes are readable from the file; the store then returned zeros (found as `http_mismatches: 1` in `tests.test_cli` runs under 10-way load: 4 of 100 runs; the data was correct 0.3 s later). The store contract is "never zero/missing data": each piece lying inside the streamed file is now checked against its SHA-1 the first time it is served (about 8 ms per 4 MiB piece), and the HTTP server waits and asks again until the data is readable. Regression tests in `tests/test_cache.py` (red before, green after). Same load after the fix: 0 of 100. Boundary pieces shared with another file and torrents without v1 piece hashes are not checked.
- Engine: closing the store while the cache loop was in the middle of an eviction cancelled it between "punched" and "commit", leaving the eviction journal open after a clean exit (seen once under load as a failure of `tests.test_cli.CliBounded.test_play_seek_both_ways_inside_a_hard_cache_limit`, reproduced deterministically, regression test in `tests/test_cache.py`). `close()` now lets an in-flight eviction finish (bounded to 20 s, no new eviction starts). The cache limit and the recovery rules are unchanged; the journal would have been completed by recovery at the next start anyway.
- Engine: after a restart or cache eviction a healthy download could be declared "stuck" and the torrent restarted every 30 s; the restart message now also reports the threshold actually used.

### Known issues
See `docs/KNOWN_ISSUES.md` (the one unexplained native crash, lightly verified real-internet streaming, single-machine testing).
