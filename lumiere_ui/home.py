# SPDX-License-Identifier: GPL-3.0-or-later
"""Home screen: one obvious thing to do (open a video), recent items, readiness. Plus the status strip shared by all screens."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import time

from lumiere import titles

from . import brand
from . import theme as T
from .icons import icon, pixmap
from .messages import tr
from .widgets import AnimatedBar, Dot, FlowLayout, HoverFade, SectionHead, button, card, fmt_bytes, fmt_speed, fmt_time, icon_button, label


def looks_like_magnet(s: str) -> bool:
    s = s.strip()
    return s.lower().startswith("magnet:?") and "xt=urn:btih:" in s.lower()



def brand_wordmark() -> QLabel:
    """Header name: plain text in the editorial serif (the first installed family of theme.SERIF_FAMILIES, a generic serif otherwise). No artwork, no bundled font."""
    return label(brand.product_name(), "wordmark")


def wrap_elide(text: str, font: QFont, width: int, max_lines: int = 2) -> list[str]:
    """Break `text` into at most `max_lines` lines no wider than `width`; the last line is elided with an ellipsis when the text does not fit.
    Long unbroken words (and CJK text) are broken anywhere. Pure layout: the text itself is never altered beyond the ellipsis."""
    from PyQt6.QtGui import QFontMetrics
    text = " ".join(text.split())
    if not text or width <= 0:
        return [text] if text else []
    tl = QTextLayout(text, font)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    tl.setTextOption(opt)
    spans = []
    tl.beginLayout()
    while True:
        line = tl.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textLength()))
    tl.endLayout()
    if len(spans) <= max_lines:
        return [text[a:a + n].strip() for a, n in spans]
    fm = QFontMetrics(font)
    head = [text[a:a + n].strip() for a, n in spans[:max_lines - 1]]
    rest = text[spans[max_lines - 1][0]:]
    return head + [_elide_at_word(rest, fm, width)]


def _elide_at_word(text: str, fm, width: int) -> str:
    """Elide to `width`, cutting between words when that is possible ("Geschichte über…" rather than "Geschichte über Dona…"); a first word that is itself too long is cut by character."""
    if fm.horizontalAdvance(text) <= width:
        return text
    words = text.split(" ")
    kept = ""
    for w in words:
        cand = (kept + " " + w).strip()
        if fm.horizontalAdvance(cand + "…") > width:
            break
        kept = cand
    return kept + "…" if kept else fm.elidedText(text, Qt.TextElideMode.ElideRight, width)


class StatusStrip(QFrame):
    """Always-visible one-line summary: readiness / activity, sources, speed, cache. Details live in the player's side panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusstrip")
        self.setStyleSheet(f"QFrame#statusstrip {{ background:{T.SURFACE}; border-top:1px solid {T.HAIRLINE}; }}")
        self.dot = Dot(T.TEXT3)
        self.text = label(tr("Checking…", "StatusStrip"))
        self.peers = label("", "secondary")
        self.speed = label("", "secondary")
        self.cache_label = label("", "secondary")
        self.cache_bar = AnimatedBar(T.ACCENT, T.TRACK, 6)
        self.cache_bar.setFixedWidth(110)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(T.S4, T.S2, T.S4, T.S2)
        lay.setSpacing(T.S3)
        for w in (self.dot, self.text):
            lay.addWidget(w)
        lay.addStretch(1)
        for w in (self.peers, self.speed, self.cache_label, self.cache_bar):
            lay.addWidget(w)
        self.set_idle(None, 0, 0)

    def set_ready(self, ok: bool, problem_text: str = "") -> None:
        self.dot.setColor(T.SUCCESS if ok else T.WARNING)
        self.text.setText(tr("Ready to stream", "StatusStrip") if ok else problem_text)

    def set_idle(self, ready: dict | None, cache_used: int, cache_limit: int) -> None:
        self.peers.setText("")
        self.speed.setText("")
        self._cache(cache_used, cache_limit)

    def _cache(self, used: int, limit: int) -> None:
        if limit:
            self.cache_label.setText(tr("Cache %1 of %2", "StatusStrip").replace("%1", fmt_bytes(used)).replace("%2", fmt_bytes(limit)))
            self.cache_bar.setValue(used / limit)
            self.cache_bar.show()
        else:
            self.cache_label.setText(tr("Cache %1 (no limit)", "StatusStrip").replace("%1", fmt_bytes(used)) if used else "")
            self.cache_bar.hide()

    def set_status(self, s: dict) -> None:
        phase = s.get("phase", "idle")
        names = {"opening": tr("Looking for sources…", "StatusStrip"), "starting": tr("Starting…", "StatusStrip"),
                 "playing": tr("Streaming", "StatusStrip"), "paused": tr("Paused", "StatusStrip"), "buffering": tr("Buffering…", "StatusStrip")}
        self.text.setText(names.get(phase, tr("Ready to stream", "StatusStrip")))
        self.dot.setColor({"buffering": T.WARNING, "opening": T.WARNING, "starting": T.WARNING}.get(phase, T.SUCCESS))
        if phase in ("idle", "opening"):
            return
        n = int(s.get("peers", 0))
        self.peers.setText(tr("%1 sources", "StatusStrip").replace("%1", str(n)) if n != 1 else tr("1 source", "StatusStrip"))
        self.speed.setText(fmt_speed(s.get("down_Bps", 0)))
        self._cache(int(s.get("cache_used", 0)), int(s.get("cache_limit", 0)))


class DropZone(QFrame):
    """The hero of the home screen: choose a .torrent, drop one, or paste a magnet link."""
    sourceChosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._hot = False
        self.setObjectName("dropzone")
        self.setMinimumHeight(200)
        title = self.hero = label(tr("Watch while it downloads", "Home"), "hero")
        self._hero_px = 0
        sub = label(tr("Drop a .torrent file here, or choose one", "Home"), "lead")
        self.open_btn = button(tr("Open torrent file", "Home"), "primary", "folder-open", name=tr("Open torrent file", "Home"))
        self.open_btn.clicked.connect(self.choose_file)
        self.magnet = QLineEdit()
        self.magnet.setPlaceholderText(tr("Paste a magnet link", "Home"))
        self.magnet.setAccessibleName(tr("Magnet link", "Home"))
        self.magnet.setMinimumWidth(200)
        self.magnet.returnPressed.connect(self.submit_magnet)
        self.paste_btn = icon_button("paste", tr("Paste from clipboard", "Home"))
        self.paste_btn.clicked.connect(self.paste)
        self.play_btn = button(tr("Play", "Home"), "", "play", name=tr("Play magnet link", "Home"))
        self.play_btn.clicked.connect(self.submit_magnet)
        self.error = label("", "caption")
        self.error.setStyleSheet(f"color:{T.DANGER};")
        self.error.hide()
        row = QHBoxLayout()                                              # text and actions share one left edge; the magnet field takes the free width
        row.setSpacing(T.S2)
        row.addWidget(self.open_btn)
        row.addSpacing(T.S3)
        row.addWidget(self.magnet, 1)
        row.addWidget(self.paste_btn)
        row.addWidget(self.play_btn)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S8, T.S8, T.S8 + T.S2, T.S8 + T.S2)     # room for the two crop marks (inset 16 px, 20 px long) around the text block
        lay.setSpacing(T.GAP_TIGHT)
        lay.addWidget(title)
        lay.addWidget(sub)
        lay.addSpacing(T.GAP_GROUP)
        lay.addLayout(row)
        lay.addWidget(self.error)
        self.setTabOrder(self.open_btn, self.magnet)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # the display line grows with the column (40 -> 48 px) so the hero keeps its typographic weight at 1440 px instead of leaving the box empty
        px = T.FS_HERO + (18 if self.width() >= 820 else 10)
        if px != self._hero_px:
            self._hero_px = px
            self.hero.setStyleSheet(f"font-size:{px}px;")

    # ----------------------------------------------------------------------------------------------- actions
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Open torrent file", "Home"), str(Path.home()), tr("Torrent files (*.torrent);;All files (*)", "Home"))
        if path:
            self.sourceChosen.emit(path)

    def paste(self) -> None:
        self.magnet.setText(QApplication.clipboard().text().strip())
        self.magnet.setFocus()

    def submit_magnet(self) -> None:
        text = self.magnet.text().strip()
        if not text:
            self.show_error(tr("Paste a magnet link first.", "Home"))
        elif not looks_like_magnet(text):
            self.show_error(tr("That doesn't look like a torrent link. It should start with “magnet:”.", "Home"))
        else:
            self.error.hide()
            self.sourceChosen.emit(text)

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.show()

    # ------------------------------------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() and any(u.toLocalFile().lower().endswith(".torrent") for u in md.urls()) or (md.hasText() and looks_like_magnet(md.text())):
            e.acceptProposedAction()
            self._hot = True
            self.update()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._hot = False
        self.update()

    def dropEvent(self, e):
        self._hot = False
        self.update()
        md = e.mimeData()
        for u in md.urls():
            f = u.toLocalFile()
            if f.lower().endswith(".torrent"):
                self.sourceChosen.emit(f)
                return
        if md.hasText() and looks_like_magnet(md.text()):
            self.sourceChosen.emit(md.text().strip())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(T.ELEVATED if self._hot else T.SURFACE))
        p.setPen(QPen(QColor(T.EDGE), 1.0))                              # the same resting edge as the cards
        p.drawRoundedRect(r, T.R_CARD, T.R_CARD)
        # film-gate crop marks: only two (top-left, bottom-right), quiet at rest, accent while a file is dragged over
        p.setBrush(Qt.BrushStyle.NoBrush)
        corner = QPen(QColor(T.ACCENT if self._hot else T.OUTLINE_STRONG), 2.0)
        corner.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(corner)
        m, L = 16.0, 20.0
        x0, y0, x1, y1 = r.left() + m, r.top() + m, r.right() - m, r.bottom() - m
        for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y1, -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + dx * L, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * L))
        p.end()


class RecentCard(QFrame):
    """One entry of "Continue watching". Identity and behaviour are unchanged (the item is the stored recent entry, keyed by infohash); only its presentation uses the
    cleaned title from lumiere.titles. The stored name is never modified and stays available in the tooltip."""
    clicked = pyqtSignal(dict)
    removeRequested = pyqtSignal(str)
    WIDTH, HEIGHT = 212, 128

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setProperty("card", "true")
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        d = titles.for_recent_item(item)
        self.display = d
        title = d.text or tr("Untitled", "Home")
        self.setAccessibleName(tr("Open %1", "Home").replace("%1", title))
        self.setToolTip(self._tooltip(d, item))
        pos, dur = float(item.get("position_s") or 0), float(item.get("duration_s") or 0)
        progress = tr("Watched", "Home") if item.get("watched") else (tr("Resume at %1", "Home").replace("%1", fmt_time(pos)) if pos > 5 else tr("Not started", "Home"))
        self.fraction = 1.0 if item.get("watched") else (min(pos / dur, 1.0) if dur else 0.0)
        self.watched = bool(item.get("watched"))
        # year (only when the cleaner found clear evidence), then the film title in the serif, wrapped to two lines and elided, then the progress in words
        self.year_label = label(str(d.year) if d.year else "", "caption")
        self.year_label.setFixedHeight(self.year_label.fontMetrics().height() + 2)        # the row is always reserved so titles line up across cards
        self.name_label = label("")
        self.name_label.setStyleSheet(f"font-family:{T._serif_css()}; font-size:{T.FS_LEAD + 2}px; font-weight:500;")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.text_width = self.WIDTH - 2 * (T.S4 + 2)
        self.name_label.ensurePolished()                                  # the style sheet's serif must be applied before the text is measured
        lines = wrap_elide(title, self.name_label.font(), self.text_width - 2, 2)
        self.name_label.setText("\n".join(lines))
        self.name_label.setFixedHeight(2 * self.name_label.fontMetrics().lineSpacing())
        self.progress_label = label(progress, "secondary")
        self.progress_label.setMaximumWidth(self.text_width)
        self.progress_label.setText(self.progress_label.fontMetrics().elidedText(progress, Qt.TextElideMode.ElideRight, self.text_width))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S4 + 2, T.S3 + 2, T.S4 + 2, T.S4 + 2)    # 2 px of card shows around the content: room for the hover border and the focus ring
        lay.setSpacing(0)
        lay.addWidget(self.year_label)
        lay.addWidget(self.name_label)
        lay.addStretch(1)
        lay.addWidget(self.progress_label)
        self._hover = HoverFade(self)
        self._pressed = False

    @staticmethod
    def _tooltip(d, item: dict) -> str:
        """Plain text turned into safe rich text (Qt would otherwise interpret markup in a hostile file name): the stored name, and - labelled honestly - when it was opened."""
        lines = [d.original or tr("Untitled", "Home")]
        opened = item.get("last_opened")
        if isinstance(opened, (int, float)) and opened > 0:
            lines.append(tr("Last opened: %1", "Home").replace("%1", time.strftime("%Y-%m-%d %H:%M", time.localtime(opened))))
        return Qt.convertFromPlainText("\n".join(lines))

    def enterEvent(self, e):
        self._hover.go(True)

    def leaveEvent(self, e):
        self._hover.go(False)
        if self._pressed:
            self._pressed = False
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        was = self._pressed
        self._pressed = False
        self.update()
        if e.button() == Qt.MouseButton.LeftButton and was and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.item)

    def paintEvent(self, e):
        super().paintEvent(e)                                        # the card surface (style sheet)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        v = self._hover.value
        if self._pressed or v > 0.0:                                 # tone fades in under the content; the pressed tone is immediate
            tone = QColor(T.PRESSED if self._pressed else T.HOVER)
            tone.setAlphaF(1.0 if self._pressed else 0.55 * v)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tone)
            p.drawRoundedRect(r, T.R_CARD, T.R_CARD)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(T.EDGE), 1.0))                          # visible resting edge (about 2:1 against the page in both themes), also while pressed
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), T.R_CARD, T.R_CARD)
        if v > 0.0 and not self._pressed:                            # the edge strengthens while hovered
            edge = QColor(T.OUTLINE_STRONG)
            edge.setAlphaF(0.8 * v)
            p.setPen(QPen(edge, 1.0))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), T.R_CARD, T.R_CARD)
        self._paint_progress(p, r)
        if self.hasFocus():                                          # keyboard focus (WCAG 2.4.7): 2 px ring in the margin around the content, >= 3:1 against the card and the page
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T.FOCUS), 2.0))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), T.R_CARD, T.R_CARD)
        p.end()

    def _paint_progress(self, p: QPainter, r: QRectF) -> None:
        """A 2 px line along the bottom edge: a quiet track and the accent fill (green when watched). The words above carry the same information."""
        clip = QPainterPath()
        clip.addRoundedRect(r.adjusted(1, 1, -1, -1), max(T.R_CARD - 1, 1), max(T.R_CARD - 1, 1))
        p.save()
        p.setClipPath(clip)
        p.setPen(Qt.PenStyle.NoPen)
        y = r.bottom() - 3
        p.setBrush(QColor(T.TRACK))
        p.drawRect(QRectF(r.left() + 1, y, r.width() - 2, 2))
        if self.fraction > 0:
            p.setBrush(QColor(T.SUCCESS if self.watched else T.ACCENT))
            p.drawRect(QRectF(r.left() + 1, y, (r.width() - 2) * self.fraction, 2))
        p.restore()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.item)
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        a = m.addAction(tr("Remove from this list", "Home"))
        if m.exec(e.globalPos()) is a:
            self.removeRequested.emit(self.item["infohash"])


class HomeScreen(QWidget):
    COLUMN_MAX = 932                                    # 4 cards of 212 px + 3 gaps + the 2 x 24 px margins: hero, heading rule and card grid share their edges
    openRequested = pyqtSignal(str, str)     # source, title
    settingsRequested = pyqtSignal()
    helpRequested = pyqtSignal()
    removeRecent = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        logo = label("")
        logo.setPixmap(brand.symbol_pixmap(28, T.TEXT, T.ACCENT))
        name = brand_wordmark()
        help_btn = icon_button("help", tr("Help", "Home"), T.TEXT2, 22)
        help_btn.clicked.connect(self.helpRequested)
        set_btn = icon_button("settings", tr("Settings", "Home"), T.TEXT2, 22)
        set_btn.clicked.connect(self.settingsRequested)
        top = QHBoxLayout()
        top.setContentsMargins(T.S6, 20, T.S6, 0)
        top.setSpacing(T.S2)
        top.addWidget(logo)
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(help_btn)
        top.addWidget(set_btn)

        self.drop = DropZone()
        self.drop.sourceChosen.connect(lambda src: self.openRequested.emit(src, ""))
        self.recent_title = SectionHead(tr("Continue watching", "Home"))
        self.recent_host = QWidget()
        self.flow = FlowLayout(self.recent_host, T.S3)
        self.empty = label(tr("Videos you open will appear here, so you can pick up where you left off.", "Home"), "emptyhint", wrap=True)
        self.empty.setMaximumWidth(560)                                   # a readable measure; set in the serif like the heading above it

        col = QVBoxLayout()                                              # rhythm by relationship: a large gap between the hero and the section, a smaller one below the heading
        col.setSpacing(0)
        col.setContentsMargins(T.S6, T.S6, T.S6, T.S6)
        col.addWidget(self.drop)
        col.addSpacing(T.GAP_SECTION)
        col.addWidget(self.recent_title)
        col.addSpacing(T.GAP_GROUP)
        col.addWidget(self.recent_host)
        col.addWidget(self.empty)
        col.addStretch(1)
        self._col = col
        holder = QWidget()
        holder.setMaximumWidth(self.COLUMN_MAX)                          # a balanced, centred column; text inside it is left-aligned
        holder.setLayout(col)
        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(holder, 100)
        center.addStretch(1)
        inner = QWidget()
        inner.setLayout(center)
        scroll = QScrollArea()
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)     # no invisible Tab stop: the controls inside stay focusable and Qt scrolls a focused child into view
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(scroll, 1)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # the space above the hero grows gently with the window height, so a tall window looks composed rather than top-heavy (24 px up to 64 px)
        self._col.setContentsMargins(T.S6, T.S6 + max(0, min(40, (self.height() - 600) // 10)), T.S6, T.S6)

    def set_recent(self, items: list[dict]) -> None:
        while self.flow.count():
            it = self.flow.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for it in items[:12]:
            c = RecentCard(it)
            c.clicked.connect(lambda item: self.openRequested.emit(item.get("source", ""), item.get("title", "")))
            c.removeRequested.connect(self.removeRecent)
            self.flow.addWidget(c)
        has = bool(items)
        self.empty.setVisible(not has)
        self.recent_host.setVisible(has)
        self.recent_host.updateGeometry()
