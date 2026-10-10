# Third-party notices

Lumière is GPL-3.0-or-later (see [LICENSE](LICENSE) and [docs/LICENSING.md](docs/LICENSING.md)). It does not include third-party code or binaries, with the one
possible exception below. At run time it uses the following software installed from your distribution, each under its own license:

* **PyQt6** — © Riverbank Computing Limited — GPL-3 (https://www.riverbankcomputing.com/software/pyqt/)
* **Qt 6** — © The Qt Company and contributors — LGPL-3 / GPL (https://www.qt.io/)
* **mpv / libmpv** — © mpv developers — GPL-2+ / LGPL-2.1+ (Ubuntu binaries GPL-3+) (https://mpv.io/)
* **python-mpv** — © Sebastian Götte and contributors — GPL-2+ or LGPL-2.1+ (https://github.com/jaseg/python-mpv)
* **libtorrent-rasterbar** — © Arvid Norberg and contributors — BSD-3-Clause (https://libtorrent.org/)
* **Python** — © Python Software Foundation — PSF License

## Icons

The outline icons in `kino_stream_ui/icons.py` were drawn for this project (24×24, 2 px stroke, round caps) in the visual style of the Feather and Lucide icon sets. Some
shapes (for example the play, volume, folder, alert and check glyphs) are simple geometries that may coincide with those sets. As a precaution their notices are reproduced:

**Feather** — MIT License — Copyright (c) 2013-2017 Cole Bemis
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

**Lucide** — ISC License — Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part of Feather (MIT); all other copyright (c) for Lucide are held by Lucide Contributors 2022.
Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear
in all copies. THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT
SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

## Fonts

The *Inter* typeface (SIL Open Font License 1.1, © The Inter Project Authors) and the editorial serifs named in `kino_stream_ui/theme.py` (Literata, Source Serif 4, EB Garamond, Charis SIL, Noto Serif, Liberation Serif, DejaVu Serif) are used only if installed on the system; **no font is included or bundled**, and the interface falls back to generic families.

## Brand artwork and fonts

* The frame symbol and the application icon (`packaging/kino-stream.svg`) are plain geometry drawn for this project.
* No logo or wordmark artwork is shipped: the header name is plain text. (An earlier candidate included vector outlines of the word "Lumière" taken from the *EB Garamond* font, SIL OFL 1.1; that file was removed to keep the project free of font-derived artwork.)
* At run time the interface uses fonts that happen to be installed (Inter, Cantarell, and an editorial serif such as Literata, Source Serif 4 or EB Garamond, with generic fallbacks); none is bundled.
