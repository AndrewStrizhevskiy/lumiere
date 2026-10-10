# SPDX-License-Identifier: GPL-3.0-or-later
# SUPERSEDED (kept for the record): this mock patched the pre-implementation UI. R1-R6 are now implemented; use docs/design/prototypes/render_screens.py. Not maintained.
"""PROPOSAL MOCK - not part of the application. Renders the real Home/Settings screens as they are today ("before") and with the refinements proposed in
docs/design/CRAFT_DIRECTION.md applied *in this process only* by monkeypatching ("after"). No file of lumiere / lumiere_ui is modified; nothing is persisted.
usage (from the repository root):  PYTHONPATH=. python3 docs/design/prototypes/craft_mock.py OUTPUT_DIR
Offscreen, reduced motion, made-up sample titles (not real data). The "after" images approximate the proposal; metrics are not final."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LUMIERE_REDUCE_MOTION"] = "1"
_d = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _d
os.environ["XDG_STATE_HOME"] = _d

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget  # noqa: E402

app = QApplication([])
from lumiere.recent import RecentItems  # noqa: E402
from lumiere.settings import Settings  # noqa: E402
from lumiere_ui import home, theme as T  # noqa: E402
from lumiere_ui.app import install_theme  # noqa: E402
from lumiere_ui.bridge import EngineBridge  # noqa: E402
from lumiere_ui.mainwindow import MainWindow  # noqa: E402
from lumiere_ui.widgets import AnimatedBar, fmt_time, label  # noqa: E402
from lumiere import titles  # noqa: E402

install_theme(app)
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
SAMPLES = [("Some.Movie.2024.1080p.WEB-DL.x264-GROUP", 1810, 6000), ("Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p.BluRay.x264-GRP", 0, 0),
           ("千と千尋の神隠し.2001.1080p.BluRay.x264.mkv", 6200, 7500), ("Show.S01E02.720p.HDTV.x264", 610, 2700), ("IMG_2048.mov", 40, 95),
           ("Movie.Night.2024.2025.1080p.WEB-DL", 0, 0)]
SIZES = {"1040x700": (1040, 700), "720x520": (720, 520), "1440x900": (1440, 900)}


def build(theme: str, w: int, h: int, items: bool = True, settings: bool = False):
    T.apply(theme)
    app.setStyleSheet(T.qss())
    app.setPalette(T.palette())
    tmp = Path(tempfile.mkdtemp())
    r = RecentItems(tmp / "recent.json")
    for i, (n, pos, dur) in enumerate(SAMPLES if items else []):
        r.touch(f"{i:x}" * 40, n, "x.torrent", 3_000_000_000)
        r.update_position(f"{i:x}" * 40, pos, dur)
    win = MainWindow(EngineBridge(Settings(cache_root=str(tmp / "c"), tour_done=True), tmp / "s", r))
    win.resize(w, h)
    if settings:
        win.go(win.SETTINGS)
    win.show()
    if PROPOSED:
        apply_proposal(win)
    for _ in range(10):
        app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    return win


# ------------------------------------------------------------------------------------------------------------------ the proposal (mock)
PROPOSED = False
FEATURE_W = 212 * 2 + T.S3


class ProposedCard(home.RecentCard):
    """Title card: no grey art block; serif title on the card, year and progress in tabular figures, progress as a 2 px line on the bottom edge."""
    def __init__(self, item, parent=None, feature=False):
        QFrame.__init__(self, parent)
        self.item = item
        self.setProperty("card", "true")
        self.setFixedSize(FEATURE_W if feature else 212, 150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        d = titles.for_recent_item(item)
        self.display = d
        title = d.text or "Untitled"
        self.setAccessibleName("Open " + title)
        self.setToolTip(self._tooltip(d, item))
        pos, dur = float(item.get("position_s") or 0), float(item.get("duration_s") or 0)
        progress = "Watched" if item.get("watched") else (f"Resume at {fmt_time(pos)}" if pos > 5 else "Not started")
        year = QLabel(str(d.year) if d.year else "")
        year.setStyleSheet(f"color:{T.TEXT3}; font-size:{T.FS_CAPTION}px; letter-spacing:1px; background:transparent;")
        name = QLabel(title)
        name.setWordWrap(True)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setStyleSheet(f"font-family:{T._serif_css()}; font-size:{24 if feature else 19}px; font-weight:500; background:transparent;")
        name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        prog = QLabel(progress)
        prog.setStyleSheet(f"color:{T.TEXT2}; font-size:{T.FS_SMALL}px; background:transparent;")
        f = prog.font()
        f.setFeature(QFont.Tag("tnum"), 1) if hasattr(f, "setFeature") else None       # tabular figures where the font has them
        prog.setFont(f)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S4, T.S3, T.S4, T.S4)
        lay.setSpacing(T.S1)
        lay.addWidget(year)
        lay.addWidget(name, 1)
        lay.addWidget(prog)
        self._frac = 1.0 if item.get("watched") else (pos / dur if dur else 0.0)
        self._hover = home.HoverFade(self)
        self._pressed = False

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._frac > 0:
            p = QPainter(self)
            r = QRectF(self.rect())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.TRACK))
            p.drawRect(QRectF(r.left() + T.R_CARD / 2, r.bottom() - 3, r.width() - T.R_CARD, 2))
            p.setBrush(QColor(T.SUCCESS if self.item.get("watched") else T.ACCENT))
            p.drawRect(QRectF(r.left() + T.R_CARD / 2, r.bottom() - 3, (r.width() - T.R_CARD) * self._frac, 2))
            p.end()


def _drop_paint(self, e):
    p = QPainter(self)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(self.rect())
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(T.ELEVATED if self._hot else T.SURFACE))
    p.drawRoundedRect(r, T.R_CARD, T.R_CARD)
    pen = QPen(QColor(T.ACCENT if self._hot else T.OUTLINE_STRONG), 2.0)          # two crop marks only (top-left, bottom-right): asymmetric, still the film-gate frame
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    m, L = 16.0, 20.0
    x0, y0, x1, y1 = r.left() + m, r.top() + m, r.right() - m, r.bottom() - m
    for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y1, -1, -1)):
        p.drawLine(QPointF(cx, cy), QPointF(cx + dx * L, cy))
        p.drawLine(QPointF(cx, cy), QPointF(cx, cy + dy * L))
    p.end()


def apply_proposal(win: MainWindow) -> None:
    hs = win.home
    dz = hs.drop
    lay = dz.layout()
    for i in range(lay.count()):                                                  # icon hidden, headline and lead left-aligned, serif display size
        w = lay.itemAt(i).widget()
        if isinstance(w, QLabel):
            if w.pixmap() is not None and not w.pixmap().isNull():
                w.hide()
            else:
                w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    lay.setContentsMargins(T.S8 + T.S2, T.S8, T.S8, T.S8 + T.S2)
    row = [lay.itemAt(i).layout() for i in range(lay.count()) if lay.itemAt(i).layout() is not None][0]
    row.takeAt(row.count() - 1)                                                   # trailing stretch
    row.takeAt(0)                                                                 # leading stretch: the action row now starts at the text edge
    row.addStretch(0)
    for w in dz.findChildren(QLabel):
        if w.property("role") == "hero":
            w.setStyleSheet(f"font-size:{T.FS_HERO + 12}px;")
    dz.paintEvent = lambda e, s=dz: _drop_paint(s, e)
    dz.update()
    # section heading: serif with a hairline rule to the edge
    head = QWidget()
    hl = QHBoxLayout(head)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.setSpacing(T.S3)
    t = QLabel(hs.recent_title.text())
    t.setStyleSheet(f"font-family:{T._serif_css()}; font-size:{T.FS_LEAD + 4}px; font-weight:500;")
    rule = QFrame()
    rule.setFixedHeight(1)
    rule.setStyleSheet(f"background:{T.HAIRLINE};")
    hl.addWidget(t)
    hl.addWidget(rule, 1)
    col = hs.recent_title.parentWidget().layout() if False else None
    holder = hs.drop.parentWidget()
    col = holder.layout()
    col.replaceWidget(hs.recent_title, head)
    hs.recent_title.hide()
    col.setContentsMargins(T.S6, T.S6, T.S6, T.S6)
    col.insertSpacing(2, T.S6)                                                    # more air above the section than between its parts
    # asymmetric column: the content hugs the logo edge, the free space goes to the right
    center = holder.parentWidget().layout()
    center.setStretch(0, 1)
    center.setStretch(2, 3)
    holder.setMaximumWidth(900)
    # cards: first (most recent) is the wide feature card
    cards = hs.recent_host.findChildren(home.RecentCard)
    items = [c.item for c in sorted(cards, key=lambda c: hs.flow.indexOf(c))]
    while hs.flow.count():
        it = hs.flow.takeAt(0)
        it.widget().deleteLater()
    for i, item in enumerate(items):
        hs.flow.addWidget(ProposedCard(item, feature=(i == 0)))
    for w in win.settings_screen.findChildren(QLabel):                            # settings: row titles in the serif
        if w.styleSheet() == "font-weight:600;":
            w.setStyleSheet(f"font-family:{T._serif_css()}; font-size:{T.FS_LEAD + 2}px; font-weight:500;")


def apply_global_proposal() -> None:
    T.R_CARD = 4                                                                  # printed-card corners instead of app-like rounding
    T.R_CTRL = 4


def render_all(prefix: str) -> None:
    for theme in ("dark", "light"):
        for tag, (w, h) in SIZES.items():
            win = build(theme, w, h)
            win.grab().save(str(OUT / f"{prefix}_{theme}_{tag}.png"))
            win.close()
        win = build(theme, 1040, 700, items=False)
        win.grab().save(str(OUT / f"{prefix}_{theme}_empty_1040x700.png"))
        win.close()
        win = build(theme, 1040, 700, settings=True)
        win.grab().save(str(OUT / f"{prefix}_{theme}_settings_1040x700.png"))
        win.close()


render_all("before")
PROPOSED = True
apply_global_proposal()
render_all("after")


def side_by_side() -> None:
    for after in sorted(OUT.glob("after_*.png")):
        b = QImage(str(OUT / after.name.replace("after_", "before_", 1)))
        a = QImage(str(after))
        gap, bar = 24, 34
        img = QImage(b.width() + a.width() + gap, max(a.height(), b.height()) + bar, QImage.Format.Format_RGB32)
        img.fill(QColor("#777777"))
        p = QPainter(img)
        p.setPen(QColor("white"))
        f = p.font()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.drawText(8, 22, "BEFORE: the current implementation")
        p.drawText(b.width() + gap + 8, 22, "AFTER: proposed refinement (mock, not implemented)")
        p.drawImage(0, bar, b)
        p.drawImage(b.width() + gap, bar, a)
        p.end()
        img.save(str(OUT / after.name.replace("after_", "compare_", 1)))


side_by_side()
print("done", len(list(OUT.glob("*.png"))), "images")
