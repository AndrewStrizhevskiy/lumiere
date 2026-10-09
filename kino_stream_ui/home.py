# SPDX-License-Identifier: GPL-3.0-or-later
"""Home screen: one obvious thing to do (open a video), recent items, readiness. Plus the status strip shared by all screens."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMenu, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import theme as T
from .icons import icon, pixmap
from .messages import tr
from .widgets import AnimatedBar, Dot, FlowLayout, button, card, fmt_bytes, fmt_speed, fmt_time, icon_button, label


def looks_like_magnet(s: str) -> bool:
    s = s.strip()
    return s.lower().startswith("magnet:?") and "xt=urn:btih:" in s.lower()


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
        self.setMinimumHeight(230)
        ic = label("")
        ic.setPixmap(pixmap("movie", T.ACCENT, 44, 2.0))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = label(tr("Watch while it downloads", "Home"), "hero", align=Qt.AlignmentFlag.AlignCenter)
        sub = label(tr("Drop a .torrent file here, or choose one", "Home"), "lead", align=Qt.AlignmentFlag.AlignCenter)
        self.open_btn = button(tr("Open torrent file", "Home"), "primary", "folder-open", name=tr("Open torrent file", "Home"))
        self.open_btn.clicked.connect(self.choose_file)
        self.magnet = QLineEdit()
        self.magnet.setPlaceholderText(tr("Paste a magnet link", "Home"))
        self.magnet.setAccessibleName(tr("Magnet link", "Home"))
        self.magnet.setMinimumWidth(260)
        self.magnet.returnPressed.connect(self.submit_magnet)
        self.paste_btn = icon_button("paste", tr("Paste from clipboard", "Home"))
        self.paste_btn.clicked.connect(self.paste)
        self.play_btn = button(tr("Play", "Home"), "", "play", name=tr("Play magnet link", "Home"))
        self.play_btn.clicked.connect(self.submit_magnet)
        self.error = label("", "caption", align=Qt.AlignmentFlag.AlignCenter)
        self.error.setStyleSheet(f"color:{T.DANGER};")
        self.error.hide()
        row = QHBoxLayout()
        row.setSpacing(T.S2)
        row.addStretch(1)
        row.addWidget(self.open_btn)
        row.addSpacing(T.S3)
        row.addWidget(self.magnet, 1)
        row.addWidget(self.paste_btn)
        row.addWidget(self.play_btn)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S8, T.S6, T.S8, T.S6)
        lay.setSpacing(T.S2)
        for w in (ic, title, sub):
            lay.addWidget(w)
        lay.addSpacing(T.S3)
        lay.addLayout(row)
        lay.addWidget(self.error)
        self.setTabOrder(self.open_btn, self.magnet)

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
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor(T.ELEVATED if self._hot else T.SURFACE))
        pen = QPen(QColor(T.ACCENT if self._hot else T.OUTLINE), 1.5, Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.drawRoundedRect(r, 14, 14)


class RecentCard(QFrame):
    clicked = pyqtSignal(dict)
    removeRequested = pyqtSignal(str)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item = item
        self.setProperty("card", "true")
        self.setFixedSize(212, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        title = item.get("title") or "Untitled"
        self.setAccessibleName(tr("Open %1", "Home").replace("%1", title))
        initials = "".join(w[0] for w in title.replace(".", " ").split()[:2]).upper() or "?"
        art = label(initials, align=Qt.AlignmentFlag.AlignCenter)
        art.setStyleSheet(f"background:{T.ELEVATED}; border-top-left-radius:{T.R_CARD}px; border-top-right-radius:{T.R_CARD}px; color:{T.TEXT3}; font-size:24px; font-weight:600;")
        art.setFixedHeight(72)
        name = label(title, "")
        name.setStyleSheet("font-weight:600;")
        name.setMaximumWidth(190)
        name.setText(name.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, 190))
        pos, dur = float(item.get("position_s") or 0), float(item.get("duration_s") or 0)
        sub = tr("Watched", "Home") if item.get("watched") else (tr("Resume at %1", "Home").replace("%1", fmt_time(pos)) if pos > 5 else tr("Not started", "Home"))
        subl = label(sub, "secondary")
        bar = AnimatedBar(T.SUCCESS if item.get("watched") else T.ACCENT, T.TRACK, 4)
        bar.setValue(1.0 if item.get("watched") else (pos / dur if dur else 0), False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, T.S3)
        lay.setSpacing(T.S1)
        lay.addWidget(art)
        body = QVBoxLayout()
        body.setContentsMargins(T.S3, T.S2, T.S3, 0)
        body.setSpacing(T.S1)
        body.addWidget(name)
        body.addWidget(subl)
        body.addWidget(bar)
        lay.addLayout(body)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.item)

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

    def enterEvent(self, e):
        self.setStyleSheet(f"QFrame {{ background:{T.ELEVATED}; border-radius:{T.R_CARD}px; }}")

    def leaveEvent(self, e):
        self.setStyleSheet("")


class HomeScreen(QWidget):
    openRequested = pyqtSignal(str, str)     # source, title
    settingsRequested = pyqtSignal()
    helpRequested = pyqtSignal()
    removeRecent = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        logo = label("")
        logo.setPixmap(pixmap("movie", T.ACCENT, 26, 2.0))
        name = label("Kino Stream", "title")
        help_btn = icon_button("help", tr("Help", "Home"), T.TEXT2, 22)
        help_btn.clicked.connect(self.helpRequested)
        set_btn = icon_button("settings", tr("Settings", "Home"), T.TEXT2, 22)
        set_btn.clicked.connect(self.settingsRequested)
        top = QHBoxLayout()
        top.setContentsMargins(T.S6, T.S4, T.S4, 0)
        top.setSpacing(T.S2)
        top.addWidget(logo)
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(help_btn)
        top.addWidget(set_btn)

        self.drop = DropZone()
        self.drop.sourceChosen.connect(lambda src: self.openRequested.emit(src, ""))
        self.recent_title = label(tr("Continue watching", "Home"), "section")
        self.recent_host = QWidget()
        self.flow = FlowLayout(self.recent_host, T.S3)
        self.empty = label(tr("Videos you open will appear here, so you can pick up where you left off.", "Home"), "caption")

        col = QVBoxLayout()
        col.setSpacing(T.S4)
        col.setContentsMargins(T.S6, T.S6, T.S6, T.S6)
        col.addWidget(self.drop)
        col.addSpacing(T.S2)
        col.addWidget(self.recent_title)
        col.addWidget(self.recent_host)
        col.addWidget(self.empty)
        col.addStretch(1)
        holder = QWidget()
        holder.setMaximumWidth(860)
        holder.setLayout(col)
        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(holder, 100)
        center.addStretch(1)
        inner = QWidget()
        inner.setLayout(center)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(scroll, 1)

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
