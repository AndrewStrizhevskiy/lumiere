# Lumière 0.3.0-rc.2 — release candidate (pre-1.0, pre-release)

> **A pre-release for testing, not a stable release.** It is not claimed to be crash-free; see *Known limitations* below.

**Lumière** plays a video from a torrent while it downloads, with a hard limit on the disk space used. It is a Linux desktop app (PyQt6 + libmpv over a libtorrent engine) with a command-line tool, tested on Ubuntu 24.04 (GNOME on Wayland).

## What is new since 0.3.0-rc.1
* **Lumière is now the name everywhere:** commands `lumiere` and `lumiere-gui`, Python packages `lumiere` and `lumiere_ui`, the desktop entry and icon, and the folders `~/.config/lumiere`, `~/.local/state/lumiere` and `~/.cache/lumiere`.
* **Automatic, recoverable upgrade of your data.** The first start moves your old `kino-stream` folders to the new names (a rename, not a copy: a large cache is not duplicated and nothing is deleted; a link is left at the old name). An interrupted run is completed at the next start, and nothing is merged or overwritten. Settings, Continue Watching history and caches are unchanged and keep working.
* **The installer replaces an old installation** (its app folder, menu entry and icon) and leaves two small compatibility launchers, `kino-stream` and `kino-stream-gui`, that run the new commands. Your data is never touched by the installer or by `uninstall.sh` (only `--purge-data` removes data).
* **Security hardening:** a video's title (from the torrent's file name) is no longer passed to mpv as an option string, which could let a crafted file name add mpv options.
* The optional outlined wordmark artwork was removed: the header name is plain text in the system serif, and no font or artwork is bundled.
* Documentation: a naming page, current screenshots, and consolidated known issues.

Upgrading from 0.3.0-rc.1 or earlier: run `./packaging/install.sh` from the new version; see [docs/INSTALL.md](docs/INSTALL.md#upgrading-from-the-former-name-kino-stream). Old environment variables `KINO_STREAM_THEME` and `KINO_REDUCE_MOTION` are still honoured; the new ones are `LUMIERE_THEME` and `LUMIERE_REDUCE_MOTION`. The Python package names changed without an import shim (pre-1.0).

## Known limitations (full list: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md))
* **One unexplained native crash:** the automated test suite was once killed by a segmentation fault (1 of 18 full runs during development). It was never reproduced and has only been seen inside the test run, but its cause is unknown. If Lumière closes unexpectedly, please open an issue with `~/.local/state/lumiere/crash.log`.
* Verified on one machine (Ubuntu 24.04, GNOME/Wayland, ext4) and mostly with local swarms; two of three first real-internet torrents did not start streaming (cause not established). Smooth playback depends on the swarm and your network.
* No screen-reader, X11, HiDPI or high-contrast testing. One Continue-Watching entry per torrent; the title cleaner works offline and is deliberately conservative.
* **"Lumière" is a working name and is not legally cleared** (see [docs/NAMING.md](docs/NAMING.md)); other software uses the same name and this project is not affiliated with it.

## Tests behind this candidate
Full suite 360 tests (8 skipped offscreen), exit 0, and the real-display player tests (10 OK), run on the previous candidate's code; after the rename and data migration only targeted tests were run (migration, installer, cache, startup, themes, UI; all OK) plus an installation check on a real profile. Details: [docs/RELEASE_READINESS.md](docs/RELEASE_READINESS.md).

Security reports: GitHub's private vulnerability reporting (Security tab). Licence: GPL-3.0-or-later.
