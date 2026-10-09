"""Reusable building blocks. Everything visual that appears on more than one screen lives here."""
from __future__ import annotations

from PyQt6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                          pyqtProperty, pyqtSignal)
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout, QLayoutItem, QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

from . import theme as T
from .icons import icon


def label(text: str = "", role: str = "", wrap: bool = False, align=None) -> QLabel:
    l = QLabel()
    l.setTextFormat(Qt.TextFormat.PlainText)       # torrent names and engine details are untrusted: never rich text
    l.setText(text)
    if role:
        l.setProperty("role", role)
    l.setWordWrap(wrap)
    if align is not None:
        l.setAlignment(align)
    return l


def button(text: str = "", variant: str = "", icon_name: str = "", icon_color: str | None = None, tip: str = "", name: str = "") -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        col = icon_color or (T.ON_ACCENT if variant == "primary" else T.TEXT)
        b.setIcon(icon(icon_name, col, 18))
        b.setIconSize(QSize(18, 18))
    if tip:
        b.setToolTip(tip)
    b.setAccessibleName(name or tip or text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def icon_button(icon_name: str, tip: str, color: str = T.TEXT2, size: int = 20) -> QPushButton:
    b = button("", "icon", icon_name, color, tip, tip)
    b.setIconSize(QSize(size, size))
    b.setIcon(icon(icon_name, color, size))
    return b


def card(outlined: bool = False) -> QFrame:
    f = QFrame()
    f.setProperty("card", "outlined" if outlined else "true")
    return f


def divider() -> QFrame:
    f = QFrame()
    f.setProperty("role", "divider")
    f.setFrameShape(QFrame.Shape.NoFrame)
    return f


def fmt_bytes(n: float) -> str:
    n = float(n or 0)
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= div:
            v = n / div
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{int(n)} B"


def fmt_speed(bps: float) -> str:
    return fmt_bytes(bps) + "/s" if bps >= 1024 else "0 KB/s"


def fmt_time(s: float | None) -> str:
    if s is None or s < 0:
        return "–:––"
    s = int(s)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class AnimatedBar(QWidget):
    """Thin rounded progress bar; the value eases to its target (200 ms) instead of jumping."""

    def __init__(self, color: str = T.ACCENT, track: str = T.TRACK, height: int = 6, parent=None):
        super().__init__(parent)
        self._v = 0.0
        self._color, self._track = QColor(color), QColor(track)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(T.DUR_BASE)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set)
        self.setAccessibleName("Progress")

    def _set(self, v):
        self._v = float(v)
        self.update()

    def setValue(self, v: float, animate: bool = True) -> None:
        v = min(max(v, 0.0), 1.0)
        if not animate or not self.isVisible():
            self._v = v
            self.update()
            return
        self._anim.stop()
        self._anim.setStartValue(self._v)
        self._anim.setEndValue(v)
        self._anim.start()

    def value(self) -> float:
        return self._anim.endValue() if self._anim.state() == QVariantAnimation.State.Running else self._v

    def setColor(self, c: str) -> None:
        self._color = QColor(c)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._track)
        p.drawRoundedRect(r, rad, rad)
        if self._v > 0:
            p.setBrush(self._color)
            p.drawRoundedRect(QRectF(0, 0, max(r.height(), r.width() * self._v), r.height()), rad, rad)


class Dot(QWidget):
    def __init__(self, color: str = T.SUCCESS, parent=None):
        super().__init__(parent)
        self._c = QColor(color)
        self.setFixedSize(10, 10)

    def setColor(self, c: str):
        self._c = QColor(c)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._c)
        p.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class Spinner(QWidget):
    """Quiet rotating arc (hidden animation when not visible)."""

    def __init__(self, size: int = 28, color: str = T.ACCENT, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._a = 0
        self._c = QColor(color)
        self._t = QTimer(self)
        self._t.timeout.connect(self._step)

    def showEvent(self, e):
        self._t.start(30)

    def hideEvent(self, e):
        self._t.stop()

    def _step(self):
        self._a = (self._a + 9) % 360
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(T.TRACK), 3)
        p.setPen(pen)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.drawEllipse(r)
        pen.setColor(self._c)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self._a * 16, -100 * 16)


class FlowLayout(QLayout):
    """Wraps its children like text: the card grid reflows when the window narrows."""

    def __init__(self, parent=None, spacing: int = T.S3):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._sp = spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect: QRect, test: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            w = it.sizeHint().width()
            if x + w > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + self._sp, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self._sp
            line_h = max(line_h, it.sizeHint().height())
        return y + line_h - rect.y()


class Segmented(QWidget):
    """Row of mutually exclusive buttons (settings choices). Emits the selected key."""
    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], current: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.S2)
        self._btns: dict[str, QPushButton] = {}
        for key, text in options:
            b = button(text, "segment", name=text)
            b.setCheckable(True)
            b.setAutoExclusive(False)
            b.clicked.connect(lambda _=False, k=key: self.set(k, True))
            lay.addWidget(b)
            self._btns[key] = b
        lay.addStretch(1)
        self.set(current, False)

    def set(self, key: str, emit: bool = False) -> None:
        for k, b in self._btns.items():
            b.setChecked(k == key)
        self._key = key
        if emit:
            self.changed.emit(key)

    def value(self) -> str:
        return self._key


class Banner(QFrame):
    """Inline message: icon, title, plain-words text, optional actions. level: info | warning | error | success."""
    action = pyqtSignal(str)
    dismissed = pyqtSignal()

    COLORS = {"info": T.TEXT2, "warning": T.WARNING, "error": T.DANGER, "success": T.SUCCESS}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("card", "outlined")
        self.setObjectName("banner")
        self._icon = QLabel()
        self._icon.setFixedSize(24, 24)
        self._title = label("", "")
        self._title.setStyleSheet("font-weight:600;")
        self._text = label("", "secondary", wrap=True)
        self._actions = QHBoxLayout()
        self._actions.setSpacing(T.S2)
        col = QVBoxLayout()
        col.setSpacing(T.S1)
        col.addWidget(self._title)
        col.addWidget(self._text)
        col.addLayout(self._actions)
        self._close = icon_button("x", "Dismiss", T.TEXT3, 16)
        self._close.clicked.connect(self.dismissed.emit)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.S4, T.S3, T.S3, T.S3)
        lay.setSpacing(T.S3)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(col, 1)
        lay.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        self.hide()

    def show_message(self, level: str, title: str, text: str, actions: list[tuple[str, str]] | None = None) -> None:
        c = self.COLORS.get(level, T.TEXT2)
        self._icon.setPixmap(__import__("kino_stream_ui.icons", fromlist=["pixmap"]).pixmap("alert" if level in ("warning", "error") else "info", c, 20, 2.0))
        self._title.setText(title)
        self._text.setText(text)
        self.setStyleSheet(f"QFrame#banner {{ border: 1px solid {c}; }}")
        while self._actions.count():
            it = self._actions.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for key, text_ in actions or []:
            b = button(text_, "primary" if key == actions[0][0] and level == "error" else "", name=text_)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            self._actions.addWidget(b)
        self._actions.addStretch(1)
        self.show()


class Toast(QLabel):
    """Short non-blocking note that fades in/out over its parent (bottom centre)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setStyleSheet(f"background:{T.ELEVATED}; border:1px solid {T.OUTLINE}; border-radius:{T.R_CTRL}px; padding:10px 16px;")
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self.hide()

    def say(self, text: str, ms: int = 3500) -> None:
        self.setText(text)
        self.adjustSize()
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 64)
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setDuration(T.DUR_BASE)
        self._anim.setStartValue(self._fx.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)

    def _fade_out(self):
        self._anim.stop()
        self._anim.setDuration(T.DUR_SLOW)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.hide)
        self._anim.start()


def fade_in(w: QWidget, ms: int = T.DUR_BASE) -> QPropertyAnimation | None:
    from .motion import reduced_motion
    if reduced_motion():
        return None
    fx = QGraphicsOpacityEffect(w)
    w.setGraphicsEffect(fx)
    a = QPropertyAnimation(fx, b"opacity", w)
    a.setDuration(ms)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.finished.connect(lambda: w.setGraphicsEffect(None))
    a.start()
    return a
