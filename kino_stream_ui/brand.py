# SPDX-License-Identifier: GPL-3.0-or-later
"""Brand constants and the vector symbol (the header name is plain text in the system serif; there is no wordmark artwork). Only DISPLAY text lives here; technical identifiers (package names, executables, desktop-entry id, settings and
cache directories, URI handling) are deliberately NOT derived from the product name, so a rename never touches existing installations or user data.

The product is shown as "Lumière" (owner decision, 2026-10-10; trademark and domain checks are still outstanding). The previous name "Kino Stream" is kept as SOURCE_NAME: the interface
strings are written with it and `messages.tr()` substitutes the display name, so the rename is one switch and fully reversible: set KINO_STREAM_BRAND=kino to show the old name."""
from __future__ import annotations

import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

CURRENT_NAME = "Kino Stream"      # the previous product name; the text of the interface strings (see messages.tr); never an identifier
PROPOSED_NAME = "Lumière"         # the product name now shown (kept under its old constant name for compatibility with tests and tools)


# Symbol geometry on a 24-unit grid, shared by the in-app symbol and the application icon (packaging/kino-stream.svg). Tuned for 16-24 px: a 2.6 unit frame
# stroke stays about 1.7 px wide at 16 px (the first version, 2.0, antialiased to a dim 1 px grey line) and the lit panel stays several pixels large.
FRAME = (2.5, 4.5, 19.0, 15.0)
FRAME_RADIUS = 2.2
STROKE = 2.6
PANEL = (8.8, 8.4, 9.6, 6.9)
PANEL_RADIUS = 0.9


def product_name() -> str:
    """The display name: Lumière, unless KINO_STREAM_BRAND=kino (or "kino stream") asks for the previous name."""
    return CURRENT_NAME if os.environ.get("KINO_STREAM_BRAND", "").strip().lower() in ("kino", "kino stream", "kino-stream") else PROPOSED_NAME


def paint_symbol(p: QPainter, rect: QRectF, frame: QColor, light: QColor, variant: str = "frame") -> None:
    """The symbol on a 24-unit grid scaled into `rect`: a cinema frame with a lit panel inside it (variant "frame", the chosen one) or with a beam of
    light crossing it (variant "light", exploration B). Geometry only: it must stay legible at 16 px and in a single colour (frame == light)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = min(rect.width(), rect.height()) / 24.0
    p.translate(rect.center().x() - 12 * s, rect.center().y() - 12 * s)
    p.scale(s, s)
    pen = QPen(frame, STROKE)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(*FRAME), FRAME_RADIUS, FRAME_RADIUS)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(light)
    if variant == "light":
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(3.8, 5.8, 16.4, 12.4), 1.4, 1.4)
        p.setClipPath(clip)
        beam = QPainterPath()
        beam.moveTo(10, 5.5)
        beam.lineTo(15.5, 5.5)
        beam.lineTo(9.5, 18.5)
        beam.lineTo(4, 18.5)
        beam.closeSubpath()
        p.drawPath(beam)
    else:
        p.drawRoundedRect(QRectF(*PANEL), PANEL_RADIUS, PANEL_RADIUS)
    p.restore()


def symbol_pixmap(size: int, frame: str, light: str | None = None, dpr: float = 2.0, variant: str = "frame") -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    paint_symbol(p, QRectF(0, 0, size, size), QColor(frame), QColor(light or frame), variant)
    p.end()
    return pm
