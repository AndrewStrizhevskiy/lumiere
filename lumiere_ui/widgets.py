# SPDX-License-Identifier: GPL-3.0-or-later
"""Reusable building blocks. Everything visual that appears on more than one screen lives here."""
from __future__ import annotations

from PyQt6.QtCore import (QEasingCurve, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation,
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


class ActionButton(QPushButton):
    """QPushButton whose focus ring has two bands where the button is filled with the accent: the style sheet draws the outer 2 px ring (FOCUS, contrast
    with the page); this adds an inner band (FOCUS_INNER, contrast with the burgundy fill), so the indicator reaches 3:1 against BOTH adjacent colours in
    both themes (a single dark ring on burgundy is only 2.4:1)."""

    def paintEvent(self, e):
        super().paintEvent(e)
        v = self.property("variant")
        if self.hasFocus() and (v == "primary" or (v == "segment" and self.isChecked())):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(T.FOCUS_INNER), 1.5)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(2.75, 2.75, -2.75, -2.75), max(T.R_CTRL - 3, 2), max(T.R_CTRL - 3, 2))
            p.end()


def button(text: str = "", variant: str = "", icon_name: str = "", icon_color: str | None = None, tip: str = "", name: str = "") -> QPushButton:
    b = ActionButton(text)
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


def icon_button(icon_name: str, tip: str, color: str | None = None, size: int = 20) -> QPushButton:
    color = color or T.TEXT2                  # tokens are read when the widget is built, not when this module is imported
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


class SectionHead(QWidget):
    """A section heading in the editorial serif followed by a hairline rule that runs to the edge of the column. Selective: used for Continue watching only."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.title = label(text, "sectionhead")
        rule = divider()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(T.S3)
        lay.addWidget(self.title)
        lay.addWidget(rule, 1, Qt.AlignmentFlag.AlignVCenter)

    def setText(self, text: str) -> None:
        self.title.setText(text)


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

    def __init__(self, color: str | None = None, track: str | None = None, height: int = 6, parent=None):
        super().__init__(parent)
        color, track = color or T.ACCENT, track or T.TRACK
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
    def __init__(self, color: str | None = None, parent=None):
        super().__init__(parent)
        color = color or T.SUCCESS
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

    def __init__(self, size: int = 28, color: str | None = None, parent=None):
        super().__init__(parent)
        color = color or T.ACCENT
        self.setFixedSize(size, size)
        self._a = 0
        self._c = QColor(color)
        self._t = QTimer(self)
        self._t.timeout.connect(self._step)

    def showEvent(self, e):
        from .motion import reduced_motion
        if reduced_motion():
            self._t.stop()                                       # a static arc still says "busy" without moving
        else:
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

    @staticmethod
    def colors() -> dict:
        return {"info": T.TEXT2, "warning": T.WARNING, "error": T.DANGER, "success": T.SUCCESS}

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
        self._height_anim: QPropertyAnimation | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.S4, T.S3, T.S3, T.S3)
        lay.setSpacing(T.S3)
        lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(col, 1)
        lay.addWidget(self._close, 0, Qt.AlignmentFlag.AlignTop)
        self.hide()

    def show_message(self, level: str, title: str, text: str, actions: list[tuple[str, str]] | None = None) -> None:
        c = self.colors().get(level, T.TEXT2)
        self._icon.setPixmap(__import__("lumiere_ui.icons", fromlist=["pixmap"]).pixmap("alert" if level in ("warning", "error") else "info", c, 20, 2.0))
        self._title.setText(title)
        self._text.setText(text)
        self.setStyleSheet(f"QFrame#banner {{ background: {T.SURFACE}; border: none; border-bottom: 2px solid {c}; border-radius: 0; }}")
        while self._actions.count():
            it = self._actions.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for key, text_ in actions or []:
            b = button(text_, "primary" if key == actions[0][0] and level == "error" else "", name=text_)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            self._actions.addWidget(b)
        self._actions.addStretch(1)
        self._expand()

    # --- height animation: the page below moves smoothly instead of jumping; instant under reduced motion; interruptible in both directions
    def _animate_height(self, end: int, then_hide: bool) -> None:
        from .motion import reduced_motion
        if self._height_anim is not None:
            self._height_anim.stop()
            self._height_anim.deleteLater()
            self._height_anim = None
        full = 16777215                                           # QWIDGETSIZE_MAX
        if reduced_motion() or not self.parentWidget() or not self.parentWidget().isVisible():
            self.setMaximumHeight(full)
            if then_hide:
                QFrame.hide(self)
            else:
                self.show()
            return
        start = self.height() if self.isVisible() else 0
        self.setMaximumHeight(start)
        self.show()
        a = QPropertyAnimation(self, b"maximumHeight", self)
        a.setStartValue(start)
        a.setEndValue(end)
        a.setDuration(max(1, int(T.DUR_BASE * 0.8 * (abs(end - start) / max(end, start, 1)))))
        a.setEasingCurve(QEasingCurve.Type.OutCubic)

        def done(anim=a):
            if anim is not self._height_anim:
                return
            self._height_anim = None
            if then_hide:
                QFrame.hide(self)
            self.setMaximumHeight(full)
        a.finished.connect(done)
        self._height_anim = a
        a.start()

    def natural_height(self) -> int:
        """Height the banner needs at its current width (its text wraps, so this can be smaller than sizeHint(), which assumes a default width)."""
        lay = self.layout()
        width = self.width() if self.width() > 100 else (self.parentWidget().width() if self.parentWidget() else 600)
        if lay is not None:
            lay.activate()
            if lay.hasHeightForWidth():
                return max(int(lay.totalHeightForWidth(max(width, 1))), 1)
        return max(self.sizeHint().height(), 1)

    def _expand(self) -> None:
        self._animate_height(self.natural_height(), False)

    def collapse(self) -> None:
        """Dismiss with a short collapse (instant under reduced motion)."""
        if not self.isVisible():
            return
        self._animate_height(0, True)

    def hide(self) -> None:                                      # instant, and it cancels a running height animation
        if self._height_anim is not None:
            self._height_anim.stop()
            self._height_anim.deleteLater()
            self._height_anim = None
        self.setMaximumHeight(16777215)
        super().hide()


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


class _Fade(QObject):
    """One opacity effect and one animation per fade, owned by the widget. Starting a new fade while one is running INTERRUPTS it and continues from the
    current opacity (no jump back to 0); the effect is removed only when an animation really ran to the end, so a stale 'finished' can never strip a newer fade."""

    def __init__(self, w: QWidget):
        super().__init__(w)
        self.w = w
        self.fx: QGraphicsOpacityEffect | None = None
        self.anim: QPropertyAnimation | None = None

    def start(self, ms: int) -> QPropertyAnimation:
        begin = 0.0
        if self.fx is None:
            self.fx = QGraphicsOpacityEffect(self.w)
            self.fx.setOpacity(0.0)
            self.w.setGraphicsEffect(self.fx)                   # the widget owns the effect from here on
        else:
            begin = float(self.fx.opacity())
        if self.anim is not None:
            self.anim.stop()
            self.anim.deleteLater()
        a = QPropertyAnimation(self.fx, b"opacity", self)
        a.setStartValue(begin)
        a.setEndValue(1.0)
        a.setDuration(max(1, int(ms * (1.0 - begin))))          # the remaining distance takes proportionally long
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(lambda anim=a: self._finished(anim))
        self.anim = a
        a.start()
        return a

    def _finished(self, anim: QPropertyAnimation) -> None:
        if anim is not self.anim or self.fx is None or float(self.fx.opacity()) < 0.999:
            return                                              # interrupted or replaced: not the end of the current fade
        self.remove()

    def remove(self) -> None:
        if self.anim is not None:
            self.anim.stop()
            self.anim.deleteLater()
            self.anim = None
        if self.fx is not None:
            self.fx = None
            self.w.setGraphicsEffect(None)                      # deletes the effect

    def running(self) -> bool:
        return self.anim is not None and self.anim.state() == QPropertyAnimation.State.Running


def fade_in(w: QWidget, ms: int = T.DUR_BASE) -> QPropertyAnimation | None:
    """Fade a screen in. Reduced motion: nothing is animated and any running fade is finished at once. Calling it again interrupts the running fade."""
    from .motion import reduced_motion
    f = getattr(w, "_lumiere_fade", None)
    if reduced_motion():
        if f is not None:
            f.remove()
        return None
    if f is None:
        f = w._lumiere_fade = _Fade(w)
    return f.start(ms)


def stop_fade(w: QWidget) -> None:
    f = getattr(w, "_lumiere_fade", None)
    if f is not None:
        f.remove()


class HoverFade(QObject):
    """A 0..1 value that eases toward 1 while the pointer is over a widget and back to 0 when it leaves (the style sheet cannot animate). Interruptible: reversing
    mid-way continues from the current value. Reduced motion: the value jumps. The callback is only `widget.update()`; nothing else happens per frame."""

    def __init__(self, widget: QWidget, ms: int = T.DUR_FAST):
        super().__init__(widget)
        self.w, self.ms, self.value = widget, ms, 0.0
        self._a = QVariantAnimation(self)
        self._a.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._a.valueChanged.connect(self._set)

    def _set(self, v) -> None:
        self.value = float(v)
        self.w.update()

    def go(self, on: bool) -> None:
        from .motion import reduced_motion
        end = 1.0 if on else 0.0
        self._a.stop()
        if reduced_motion() or not self.w.isVisible():
            self.value = end
            self.w.update()
            return
        self._a.setStartValue(self.value)
        self._a.setEndValue(end)
        self._a.setDuration(max(1, int(self.ms * abs(end - self.value))))
        self._a.start()

    def running(self) -> bool:
        return self._a.state() == QVariantAnimation.State.Running
