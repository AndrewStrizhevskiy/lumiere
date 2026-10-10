# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility measurements on REAL rendered widgets (offscreen), in both themes.

Criteria applied (WCAG 2.1/2.2): 1.4.3 text contrast 4.5:1; 1.4.11 non-text contrast 3:1 for UI component boundaries and states, which for a focus
indicator means 3:1 against EVERY adjacent colour (the page outside the ring and the fill inside it); 2.4.7 Focus Visible (every keyboard-focusable control must
change visibly when focused); 2.4.13 Focus Appearance (AAA, targeted where reachable: >= 2 px thick, >= 3:1 between focused and unfocused). Disabled controls are
exempt from contrast rules but are checked for legibility and for being distinguishable from enabled ones. Hover is not a WCAG contrast requirement; it is checked
for being perceivable. The playback seek bar is checked for a monotonic luminance order (played > downloaded > remaining) so it does not rely on hue."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
os.environ["LUMIERE_REDUCE_MOTION"] = "1"
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])
from lumiere_ui import theme as T  # noqa: E402
from tests.test_theme import contrast  # noqa: E402


def lum(c: QColor) -> float:
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c.red() / 255) + 0.7152 * f(c.green() / 255) + 0.0722 * f(c.blue() / 255)


def ratio(a: QColor, b: QColor) -> float:
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def pixel(img, x, y) -> QColor:
    return QColor(img.pixel(x, y))


class ThemedCase(unittest.TestCase):
    theme = "dark"

    def setUp(self):
        T.apply(self.theme)
        app.setStyleSheet(T.qss())
        app.setPalette(T.palette())

    def tearDown(self):
        T.apply("dark")
        app.setStyleSheet(T.qss())


class Tokens(unittest.TestCase):
    def test_hover_and_pressed_are_perceivable_and_disabled_is_legible_but_different(self):
        for name, t in T.THEMES.items():
            self.assertGreaterEqual(contrast(t["ELEVATED"], t["HOVER"]), 1.12, f"{name}: hover barely differs from rest")
            self.assertGreaterEqual(contrast(t["HOVER"], t["PRESSED"]), 1.04, f"{name}: pressed barely differs from hover")
            self.assertGreaterEqual(contrast(t["TEXT3"], t["SURFACE"]), 4.5, f"{name}: disabled text legibility")
            self.assertGreaterEqual(contrast(t["TEXT"], t["SURFACE"]) / contrast(t["TEXT3"], t["SURFACE"]), 1.8, f"{name}: disabled must look different from enabled")
            self.assertGreaterEqual(contrast(t["ACCENT_HOVER"], t["ACCENT_FILL"]), 1.1, f"{name}: primary hover")

    def test_focus_ring_colours_against_every_adjacent_colour(self):
        for name, t in T.THEMES.items():
            for surface in ("BG", "SURFACE", "ELEVATED"):
                self.assertGreaterEqual(contrast(t["FOCUS"], t[surface]), 3.0, f"{name}: ring vs {surface}")
            self.assertGreaterEqual(contrast(t["FOCUS_INNER"], t["ACCENT_FILL"]), 3.0, f"{name}: inner band vs burgundy fill")

    def test_seek_bar_layers_are_ordered_by_luminance_not_only_hue(self):
        d = T.THEMES["dark"]                      # the playback screen always uses the dark set
        self.assertGreaterEqual(contrast(d["PLAYED"], d["AVAILABLE"]), 3.0)
        self.assertGreaterEqual(contrast(d["AVAILABLE"], d["TRACK"]), 2.0)
        self.assertGreaterEqual(contrast(d["PLAYED"], d["TRACK"]), 5.0)


class RenderedFocus(ThemedCase):
    def make(self):
        from lumiere_ui.widgets import button
        w = QWidget()
        w.setObjectName("root")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(30, 30, 30, 30)
        b, other = button("Open torrent file", "primary"), button("Play", "", name="Play")
        lay.addWidget(b)
        lay.addWidget(other)
        w.resize(300, 160)
        w.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(w.close)
        return w, b, other

    def measure(self):
        w, b, other = self.make()
        w.activateWindow()
        other.setFocus()
        app.processEvents()
        unfocused = w.grab().toImage()
        b.setFocus()
        app.processEvents()
        self.assertTrue(b.hasFocus())
        focused = w.grab().toImage()
        cx, y0 = b.x() + 12, b.y()
        page, fill = pixel(focused, cx, y0 - 4), pixel(focused, cx, y0 + 9)
        outer, inner = pixel(focused, cx, y0 + 1), pixel(focused, cx, y0 + 2)      # the crisp rows of the 2 px outer band and the 1.5 px inner band
        return page, fill, outer, inner, pixel(unfocused, cx, y0 + 2)

    def check(self):
        page, fill, outer, inner, unfocused_edge = self.measure()
        self.assertGreaterEqual(ratio(outer, page), 3.0, f"{self.theme}: outer band vs page = {ratio(outer, page):.2f}")
        self.assertGreaterEqual(ratio(inner, fill), 3.0, f"{self.theme}: inner band vs fill = {ratio(inner, fill):.2f}")
        self.assertGreaterEqual(ratio(inner, unfocused_edge), 3.0, f"{self.theme}: focused vs unfocused state = {ratio(inner, unfocused_edge):.2f}")

    def test_primary_button_focus_is_visible_against_page_and_fill(self):
        self.check()


class RenderedFocusLight(RenderedFocus):
    theme = "light"


class FocusSweep(ThemedCase):
    """2.4.7: every keyboard-focusable control on the Home and Settings screens must look different when focused."""

    def build(self):
        from lumiere.recent import RecentItems
        from lumiere.settings import Settings
        from lumiere_ui.bridge import EngineBridge
        from lumiere_ui.mainwindow import MainWindow
        tmp = Path(tempfile.mkdtemp())
        r = RecentItems(tmp / "recent.json")
        for h, t in (("a" * 40, "Sintel"), ("b" * 40, "Tears of Steel")):
            r.touch(h, t, "x.torrent", 100_000_000)
        win = MainWindow(EngineBridge(Settings(cache_root=str(tmp / "c"), tour_done=True), tmp / "state", r))
        win.resize(1100, 720)
        win.show()
        for _ in range(8):
            app.processEvents()
        self.addCleanup(win.close)
        return win

    def sweep(self, win, screen):
        win.go(screen)
        for _ in range(8):
            app.processEvents()
        win.activateWindow()
        cur = win.stack.currentWidget()
        seen = []
        for wd in cur.findChildren(QWidget):
            if wd.isVisible() and wd.focusPolicy().value & 1 and wd.width() > 8 and wd.height() > 8 and wd.window() is win:
                wd.clearFocus()
                app.processEvents()
                before = wd.grab().toImage()
                wd.setFocus()
                app.processEvents()
                if not wd.hasFocus():
                    continue
                after = wd.grab().toImage()
                diff = sum(1 for x in range(0, after.width(), 1) for y in range(0, after.height(), 1) if pixel(before, x, y) != pixel(after, x, y))
                seen.append((type(wd).__name__, wd.accessibleName() or wd.objectName() or wd.toolTip(), diff))
                self.assertGreater(diff, 24, f"{self.theme}: {type(wd).__name__} '{wd.accessibleName()}' shows no visible focus (changed pixels: {diff})")
        return seen

    def test_home_controls_show_focus(self):
        seen = self.sweep(self.build(), 0)
        self.assertTrue(any(n == "RecentCard" for n, _, _ in seen), "the recent-video cards must be part of the sweep")
        self.assertGreaterEqual(len(seen), 6)

    def test_settings_controls_show_focus(self):
        seen = self.sweep(self.build(), 2)
        self.assertGreaterEqual(len(seen), 6)


class FocusSweepLight(FocusSweep):
    theme = "light"


class SeekBarRendering(ThemedCase):
    def test_played_downloaded_and_remaining_are_three_distinct_luminance_steps(self):
        from lumiere_ui.player import SeekBar
        bar = SeekBar()
        bar.resize(400, 28)
        bar.set_bins([1.0] * 10 + [0.0] * 10)       # first half downloaded
        bar.value = 0.25                              # first quarter played
        bar.duration = 100.0
        bar.show()
        app.processEvents()
        img = bar.grab().toImage()
        y = bar.height() // 2 + 1                     # just below the handle's centre line, inside the 6 px track
        played, downloaded, remaining = pixel(img, 8 + int(384 * 0.12), y), pixel(img, 8 + int(384 * 0.38), y), pixel(img, 8 + int(384 * 0.80), y)
        self.assertGreater(lum(played), lum(downloaded) + 0.05)
        self.assertGreater(lum(downloaded), lum(remaining) + 0.03)
        self.assertGreaterEqual(ratio(played, downloaded), 3.0, f"played vs downloaded {ratio(played, downloaded):.2f}")
        self.assertGreaterEqual(ratio(downloaded, remaining), 2.0, f"downloaded vs remaining {ratio(downloaded, remaining):.2f}")


class SeekBarRenderingLight(SeekBarRendering):
    theme = "light"                                   # the player is always dark: the seek bar must not change with the app theme


if __name__ == "__main__":
    unittest.main()
