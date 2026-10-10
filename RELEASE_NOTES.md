# Kino Stream 0.3.0 — first public version (pre-1.0)

Kino Stream plays a video from a torrent while it downloads, with a hard limit on the disk space used. This release adds a desktop app on
top of the existing engine and command line tool.

**Try it if:** you run Ubuntu 24.04 (GNOME/Wayland) and are happy to report problems.
**Don't rely on it for:** other platforms/filesystems (untested), or guaranteed smooth playback — that depends on the swarm and your network.

Highlights: a disk cache with a hard limit (tested with simulated crashes and process kills, on ext4 only) · embedded player with a seek bar showing downloaded parts · status messages that only state what was
measured · first-run tutorial · user-level installer and uninstaller (tested in disposable profiles; they do not touch other applications).

Please read [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md). Install: [docs/INSTALL.md](docs/INSTALL.md).
