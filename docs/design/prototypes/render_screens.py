# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders the REAL current screens (offscreen, reduced motion, made-up sample titles) for the review package; changes nothing and persists nothing.
usage (repository root): PYTHONPATH=. python3 docs/design/prototypes/render_screens.py OUTPUT_DIR [BEFORE_DIR]
If BEFORE_DIR holds `before_<theme>_<size>.png` images (rendered earlier from the unchanged code), side-by-side `compare_*` images are written too."""
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

from PyQt6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from lumiere.recent import RecentItems  # noqa: E402
from lumiere.settings import Settings  # noqa: E402
from lumiere_ui import home, theme as T  # noqa: E402
from lumiere_ui.app import install_theme  # noqa: E402
from lumiere_ui.bridge import EngineBridge  # noqa: E402
from lumiere_ui.mainwindow import MainWindow  # noqa: E402

install_theme(app)
OUT = Path(sys.argv[1])
BEFORE = Path(sys.argv[2]) if len(sys.argv) > 2 else None
OUT.mkdir(parents=True, exist_ok=True)
SAMPLES = [("Some.Movie.2024.1080p.WEB-DL.x264-GROUP", 1810, 6000), ("Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p.BluRay.x264-GRP", 0, 0),
           ("千と千尋の神隠し.2001.1080p.BluRay.x264.mkv", 6200, 7500), ("Show.S01E02.720p.HDTV.x264", 610, 2700), ("IMG_2048.mov", 40, 95),
           ("Movie.Night.2024.2025.1080p.WEB-DL", 0, 0)]
LONG = [("The.Extraordinarily.Long.Title.Of.An.Independent.Film.That.Keeps.Going.And.Going.2019.2160p.UHD.BluRay.x265-GRP", 900, 6000),
        ("A" * 90 + ".mkv", 0, 0), ("Ñandú.y.el.Cóndor.en.la.Pampa.Austral.1987.1080p.WEB-DL.x264", 6000, 6100),
        ("Eine.sehr.lange.Geschichte.über.Donaudampfschifffahrtsgesellschaftskapitän.2011.1080p.WEB-DL.x264", 100, 6000)]
SIZES = {"720x520": (720, 520), "1040x700": (1040, 700), "1440x900": (1440, 900)}


def build(theme, w, h, samples=SAMPLES, settings=False, card_cls=None):
    T.apply(theme)
    app.setStyleSheet(T.qss())
    app.setPalette(T.palette())
    if card_cls:
        home.RecentCard = card_cls
    tmp = Path(tempfile.mkdtemp())
    r = RecentItems(tmp / "recent.json")
    for i, (n, pos, dur) in enumerate(samples):
        r.touch(f"{i:x}" * 40, n, "x.torrent", 3_000_000_000)
        r.update_position(f"{i:x}" * 40, pos, dur)
    win = MainWindow(EngineBridge(Settings(cache_root=str(tmp / "c"), tour_done=True), tmp / "s", r))
    win.resize(w, h)
    if settings:
        win.go(win.SETTINGS)
    win.show()
    for _ in range(10):
        app.processEvents()
    time.sleep(0.1)
    app.processEvents()
    return win


def save(win, name):
    win.grab().save(str(OUT / name))
    win.close()


original_card = home.RecentCard
for theme in ("dark", "light"):
    for tag, (w, h) in SIZES.items():
        save(build(theme, w, h), f"after_{theme}_{tag}.png")
    for tag, (w, h) in SIZES.items():
        save(build(theme, w, h, samples=[]), f"after_{theme}_empty_{tag}.png")
    save(build(theme, 1040, 700, settings=True), f"after_{theme}_settings_1040x700.png")
    save(build(theme, 720, 520, settings=True), f"after_{theme}_settings_720x520.png")
    for tag, (w, h) in SIZES.items():
        save(build(theme, w, h, samples=LONG + SAMPLES[:2]), f"after_{theme}_long_titles_{tag}.png")

    # card layout comparison: uniform cards vs one emphasised (wide) first card, 1040 px
    save(build(theme, 1040, 700, card_cls=original_card), f"cards_balanced_{theme}_1040x700.png")

    class WideCard(original_card):
        WIDTH = 212 * 2 + T.S3

    win = build(theme, 1040, 700, card_cls=None)
    home.RecentCard = WideCard
    win.home.set_recent(win.bridge.recent.items)
    # only the first card is wide: rebuild the others at the normal width
    from PyQt6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    items = win.bridge.recent.items
    while win.home.flow.count():
        win.home.flow.takeAt(0).widget().deleteLater()
    for i, it in enumerate(items):
        win.home.flow.addWidget((WideCard if i == 0 else original_card)(it))
    for _ in range(6):
        app.processEvents()
    save(win, f"cards_emphasised_{theme}_1040x700.png")
    home.RecentCard = original_card

    # states of one card (rest, hover, pressed, keyboard focus) and a disabled button
    from PyQt6.QtCore import Qt
    win = build(theme, 1040, 700)
    cards = win.home.findChildren(original_card)
    c = cards[0]
    shots = []
    c.clearFocus()
    shots.append(c.grab().toImage())
    c._hover.go(True)
    app.processEvents()
    shots.append(c.grab().toImage())
    c._hover.go(False)
    c._pressed = True
    c.update()
    shots.append(c.grab().toImage())
    c._pressed = False
    c.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    shots.append(c.grab().toImage())
    win.home.drop.play_btn.setEnabled(False)
    win.home.drop.open_btn.setEnabled(False)
    app.processEvents()
    shots.append(win.home.drop.grab().toImage())
    pad = 12
    sheet = QImage(sum(i.width() for i in shots[:4]) + pad * 5, max(shots[4].height(), shots[0].height()) * 2 + pad * 3, QImage.Format.Format_RGB32)
    sheet.fill(QColor(T.BG))
    p = QPainter(sheet)
    x = pad
    for i in shots[:4]:
        p.drawImage(x, pad, i)
        x += i.width() + pad
    p.drawImage(pad, shots[0].height() + 2 * pad, shots[4])
    p.end()
    sheet.save(str(OUT / f"states_{theme}.png"))
    win.close()

if BEFORE:
    for after in sorted(OUT.glob("after_*.png")):
        b_path = BEFORE / after.name.replace("after_", "before_", 1)
        if not b_path.exists():
            continue
        b, a = QImage(str(b_path)), QImage(str(after))
        gap, bar = 24, 34
        img = QImage(b.width() + a.width() + gap, max(a.height(), b.height()) + bar, QImage.Format.Format_RGB32)
        img.fill(QColor("#777777"))
        p = QPainter(img)
        p.setPen(QColor("white"))
        f = p.font()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.drawText(8, 22, "BEFORE (previous implementation)")
        p.drawText(b.width() + gap + 8, 22, "AFTER (implemented in the sandbox)")
        p.drawImage(0, bar, b)
        p.drawImage(b.width() + gap, bar, a)
        p.end()
        img.save(str(OUT / after.name.replace("after_", "compare_", 1)))
print("done", len(list(OUT.glob("*.png"))), "images")
