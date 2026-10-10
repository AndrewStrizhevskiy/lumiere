# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-1.0: anything may change.

## [0.3.0] — first public version (not yet published)

### Changed
- **Release hygiene after 0.3.0-rc.1:** the optional outlined wordmark artwork, its generator and the `KINO_STREAM_WORDMARK_ART` switch were removed (the header name is plain text in the system serif; no font-derived artwork is shipped); `docs/NAMING.md` records the naming check (working name, not cleared); README screenshots regenerated; internal local paths and process references removed from the public documents; the unexplained crash is described in plain language in `docs/KNOWN_ISSUES.md` 0b; engine messages say Lumière; SPDX header added to the desktop-entry template.
- **Product renamed to Lumière** (display name only: window title, menus, dialogs, messages, tutorial, desktop entry `Name=`, installer text, documentation). Technical identifiers are unchanged: `kino-stream` / `kino-stream-gui` commands, `kino_stream` / `kino_stream_ui` packages, `kino-stream.desktop` and icon names, `StartupWMClass`, settings/state/cache folders and the cache marker. `KINO_STREAM_BRAND=kino` restores the previous display name. The header shows the name in the installed serif. Engine/CLI error strings that say "Kino Stream" were left as they are.

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
- Offline title cleaner (`kino_stream/titles.py`): removes release noise, takes a year only on clear evidence, declines episodes/season packs/collections, never contacts a network. Stored history format is unchanged.
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
See `docs/KNOWN_ISSUES.md`. Notably: tested on Ubuntu 24.04 / Wayland / ext4 only; one unexplained intermittent magnet test failure; **one unexplained native crash (SIGSEGV) in 1 of 18 full automated runs of the interface work, never reproduced** (section 0b).
