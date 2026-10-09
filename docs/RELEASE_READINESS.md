# Release readiness — 0.3.0 (pre-1.0)

Assessment of whether a stranger can install, test, understand and contribute. Claims are limited to what was run; see the three lists.
All results below were measured on this exact source tree (the sanitized public history), on one machine: Ubuntu 24.04, GNOME/Wayland, ext4, Python 3.12.

## Passed
* **Full test discovery** (`python3 -m unittest discover -s tests -t .`, offscreen Qt): **171 tests in 755 s — OK, 164 ran, 7 skipped** (the OpenGL player tests, which need a real display and run separately).
* **Real-display OpenGL player tests** (`python3 -m unittest tests.test_ui_player`, Wayland, real libmpv, local swarm): **9 tests in 57 s — OK.** Torrent file and magnet link, each also through the launcher path; seek, pause, volume, tracks; player-error reporting; status wording.
* **Install / uninstall in disposable profiles** (`tests/test_packaging.py`, 8 tests, plus a manual run): install is repeatable (a second install leaves the profile byte-identical); only the documented files are created;
  other applications' files and `mimeapps.list` are untouched; the uninstaller removes only what the installer made and refuses to touch a foreign launcher; user data and a custom cache folder are kept unless `--purge-data`
  is given, and a custom cache folder is never deleted even then; a missing dependency is explained with the exact `apt` command; `desktop-file-validate` is clean.
* **Desktop launch** (manual, disposable profile, real Wayland session): `gio launch` on the installed `.desktop` file started the app; a second launch (`-- magnet:?…`) handed the link to the running window and exited 0.
* **Security-sensitive code**: magnet/`.torrent` hand-over (parsing, ownership-checked owner-only socket in `$XDG_RUNTIME_DIR`, size cap, `--` before `%U`), cache-deletion confinement, plain-text rendering of untrusted names, diagnostics redaction — all covered by tests.
* **Publish gate**: `tools/release_config.py check` fails while any `@@…@@` placeholder remains or `LICENSE` is missing; `.githooks/pre-push` runs it (3 tests).
* **Documented commands match the implementation**: `install.sh --check/--no-desktop-db`, `uninstall.sh --dry-run/--purge-data/--no-desktop-db`, `kino-stream --version`, `kino-stream-gui --version`, `doctor --network`, `play` options were each run or checked against `--help`.
* **Privacy audit** of every revision and every git object of the public repository: see the release report; no personal address, name, network, VPN or credential data found.

## Skipped
* The 7 player tests inside the discovery run (run separately, above).
* Real-internet tests (`tests/realswarm.py`, 25 GB `tests/large_scenarios.py`): opt-in, not run. Earlier real-swarm results (5 runs) are in `docs/real_swarm_report.json` and are not a guarantee.

## Unverified
* Anything other than Ubuntu 24.04 / GNOME / Wayland / ext4 / Intel graphics (X11, NVIDIA/AMD, other distributions, btrfs/xfs/tmpfs, other Qt/mpv versions).
* Playback of a real internet torrent **through the GUI** (engine-level real-swarm runs exist; GUI runs used local swarms).
* Clicking the launcher in the GNOME application menu; the `xdg-mime` default-handler flow (defaults are deliberately never changed by the installer).
* Screen-reader behaviour, multi-monitor fullscreen, audio/subtitle menus with many tracks.
* The root cause of two intermittent test failures — **unknown, not fixed**:
  * `tests/test_ui_player.py::test_magnet_link_plays_end_to_end` failed 2 of ~14 early runs; not reproduced in 40+ later runs and in the final run above.
  * `tests/test_stalls.py::LostRequests::test_black_holed_seeder…` failed in 2 of 6 earlier module/discovery runs; **8 of 8 repeat runs with extra diagnostics passed and the final discovery run passed**. No change was made that
    could be credited with fixing it; a failure now prints server/store state to help the next investigation.
  See `docs/KNOWN_ISSUES.md`.

## Licensing compatibility
GPL-3.0-or-later (see `docs/LICENSING.md`, `THIRD_PARTY_NOTICES.md`). No concerns for source distribution. If binary packages are ever built, bundling PyQt6 (GPL-3 only) and libmpv/python-mpv brings GPL redistribution
duties (offer source, keep notices). The bundled-icon provenance is covered by precautionary Feather/Lucide notices; the "drawn in the style of" statement could not be verified beyond the author's own account.

## Remaining blockers before publishing (need the maintainer)
1. Fill the release placeholders: GitHub `owner/name`, security contact email, conduct contact email — `python3 tools/release_config.py apply --repo … --security-email … --conduct-email …`; then `python3 tools/release_config.py check`.
2. Decide the commit author identity for the public history (currently the neutral `Kino Stream contributors <noreply@invalid>`).
3. Approve publication (creating the repository, pushing, tagging `v0.3.0`) — nothing has been pushed or published.
4. Real installation into a user profile has not been performed (only disposable profiles).
