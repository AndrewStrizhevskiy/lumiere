# Release readiness — 0.3.0 (pre-1.0)

Assessment of whether a stranger can install, test, understand and contribute. Claims are limited to what was run; see the three lists.

## Checks that passed
* **Full test discovery** (`python3 -m unittest discover -s tests -t .`, offscreen Qt, ~12 min): 162 tests, 154 passed, 7 skipped (the OpenGL player tests, by design in that
  mode), **1 failed**: the intermittent `test_stalls` black-hole test (see KNOWN_ISSUES; passes alone).
* **Real OpenGL player tests** (`python3 -m unittest tests.test_ui_player`, Wayland, real libmpv, local swarm): 9 tests, OK (50 s) — torrent file and magnet link, both also through the
  launcher path (`handle_external`), seek/pause/volume/tracks, error reporting, status wording.
* **GUI/launch/packaging subset** after the last edits: 41 tests OK (`test_ui`, `test_launch`, `test_tour`, `test_packaging`).
* **Install/uninstall in a throw-away HOME** (`tests/test_packaging.py`, 8 tests): creates only the documented files; other apps' files (mimeapps.list) byte-identical;
  idempotent re-install; refuses to overwrite/remove a foreign launcher; uninstall leaves nothing but user data; `--purge-data` never removes a custom cache folder; clear message for a missing dependency;
  `desktop-file-validate` clean; installed copy runs `--version`, `--help`, `--smoke`.
* **Desktop launch** (manual): `gio launch` of the installed `.desktop` file (throw-away profile, real Wayland session) started the app; a second launch with a magnet link returned in 0.65 s and handed it to the running window.
* **Window sizes**: Home, Settings, error dialogs, tutorial and player at 720×480 / ~1100×700 / 1600×900 with layout assertions and screenshots (`docs/gui/p5_*`); two layout problems found and fixed (player controls squeezed at minimum
  width with the panel open; clipped legend in the panel).
* **Logs/messages review**: code logs no magnet links, peer addresses or file contents; diagnostics and technical error details now hide the home folder and tracker URLs (tested).
* **Post-commit security review (2 findings, both fixed and tested):** (1) diagnostics redaction missed magnet links with `dn=` before `xt=`, other URL schemes, other users' home paths and IP addresses — now hides every magnet except its info-hash, every URL, IPs and `/home/<user>`; (2) the single-instance socket was in world-writable `/tmp`, so another local user could have squatted it and received forwarded magnet links — it now lives in `$XDG_RUNTIME_DIR` (fallback: the 0700 state directory), is owner-only, a socket or file not owned by you is refused (never replaced or trusted), and requests are size-capped.
* **Security review items** from earlier stages (cache deletion confinement, plain-text rendering of untrusted names) are covered by tests.

## Skipped
* The 7 OpenGL player tests in the discovery run (they run separately, above).
* Real-internet tests (`tests/realswarm.py`, 25 GB `tests/large_scenarios.py`) — opt-in, not run in P5. Earlier real-swarm results are in `docs/real_swarm_report.json` (5 runs) and are not a guarantee.

## Unverified
* Anything other than Ubuntu 24.04 / GNOME / Wayland / ext4 / Intel graphics (X11, NVIDIA/AMD, other distros, btrfs/xfs/tmpfs, other Qt/mpv versions).
* Playback of a real internet torrent **through the GUI** (engine-level real-swarm runs exist; GUI runs used local swarms).
* Clicking the launcher in the GNOME application menu and `xdg-mime` default-handler flow (the `.desktop` file is valid and launches via `gio`; defaults were deliberately not changed).
* Screen-reader behaviour; multi-monitor fullscreen; many-track audio/subtitle menus.
* The root cause of two intermittent test failures (magnet GUI test, `test_stalls` black-hole): **unknown**.

## Blockers and decisions before publishing
1. **License** — not chosen on purpose. Recommendation (GPL-3.0-or-later) and trade-offs: `docs/LICENSE_DECISION.md`. No `LICENSE` file exists yet.
2. **Personal data in the repository history.** Working-tree copies of IP addresses in `diag/*.json`, `docs/NETWORK_FINDINGS.md` and `docs/*.json` were replaced by documentation-range addresses (203.0.113.x), but
   (a) the **git history still contains the real addresses**, and (b) `docs/NETWORK_FINDINGS.md` and several file names name your networks, university, VPN software/provider and host details. Recommended: publish from a fresh
   history (or a filtered one) and decide whether `diag/*.json` / `docs/NETWORK_FINDINGS.md` belong in the public repo at all. Nothing was deleted or rewritten without your say-so.
3. **Contact addresses**: `SECURITY.md` and `CODE_OF_CONDUCT.md` contain placeholders for a security/conduct email; `.github/ISSUE_TEMPLATE/config.yml` has `OWNER/REPO` placeholders.
4. **Real installation**: the installer was only run in throw-away profiles. Run `./packaging/install.sh` yourself when you want it in your real profile (user-level, no root; uninstall documented).
5. Screenshots show a synthetic test video (colour bars), not a real movie.
