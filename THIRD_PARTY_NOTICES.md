# Third-party notices

Kino Stream is GPL-3.0-or-later (see [LICENSE](LICENSE) and [docs/LICENSING.md](docs/LICENSING.md)). It does not include third-party code or binaries, with the one
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

The *Inter* typeface (SIL Open Font License 1.1, © The Inter Project Authors) is used only if it is installed on the system; it is not included.

## Brand artwork (design concept, not yet adopted by the project owner)

* `kino_stream_ui/assets/lumiere-wordmark.svg` contains the **outlines (vector shapes) of the word "Lumière"** taken from the locally installed font **EB Garamond** — style "EB Garamond 12 Regular" (`/usr/share/fonts/truetype/ebgaramond/EBGaramond12-Regular.ttf`, Ubuntu package
  `fonts-ebgaramond-extra` 0.016+git20210310.42d4f9f2-1) — © 2010–2012 Georg Duffner, **SIL Open Font License 1.1** (licence text: `/usr/share/doc/fonts-ebgaramond-extra/copyright`). The outlines were generated once with `tools/make_brand_assets.py`; no font file is bundled or distributed and the SVG
  contains no text or font reference. **Whether outlined lettering counts as a derivative work of the font, and what the OFL requires for it, has not been determined; this is a question for qualified review.** If it is a concern, regenerate the wordmark from a different typeface (`--font`).
* The frame symbol and the application icon (`packaging/kino-stream.svg`) are plain geometry drawn for this project.
* At run time the interface uses fonts that happen to be installed (Inter, Cantarell, and an editorial serif such as Literata, Source Serif 4 or EB Garamond, with generic fallbacks); none is bundled.
