# Contributing

Thanks for helping. Bug reports with the **Diagnostics** text (Help → Diagnostics) and clear steps are the most useful contribution.

## Ground rules that protect users
* Never delete user data without an explicit, confirmed action; deletion code lives in `lumiere/caches.py` and is deliberately narrow.
* Never present an unverified network hypothesis as a fact in user-facing text (`lumiere_ui/messages.py`).
* All libtorrent calls stay in the engine thread. Never call `wait_for_alert()`; `tests/test_alert_safety.py` enforces it.
* `lumiere_ui/tour.py` and other pure-UI modules must not import the engine.
* Don't touch the user's network configuration (VPN, firewall, routes) or other applications from code or scripts.

## Setup
```bash
sudo apt install python3-libtorrent python3-pyqt6 python3-pyqt6.qtsvg python3-mpv libmpv2 mpv ffmpeg
git clone https://github.com/AndrewStrizhevskiy/lumiere.git && cd lumiere
python3 -m lumiere_ui        # run the app from the checkout
./bin/lumiere --help         # CLI from the checkout
```

## Tests
| command | what | time |
|---|---|---|
| `python3 -m unittest discover -s tests -t .` | engine, cache, CLI, GUI (offscreen), packaging; the OpenGL player tests are skipped | ~12 min |
| `python3 -m unittest tests.test_ui_player` | real libmpv/OpenGL player; needs a graphical session; a window appears | ~45 s |
| `python3 -m unittest tests.test_tour tests.test_ui tests.test_launch tests.test_packaging` | quick GUI/packaging subset | ~30 s |

Tests that need mpv/ffmpeg skip themselves when missing. Real-internet tests (`tests/realswarm.py`) are opt-in and never part of discovery.
GUI tests set `XDG_*` to temp dirs; keep it that way so tests never touch a real profile.

## Pull requests
Small, focused changes with tests; explain user-visible behaviour changes in the description and `CHANGELOG.md`. By contributing you agree your work is
released under GPL-3.0-or-later (see LICENSE and docs/LICENSING.md); there is no contributor license agreement. New source files should start with `# SPDX-License-Identifier: GPL-3.0-or-later`.
