# Lumière 0.3.0-rc.1 — release candidate (pre-1.0, pre-release)

> **This is a pre-release for testing, not a stable release.** It is not claimed to be crash-free. Known limitations are listed below and in [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

The application is called **Lumière** (previously "Kino Stream"). *Update after this release candidate:* the commands, Python packages, desktop entry and data folders were renamed to `lumiere` as well, with an automatic, recoverable migration of existing folders and compatibility launchers for the old command names (see the CHANGELOG, `docs/INSTALL.md` and `docs/FILES_AND_DATA.md`); the rc.1 release itself used the old technical names. The name is **not legally cleared**: a quick search found other software called Lumière and no trademark register was searched (see the naming note in the README).

Lumière plays a video from a torrent while it downloads, with a hard limit on the disk space used. This release adds a desktop app on
top of the existing engine and command line tool.

**Try it if:** you run Ubuntu 24.04 (GNOME/Wayland) and are happy to report problems.
**Don't rely on it for:** other platforms/filesystems (untested), or guaranteed smooth playback — that depends on the swarm and your network.

Highlights: a disk cache with a hard limit (tested with simulated crashes and process kills, on ext4 only) · embedded player with a seek bar showing downloaded parts · status messages that only state what was
measured · first-run tutorial · user-level installer and uninstaller (tested in disposable profiles; they do not touch other applications).

Also new in this build: a refined interface (warm dark/light themes, balanced Home, readable "Continue watching" titles made offline from the file name, keyboard-visible focus, reduced-motion support). **Known risk:** one unexplained native crash was seen once in 18 full runs of the automated tests and has not been reproduced; do not treat the application as crash-free.

Please read [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). Install: [docs/INSTALL.md](docs/INSTALL.md).

**Known limitations in short:** one unexplained intermittent native crash (SIGSEGV) in one of 18 full runs of the automated tests, never reproduced, only seen inside the test harness (the cache journal is crash-safe, tested with real SIGKILL); verified on one machine (Ubuntu 24.04, GNOME/Wayland, ext4) with local swarms only; two of three first real-internet torrents did not start streaming in the first real use (cause not established); no screen-reader, X11, HiDPI or high-contrast testing; one "Continue watching" entry per torrent; the title cleaner is offline and deliberately conservative; fonts are not bundled. Reports: use GitHub's private vulnerability reporting for security issues, and issues for everything else.
