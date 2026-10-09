# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are pre-1.0: anything may change.

## [0.3.0] — first public version (not yet published)

### Added
- Desktop app (PyQt6 + libmpv): Home with drop zone / magnet field / "Continue watching", Settings, first-run tutorial, error dialogs and a
  connection check, embedded player (play/pause, seek bar with on-disk availability, volume, fullscreen, audio/subtitle menus, connection
  panel, resume).
- Install/uninstall scripts for Ubuntu 24.04 (user-level, no root), `.desktop` launcher with `.torrent`/`magnet:` handling, single running instance,
  rotating `gui.log`, `kino-stream --version`.
- Documentation: how streaming and the bounded cache work, troubleshooting, files and data, install/uninstall, known limitations.

### Engine (from the 0.1–0.2 development line)
- Bounded sparse-file cache with admission control, eviction, durable index, journal and crash recovery.
- Fixed a native crash caused by `wait_for_alert()` use-after-free in the libtorrent Python binding (alerts are now read with `pop_alerts()` only; guarded by a test).
- Network diagnostics (`doctor --network`) with confirmed / observed / hypothesis verdicts.

### Known issues
See `docs/KNOWN_ISSUES.md`. Notably: tested on Ubuntu 24.04 / Wayland / ext4 only; one unexplained intermittent magnet test failure.
