# Security policy

Lumière is pre-1.0 software. Security reports are welcome.

**Report privately** — do not open a public issue. Use GitHub's "Report a vulnerability" (private advisory: https://github.com/AndrewStrizhevskiy/lumiere/security/advisories/new);
only the maintainers can see it. No e-mail address is published on purpose. Include the version, steps to reproduce and the impact you see.
You will get an acknowledgement; this is a volunteer project, so no response-time guarantee is made.

**Supported versions:** only the latest release.

**Areas of particular interest:** path handling in cache deletion (`kino_stream/caches.py`), parsing of untrusted `.torrent`/magnet input and file
names (rendered as plain text in the UI), the local HTTP server (binds to `127.0.0.1` only, random port), the single-instance socket
(`$XDG_RUNTIME_DIR/kino-stream-gui.sock`, owner-only, ownership checked before use), and the installer scripts.

**Out of scope:** the behaviour of BitTorrent peers or content you choose to stream; vulnerabilities in libtorrent, mpv or Qt (report those upstream).

**Privacy notes:** the app stores the sources you open (including full magnet links) in `~/.local/state/kino-stream/recent.json`; diagnostics output hides the
home folder and tracker URLs but not video titles. See `docs/FILES_AND_DATA.md`.
