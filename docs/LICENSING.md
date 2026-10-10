# Licensing

**Kino Stream is licensed under the GNU General Public License, version 3 or (at your option) any later version (GPL-3.0-or-later).**
The full text is in [`LICENSE`](../LICENSE); every source file carries `SPDX-License-Identifier: GPL-3.0-or-later`.
Copyright is held by the Kino Stream contributors.

## Why GPL-3.0-or-later

The desktop app imports PyQt6, which is available only under **GPL-3** or Riverbank's commercial license, and it drives libmpv, which Ubuntu builds as **GPL-3+**.
Choosing GPL-3.0-or-later for the whole project is consistent with all of them, keeps the project simple, and keeps improvements open. Permissive alternatives
(MIT/Apache-2.0) would not let anyone ship the app without also complying with the GPL of those dependencies, so they would promise users more than they could deliver.
The engine package (`kino_stream`) does not import Qt or the mpv bindings, so it could be re-licensed more permissively in the future by its copyright holders if there is a need.

## Dependencies and their licenses

Kino Stream **does not bundle or redistribute** any third-party code or binaries: everything below is installed from the Linux distribution (Ubuntu 24.04 package copyright files were consulted).

| dependency | used by | license (as packaged) | compatibility with GPL-3.0-or-later |
|---|---|---|---|
| PyQt6 (and Qt 6) | desktop app | PyQt6: **GPL-3** (or commercial); Qt 6: LGPL-3 / GPL | compatible: the combined app is GPL-3, which is what we are |
| libmpv / mpv 0.37 | embedded player; `mpv` is also run as a separate process by the CLI | source GPL-2+ or LGPL-2.1+; **Ubuntu's binaries are GPL-3+** (linked to libsmbclient) | compatible |
| python-mpv 1.0.4 | app | GPL-2+ **or** LGPL-2.1+ (dual) | compatible (either option works with GPL-3) |
| libtorrent-rasterbar 2.0 (python3-libtorrent) | engine | BSD-3-Clause; the Ubuntu copyright file also lists Boost (BSL-1.0), zlib, MIT/Expat, public-domain and GPL-2+ components | compatible (GPL-2+ is compatible with GPL-3; the exact origin of the GPL-2+ files was not examined) |
| Python 3.12 standard library | everything | PSF License | compatible |
| ffmpeg | **tests only**, run as a separate process | LGPL/GPL | not linked, not redistributed |
| Inter font | optional look; **not bundled**, used only if installed | SIL OFL 1.1 | not distributed |
| Icons | `kino_stream_ui/icons.py` | drawn for this project in the style of the Feather/Lucide icon sets; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) | notices included as a precaution |

## Redistribution notes and concerns (read before packaging)

* **Source distribution (this repository):** no concern. Dependencies are referenced, not included.
* **Binary packages / Flatpak / AppImage (not provided):** bundling PyQt6, libmpv or python-mpv means redistributing GPL code; you would have to offer the corresponding source of
  everything bundled, keep their notices, and comply with GPL-3 for the combined work. libmpv built with GPL components cannot be mixed with non-GPL-compatible code.
* **PyQt6 is GPL-3 only** (not "or later"). Kino Stream's "or later" clause is fine, but the *combined* app is effectively GPL-3 for as long as it uses PyQt6.
* **Commercial or closed-source use** of the desktop app would require a commercial PyQt license *and* an LGPL build of mpv; that is outside this project's scope.
* **Contributions** are accepted under GPL-3.0-or-later; there is no contributor license agreement, so re-licensing later needs every contributor's consent.
* **Media used in documentation and tests:** the repository contains no third-party media. Test videos are generated with ffmpeg. Docs mention the Blender Foundation's open movies
  (*Sintel*, *Tears of Steel*, CC BY 3.0) only as examples of legally shareable torrents.
* **No warranty / lawful use:** the GPL disclaims warranty. Kino Stream does not provide or host content; users are responsible for using it lawfully.

This is engineering documentation, not legal advice. The compatibility check above rests on the license fields of the Ubuntu package copyright files and could not
be independently verified for other distributions.
