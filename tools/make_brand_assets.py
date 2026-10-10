#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerates the brand artwork. Offline: uses Qt and a locally installed OFL serif (EB Garamond) only to *outline* the wordmark once; the result is plain SVG
path data, so no font is needed at run time. Usage:  QT_QPA_PLATFORM=offscreen python3 tools/make_brand_assets.py [--sheet docs/design/concept_logo_explorations.png]"""
import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontInfo, QImage, QPainter, QPainterPath  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from kino_stream_ui import brand  # noqa: E402

CHARCOAL, IVORY, BURGUNDY, OLIVE, SOFT, WARM = "#22211F", "#F1EDE4", "#854B49", "#85836F", "#EAE7E0", "#AAA59F"


def path_to_svg(path: QPainterPath) -> str:
    d, i, n = [], 0, path.elementCount()
    while i < n:
        e = path.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            d.append(f"M{e.x:.2f} {e.y:.2f}")
        elif e.type == QPainterPath.ElementType.LineToElement:
            d.append(f"L{e.x:.2f} {e.y:.2f}")
        elif e.type == QPainterPath.ElementType.CurveToElement:
            c1, c2 = path.elementAt(i + 1), path.elementAt(i + 2)
            d.append(f"C{e.x:.2f} {e.y:.2f} {c1.x:.2f} {c1.y:.2f} {c2.x:.2f} {c2.y:.2f}")
            i += 2
        i += 1
    return "".join(d) + "Z"


def wordmark_svg(text: str = "Lumière", family: str = "EB Garamond") -> str:
    f = QFont(family)
    f.setPixelSize(100)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
    if QFontInfo(f).family() != family:
        raise SystemExit(f"{family} is not installed here; install it (OFL) or pass another --font")
    path = QPainterPath()
    path.addText(0, 0, f, text)
    r = path.boundingRect()
    pad = 4
    vb = f"{r.left() - pad:.1f} {r.top() - pad:.1f} {r.width() + 2 * pad:.1f} {r.height() + 2 * pad:.1f}"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" role="img" aria-label="{text}">\n  <title>{text}</title>\n'
            f'  <!-- glyph outlines of {family} (SIL OFL 1.1), set once; colour = currentColor -->\n  <path fill="currentColor" d="{path_to_svg(path)}"/>\n</svg>\n')


def icon_svg(variant: str) -> str:
    """128-unit app icon: a charcoal tile with the frame symbol, using brand.FRAME/STROKE/PANEL (24-unit grid scaled by 4.4 and centred; the tile is nearly full-bleed so
    the symbol keeps as many pixels as possible at 16-24 px)."""
    s = 4.4
    ox = oy = 64 - 12 * s
    tile, frame, lit = {"mono": (CHARCOAL, SOFT, SOFT), "burgundy-tint": (CHARCOAL, SOFT, "#D49A96"), "burgundy": (CHARCOAL, SOFT, BURGUNDY),
                        "burgundy-tile": (BURGUNDY, SOFT, SOFT)}[variant]
    fx, fy, fw, fh = brand.FRAME
    px, py, pw, ph = brand.PANEL
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">\n  <title>Frame symbol (concept)</title>\n'
            f'  <rect x="3" y="3" width="122" height="122" rx="26" fill="{tile}"/>\n'
            f'  <rect x="{ox + fx * s:.2f}" y="{oy + fy * s:.2f}" width="{fw * s:.2f}" height="{fh * s:.2f}" rx="{brand.FRAME_RADIUS * s:.2f}" fill="none" stroke="{frame}" stroke-width="{brand.STROKE * s:.2f}"/>\n'
            f'  <rect x="{ox + px * s:.2f}" y="{oy + py * s:.2f}" width="{pw * s:.2f}" height="{ph * s:.2f}" rx="{brand.PANEL_RADIUS * s:.2f}" fill="{lit}"/>\n</svg>\n')


def sheet(out: Path) -> None:
    """Exploration sheet: concepts A (frame), B (light), C (wordmark) and four icon variants, each at 16/24/32/64 px, on dark, on ivory and in one colour."""
    sizes = (16, 24, 32, 64)
    W, H = 1180, 860
    img = QImage(W * 2, H * 2, QImage.Format.Format_ARGB32)
    img.setDevicePixelRatio(2)
    img.fill(QColor(IVORY))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    ui = QFont("Inter", 11)
    p.setFont(ui)
    p.fillRect(QRectF(0, 0, W, 410), QColor(CHARCOAL))
    p.setPen(QColor(WARM))
    p.drawText(20, 26, "CONCEPTS - not implemented functionality. A = frame (chosen), B = light, C = wordmark. Rows: two-colour, one-colour (monochrome check).")
    x = 20
    for name, var in (("A  frame", "frame"), ("B  light", "light")):
        p.setPen(QColor(SOFT)); p.drawText(x, 56, name)
        for row, (fr, li) in enumerate(((SOFT, "#D49A96"), (SOFT, SOFT))):
            xx = x
            for sz in sizes:
                brand.paint_symbol(p, QRectF(xx, 70 + row * 90 + (64 - sz) / 2, sz, sz), QColor(fr), QColor(li), var)
                xx += sz + 14
        x += 250
    p.setPen(QColor(SOFT)); p.drawText(540, 56, "C  wordmark (outlined EB Garamond; icon = symbol only)")
    from PyQt6.QtSvg import QSvgRenderer
    from PyQt6.QtCore import QByteArray
    svg = wordmark_svg().replace("currentColor", SOFT)
    r = QSvgRenderer(QByteArray(svg.encode())); vb = r.viewBoxF()
    for k, hgt in enumerate((72, 40, 24)):
        r.render(p, QRectF(540, 76 + [0, 90, 140][k], hgt * vb.width() / vb.height(), hgt))
    # light background row
    p.fillRect(QRectF(0, 410, W, 140), QColor(IVORY))
    p.setPen(QColor(CHARCOAL)); p.drawText(20, 436, "On ivory (light theme):")
    xx = 20
    for sz in sizes:
        brand.paint_symbol(p, QRectF(xx, 450 + (64 - sz) / 2, sz, sz), QColor(CHARCOAL), QColor(BURGUNDY), "frame"); xx += sz + 14
    svg = wordmark_svg().replace("currentColor", CHARCOAL); r = QSvgRenderer(QByteArray(svg.encode()))
    r.render(p, QRectF(400, 460, 60 * vb.width() / vb.height(), 60))
    # icon variants
    p.setPen(QColor(CHARCOAL)); p.drawText(20, 580, "App icon variants (tile + symbol) at 16 / 24 / 32 / 64 / 128 px - chosen: burgundy-tint")
    for k, var in enumerate(("mono", "burgundy-tint", "burgundy", "burgundy-tile")):
        r2 = QSvgRenderer(QByteArray(icon_svg(var).encode()))
        xx = 20 + k * 285
        p.setPen(QColor(CHARCOAL)); p.drawText(xx, 604, var)
        for sz in (16, 24, 32, 64):
            r2.render(p, QRectF(xx, 620 + (64 - sz) / 2, sz, sz)); xx += sz + 8
        r2.render(p, QRectF(20 + k * 285, 700, 128, 128))
    p.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="")
    ap.add_argument("--font", default="EB Garamond", help="locally installed serif family to outline for the wordmark (default: EB Garamond, SIL OFL 1.1)")
    ap.add_argument("--write", action="store_true", help="(re)write kino_stream_ui/assets/lumiere-wordmark.svg and packaging/kino-stream.svg")
    a = ap.parse_args()
    app = QApplication.instance() or QApplication(sys.argv)      # keep a reference: Qt fonts need the application alive
    if a.write:
        (ROOT / "kino_stream_ui" / "assets").mkdir(exist_ok=True)
        (ROOT / "kino_stream_ui" / "assets" / "lumiere-wordmark.svg").write_text(wordmark_svg(family=a.font), encoding="utf-8")
        (ROOT / "packaging" / "kino-stream.svg").write_text(icon_svg("burgundy-tint"), encoding="utf-8")
    if a.sheet:
        sheet(Path(a.sheet))


if __name__ == "__main__":
    main()
