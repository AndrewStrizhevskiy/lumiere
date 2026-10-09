# License decision (open — needs the maintainer's choice)

No `LICENSE` file has been added on purpose. Without one, the code is "all rights reserved": others may read it but not legally use, copy or change it.
This note lays out the options. It is engineering advice, not legal advice.

## Facts that constrain the choice (read from the Debian/Ubuntu copyright files on the development machine)

| component | how Kino Stream uses it | license |
|---|---|---|
| PyQt6 | imported by the desktop app (`kino_stream_ui`) | **GPL-3** (or a paid commercial license from Riverbank) |
| libmpv2 (Ubuntu build) | loaded by the app and used by the CLI via mpv | Ubuntu's binaries are **GPL-3+** (the source is GPL-2+/LGPL-2.1+) |
| python-mpv | imported by the app | GPL-2+ **or** LGPL-2.1+ |
| libtorrent (python3-libtorrent) | imported by the engine (`kino_stream`) | BSD-3-Clause |

The engine package (`kino_stream`) does not import Qt or mpv bindings; only the app (`kino_stream_ui`) does. Kino Stream does not bundle any of these:
they are installed from the distribution.

## Options

| option | pros | cons |
|---|---|---|
| **GPL-3.0-or-later** (whole repository) — *recommended* | matches PyQt6 (GPL-3) and Ubuntu's libmpv (GPL-3+) with no legal friction; simplest to explain; keeps improvements open; fine for a desktop app; "or later" keeps it compatible with future GPL versions | companies that want to embed the code in closed products cannot; contributors must accept copyleft |
| MIT / Apache-2.0 (whole repository) | maximally permissive; popular for libraries; Apache-2.0 adds a patent grant | the app is effectively unusable without PyQt6 (GPL) and libmpv (GPL), so a permissive label on the app gives users less than it appears; downstream *distributors* of a combined app would still have to comply with GPL; invites debate about whether importing PyQt6 under a permissive license is allowed |
| Split: engine `kino_stream` under MIT/Apache-2.0 or LGPL, app `kino_stream_ui` under GPL-3.0-or-later | lets others reuse the engine (cache + scheduler) in non-GPL projects; honest about the app's GPL dependencies | two licenses to document and maintain; contributors must know which directory is which; the engine's value to others is unproven |
| AGPL-3.0 | closes the "network service" loophole | pointless here: this is a local desktop app with no network service |
| LGPL-3.0 | weak copyleft for the engine | adds complexity without a clear benefit for an application |

## Recommendation

**GPL-3.0-or-later for the whole repository.** It is the only option that is consistent with every dependency the app actually needs, it keeps
the project simple, and nothing in the roadmap needs a permissive license. If you later want outside projects to reuse the engine, move
`kino_stream/` to a permissive license in a separate release (as sole copyright holder you can; contributions accepted under GPL would need their authors' consent first —
another reason to decide before accepting outside contributions).

## What happens once you decide
1. Add `LICENSE` (full text of the chosen license) and an SPDX line (`SPDX-License-Identifier: GPL-3.0-or-later`) to `pyproject.toml` (`license = ...`).
2. Update README → License and CONTRIBUTING (contributions are accepted under the same license).
3. Decide the copyright holder line (your name or handle) for source headers if you want them.
