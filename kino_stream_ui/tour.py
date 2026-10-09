"""First-run tutorial: five short steps with painted, gently animated illustrations.
Pure UI: it knows nothing about torrents, the engine or the player, and it only draws over the window and takes keyboard focus while open."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QWidget

from . import theme as T
from .messages import tr
from .motion import reduced_motion
from .widgets import button, label

STEPS = 5


@dataclass
class Step:
    title: str
    body: str
    note: str = ""


def steps(cache_gb: float) -> list[Step]:
    gb = f"{cache_gb:g} GB"
    return [
        Step(tr("Watch while it downloads", "Tour"),
             tr("Kino Stream plays a video from a torrent while it is still downloading, so you don't have to wait for the whole file.", "Tour")),
        Step(tr("Open a video", "Tour"),
             tr("Drop a .torrent file on the start screen, choose one from your computer, or paste a magnet link. Then press Play.", "Tour")),
        Step(tr("How buffering works", "Tour"),
             tr("The video arrives in small pieces from other people who share it. Kino Stream fetches the part you are about to watch first. Jumping to a part that has not been downloaded yet takes a moment.", "Tour"),
             tr("Smooth playback depends on how many people share the video, your network and your download speed. It cannot be guaranteed, and playback may pause to catch up.", "Tour")),
        Step(tr("Your disk stays under control", "Tour"),
             tr("Streaming uses at most %1 of disk space (you can change this in Settings). Older parts are removed automatically to stay under that limit.", "Tour").replace("%1", gb),
             tr("Kino Stream only ever removes data inside its own cache folder, and saved data is deleted only when you ask.", "Tour")),
        Step(tr("You're ready", "Tour"),
             tr("Pick a video and press Play. Space pauses, the arrow keys skip, F goes fullscreen.", "Tour"),
             tr("You can open this tutorial again from Help → Show Tutorial Again.", "Tour")),
    ]


def _c(hex_: str, a: float = 1.0) -> QColor:
    c = QColor(hex_)
    c.setAlphaF(a)
    return c


class Illustration(QWidget):
    """One painted scene per step. `phase` loops 0..1; with reduced motion it rests on the last frame and nothing animates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step = 0
        self.phase = 1.0
        self.setMinimumHeight(100)
        self._captions = True
        self.setAccessibleName(tr("Illustration", "Tour"))
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(4200)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._set)
        self.sync_motion()

    def sync_motion(self) -> None:
        if reduced_motion():
            self._anim.stop()
            self.phase = 1.0
            self.update()
        elif self.isVisible():
            self._anim.start()

    def showEvent(self, e):
        self.sync_motion()

    def hideEvent(self, e):
        self._anim.stop()

    def set_step(self, i: int) -> None:
        self.step = i
        self.update()

    def _set(self, v):
        self.phase = float(v)
        self.update()

    # ------------------------------------------------------------------------------------------------ painting
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.translate(w / 2, h / 2)
        s = min(w / 560.0, h / 170.0)
        self._captions = s >= 0.75                   # labels are unreadable when the scene is shrunk
        p.scale(s, s)
        [self._welcome, self._open, self._buffer, self._cache, self._ready][self.step](p)

    def _ease(self, t: float) -> float:
        return 1 - (1 - min(max(t, 0), 1)) ** 3

    def _welcome(self, p: QPainter) -> None:
        t = self._ease(self.phase * 1.6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(T.ELEVATED))
        p.drawRoundedRect(QRectF(-110, -62, 220, 124), 16, 16)
        p.setPen(QPen(_c(T.OUTLINE), 2))
        p.drawRoundedRect(QRectF(-110, -62, 220, 124), 16, 16)
        tri = QPainterPath()
        tri.moveTo(-16, -26)
        tri.lineTo(30, 0)
        tri.lineTo(-16, 26)
        tri.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(T.ACCENT))
        p.drawPath(tri)
        # download progress under the "screen": the video plays while the bar is still filling
        p.setBrush(_c(T.TRACK))
        p.drawRoundedRect(QRectF(-90, 44, 180, 6), 3, 3)
        p.setBrush(_c(T.AVAILABLE))
        p.drawRoundedRect(QRectF(-90, 44, 180 * (0.25 + 0.5 * t), 6), 3, 3)
        p.setBrush(_c(T.ACCENT))
        p.drawEllipse(QPointF(-90 + 180 * 0.18, 47), 5, 5)

    def _open(self, p: QPainter) -> None:
        t = self._ease(self.phase * 1.5)
        pen = QPen(_c(T.OUTLINE), 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(_c(T.SURFACE))
        p.drawRoundedRect(QRectF(-150, -60, 300, 120), 16, 16)
        # a file card dropping into the zone
        y = -100 + 76 * t
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(T.ELEVATED))
        p.drawRoundedRect(QRectF(-24, y - 8, 48, 60), 8, 8)
        p.setPen(QPen(_c(T.ACCENT), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(3):
            p.drawLine(QPointF(-12, y + 8 + i * 12), QPointF(12 - i * 5, y + 8 + i * 12))
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_c(T.TEXT2))
        if self._captions:
            p.drawText(QRectF(-150, 62, 130, 22), Qt.AlignmentFlag.AlignCenter, ".torrent")
            p.drawText(QRectF(20, 62, 130, 22), Qt.AlignmentFlag.AlignCenter, "magnet:?…")

    def _pieces(self, p: QPainter, n: int, x0: float, cell: float, y: float, have: list[float], head: float) -> None:
        for i in range(n):
            x = x0 + i * (cell + 3)
            f = have[i]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(T.TRACK))
            p.drawRoundedRect(QRectF(x, y, cell, 34), 4, 4)
            if f > 0:
                p.setBrush(_c(T.AVAILABLE, 0.35 + 0.65 * f))
                p.drawRoundedRect(QRectF(x, y + 34 * (1 - f), cell, 34 * f), 4, 4)
        hx = x0 + head * (cell + 3) + cell / 2
        p.setBrush(_c(T.ACCENT))
        tri = QPainterPath()
        tri.moveTo(hx - 7, y - 14)
        tri.lineTo(hx + 7, y - 14)
        tri.lineTo(hx, y - 3)
        tri.closeSubpath()
        p.drawPath(tri)

    def _buffer(self, p: QPainter) -> None:
        n, cell = 18, 22
        x0 = -(n * (cell + 3)) / 2
        head = 4 + 3 * self.phase
        have = []
        for i in range(n):
            if i < head - 1:
                have.append(1.0)
            else:
                have.append(min(max((self.phase * 1.4 + 0.35 - (i - head) * 0.11), 0.0), 1.0) if i - head < 7 else 0.0)
        self._pieces(p, n, x0, cell, -10, have, head)
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(_c(T.TEXT2))
        if self._captions:
            p.drawText(QRectF(x0, 40, n * (cell + 3), 20), Qt.AlignmentFlag.AlignLeft, tr("ready", "Tour"))
            p.drawText(QRectF(x0 + (head + 1.2) * (cell + 3), 40, 200, 20), Qt.AlignmentFlag.AlignLeft, tr("fetched next →", "Tour"))

    def _cache(self, p: QPainter) -> None:
        n, cell = 18, 22
        x0 = -(n * (cell + 3)) / 2
        head = 7 + 4 * self.phase
        have = []
        for i in range(n):
            behind = head - 3.5
            if i < behind - 1:
                have.append(0.0)                                   # already removed
            elif i < behind:
                have.append(max(0.0, behind - i))                  # fading out
            elif i < head + 4:
                have.append(1.0 if i < head else 0.6)
            else:
                have.append(0.0)
        self._pieces(p, n, x0, cell, -10, have, head)
        # the limit: a fixed frame around the part that is kept
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(T.ACCENT), 2, Qt.PenStyle.DashLine))
        a = x0 + 3 * (cell + 3) - 4
        p.drawRoundedRect(QRectF(a, -20, 12 * (cell + 3) + 4, 54), 8, 8)
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setBold(True)
        p.setFont(f)
        p.setPen(_c(T.ACCENT))
        if self._captions:
            p.drawText(QRectF(a, 40, 12 * (cell + 3), 20), Qt.AlignmentFlag.AlignCenter, tr("disk limit", "Tour"))

    def _ready(self, p: QPainter) -> None:
        t = self._ease(self.phase * 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(T.ACCENT, 0.16))
        p.drawEllipse(QPointF(0, 0), 62 + 6 * math.sin(self.phase * 2 * math.pi) * (0 if reduced_motion() else 1), 62 + 6 * math.sin(self.phase * 2 * math.pi) * (0 if reduced_motion() else 1))
        p.setBrush(_c(T.ACCENT))
        p.drawEllipse(QPointF(0, 0), 44, 44)
        p.setPen(QPen(_c(T.ON_ACCENT), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath()
        path.moveTo(-18, 2)
        path.lineTo(-5, 15)
        path.lineTo(20, -14)
        p.drawPath(path) if t >= 1 else p.drawPath(self._partial(path, t))

    @staticmethod
    def _partial(path: QPainterPath, t: float) -> QPainterPath:
        out = QPainterPath()
        n = 24
        out.moveTo(path.pointAtPercent(0))
        for i in range(1, int(n * t) + 1):
            out.lineTo(path.pointAtPercent(i / n))
        return out


class TourOverlay(QWidget):
    """Dimmed layer with a centred card. `finished(True)` after Finish, `finished(False)` after Skip/Esc."""
    finished = pyqtSignal(bool)

    def __init__(self, parent: QWidget, cache_gb: float = 4.0):
        super().__init__(parent)
        self.setObjectName("tour")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#tour { background: rgba(14,15,18,232); }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.index = 0
        self.steps = steps(cache_gb)
        self._prev_focus: QWidget | None = None
        self._busy = False

        self.card = QFrame()
        self.card.setObjectName("tourcard")
        self.card.setProperty("card", "outlined")
        self.card.setMaximumWidth(660)
        self.card.setMinimumWidth(460)
        self.illu = Illustration()
        self.counter = label("", "caption")
        self.title = label("", "title", wrap=True)
        self.body = label("", "", wrap=True)
        self.note = label("", "secondary", wrap=True)
        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(T.S2)
        cl.addWidget(self.counter)
        cl.addWidget(self.title)
        cl.addWidget(self.body)
        cl.addWidget(self.note)
        self.fx = QGraphicsOpacityEffect(self.content)
        self.content.setGraphicsEffect(self.fx)
        self.fx.setOpacity(1.0)

        self.dots = QHBoxLayout()
        self.dots.setSpacing(T.S2)
        self.dot_w: list[QFrame] = []
        for _ in range(STEPS):
            d = QFrame()
            d.setFixedHeight(6)
            d.setFixedWidth(6)
            self.dot_w.append(d)
            self.dots.addWidget(d)
        self.dots.addStretch(1)

        self.skip = button(tr("Skip tutorial", "Tour"), "ghost", name=tr("Skip tutorial", "Tour"))
        self.back = button(tr("Back", "Tour"), "", "arrow-left", name=tr("Previous step", "Tour"))
        self.next = button(tr("Next", "Tour"), "primary", name=tr("Next step", "Tour"))
        self.skip.clicked.connect(lambda: self._close(False))
        self.back.clicked.connect(self.go_back)
        self.next.clicked.connect(self.go_next)
        row = QHBoxLayout()
        row.setSpacing(T.S2)
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.back)
        row.addWidget(self.next)

        cl_ = QVBoxLayout(self.card)
        cl_.setContentsMargins(T.S6, T.S6, T.S6, T.S4)
        cl_.setSpacing(T.S3)
        cl_.addWidget(self.illu, 1)
        cl_.addWidget(self.content)
        cl_.addLayout(self.dots)
        cl_.addLayout(row)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(T.S4, T.S4, T.S4, T.S4)
        outer.addStretch(1)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(self.card, 100)
        h.addStretch(1)
        outer.addLayout(h)
        outer.addStretch(1)
        self.setTabOrder(self.skip, self.back)
        self.setTabOrder(self.back, self.next)
        self._apply(animate=False)
        self.hide()

    # ----------------------------------------------------------------------------------------------- lifecycle
    def open(self, cache_gb: float | None = None, start: int = 0) -> None:
        if cache_gb is not None:
            self.steps = steps(cache_gb)
        self.index = start
        self._prev_focus = self.window().focusWidget() if self.window() else None
        self._apply(animate=False)
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        if not reduced_motion():
            fx = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(fx)
            a = QPropertyAnimation(fx, b"opacity", self)
            a.setDuration(T.DUR_BASE)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.finished.connect(lambda: self.setGraphicsEffect(None))
            a.start()
            self._open_anim = a
        self.next.setFocus()
        self._fit()

    def _close(self, completed: bool) -> None:
        self.hide()
        if self._prev_focus is not None:
            try:
                self._prev_focus.setFocus()
            except RuntimeError:
                pass
        self.finished.emit(completed)

    # --------------------------------------------------------------------------------------------- navigation
    def go_next(self) -> None:
        if self.index >= STEPS - 1:
            self._close(True)
        else:
            self._goto(self.index + 1)

    def go_back(self) -> None:
        if self.index > 0:
            self._goto(self.index - 1)

    def _goto(self, i: int) -> None:
        if self._busy:
            return
        if reduced_motion():
            self.index = i
            self._apply(animate=False)
            return
        self._busy = True
        out = QPropertyAnimation(self.fx, b"opacity", self)
        out.setDuration(T.DUR_FAST)
        out.setStartValue(self.fx.opacity())
        out.setEndValue(0.0)

        def swap():
            self.index = i
            self._apply(animate=False)
            inn = QPropertyAnimation(self.fx, b"opacity", self)
            inn.setDuration(T.DUR_BASE)
            inn.setStartValue(0.0)
            inn.setEndValue(1.0)
            inn.setEasingCurve(QEasingCurve.Type.OutCubic)
            inn.finished.connect(lambda: setattr(self, "_busy", False))
            inn.start()
            self._in_anim = inn
        out.finished.connect(swap)
        out.start()
        self._out_anim = out

    def _apply(self, animate: bool = False) -> None:
        s = self.steps[self.index]
        last = self.index == STEPS - 1
        self.counter.setText(tr("Step %1 of %2", "Tour").replace("%1", str(self.index + 1)).replace("%2", str(STEPS)))
        self.title.setText(s.title)
        self.body.setText(s.body)
        self.note.setText(s.note)
        self.note.setVisible(bool(s.note))
        self.illu.set_step(self.index)
        self.back.setEnabled(self.index > 0)
        self.skip.setVisible(not last)
        self.next.setText(tr("Finish", "Tour") if last else tr("Next", "Tour"))
        self.next.setAccessibleName(tr("Finish tutorial", "Tour") if last else tr("Next step", "Tour"))
        for i, d in enumerate(self.dot_w):
            d.setStyleSheet(f"background:{T.ACCENT if i == self.index else T.TRACK}; border-radius:3px;")
            d.setFixedWidth(18 if i == self.index else 6)
        name = tr("Tutorial, step %1 of %2: %3", "Tour").replace("%1", str(self.index + 1)).replace("%2", str(STEPS)).replace("%3", s.title)
        self.card.setAccessibleName(name)
        self.card.setAccessibleDescription(" ".join(x for x in (s.body, s.note) if x))
        self.setAccessibleName(name)

    # --------------------------------------------------------------------------------------------------- input
    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._close(False)
        elif k == Qt.Key.Key_Right:
            self.go_next()
        elif k == Qt.Key.Key_Left:
            self.go_back()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not isinstance(self.focusWidget(), type(self.next)):
            self.go_next()
        else:
            super().keyPressEvent(e)

    def mousePressEvent(self, e):                  # clicks on the dim layer must not reach the window below
        e.accept()

    def _fit(self) -> None:
        """Small windows: shrink the illustration instead of letting the card overflow."""
        h = self.height()
        ih = 170 if h >= 600 else 130 if h >= 520 else 100 if h >= 470 else 0
        self.illu.setFixedHeight(max(ih, 1))
        self.illu.setVisible(ih > 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()
