# SPDX-License-Identifier: GPL-3.0-or-later
"""R1-R6 of docs/design/CRAFT_DIRECTION.md: composition at three window sizes, title wrapping/eliding, resting edge, radius system, rhythm, serif roles.
Offscreen Qt; reduced motion forced; both themes."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PyQt6.QtGui import QFont  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from lumiere.recent import RecentItems  # noqa: E402
from lumiere.settings import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])
from lumiere_ui import theme as T  # noqa: E402
from lumiere_ui.app import install_theme  # noqa: E402

install_theme(app)
from lumiere_ui import widgets as W  # noqa: E402
from lumiere_ui.bridge import EngineBridge  # noqa: E402
from lumiere_ui.home import RecentCard, wrap_elide  # noqa: E402
from lumiere_ui.mainwindow import MainWindow  # noqa: E402

LONG = ["The.Extraordinarily.Long.Title.Of.An.Independent.Film.That.Keeps.Going.And.Going.2019.2160p.UHD.BluRay.x265-GRP",
        "A" * 90 + ".mkv", "Eine.sehr.lange.Geschichte.über.Donaudampfschifffahrtsgesellschaftskapitän.2011.1080p.WEB-DL.x264",
        "千と千尋の神隠し千と千尋の神隠し千と千尋の神隠し千と千尋の神隠し.2001.1080p.BluRay.x264.mkv", "x"]


def lum(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def item(i, title, pos=0.0, dur=0.0):
    return {"infohash": f"{i:x}" * 40, "title": title, "source": "x.torrent", "size": 1, "position_s": pos, "duration_s": dur, "watched": False, "last_opened": 1_700_000_000.0 - i}


class WrapElide(unittest.TestCase):
    font = QFont("DejaVu Serif", 12)

    def test_short_text_is_one_unchanged_line(self):
        self.assertEqual(wrap_elide("Some Movie", self.font, 400), ["Some Movie"])

    def test_empty_text_gives_no_lines(self):
        self.assertEqual(wrap_elide("", self.font, 100), [])
        self.assertEqual(wrap_elide("   ", self.font, 100), [])

    def test_never_more_than_the_allowed_lines_and_never_wider_than_the_width(self):
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font)
        for text in LONG:
            for width in (60, 120, 176, 300):
                with self.subTest(text=text[:20], width=width):
                    lines = wrap_elide(text, self.font, width, 2)
                    self.assertLessEqual(len(lines), 2)
                    for line in lines:
                        self.assertLessEqual(fm.horizontalAdvance(line), width + 1)

    def test_an_overlong_text_ends_with_an_ellipsis_and_a_fitting_one_does_not(self):
        lines = wrap_elide(LONG[0], self.font, 176, 2)
        self.assertTrue(lines[-1].endswith("…"), lines)
        self.assertFalse(wrap_elide("Two short words", self.font, 400)[-1].endswith("…"))

    def test_elision_cuts_between_words_when_it_can(self):
        text = "Eine sehr lange Geschichte über Donaudampfschifffahrtsgesellschaftskapitän und mehr"
        lines = wrap_elide(text, self.font, 176, 2)
        last = lines[-1]
        self.assertTrue(last.endswith("…"), lines)
        kept = last[:-1].rstrip().split(" ")
        self.assertTrue(all(w in text.split(" ") for w in kept), f"a word was cut in the middle: {lines}")

    def test_a_first_word_that_is_itself_too_long_is_cut_by_character(self):
        lines = wrap_elide("A" * 80, self.font, 120, 2)
        self.assertTrue(lines[-1].endswith("…"))

    def test_the_start_of_the_text_is_preserved(self):
        self.assertTrue(wrap_elide(LONG[2].replace(".", " "), self.font, 176, 2)[0].startswith("Eine sehr"))


class Themed(unittest.TestCase):
    theme = "dark"

    def setUp(self):
        p = mock.patch.dict(os.environ, {"LUMIERE_REDUCE_MOTION": "1"})
        p.start()
        self.addCleanup(p.stop)
        T.apply(self.theme)
        app.setStyleSheet(T.qss())
        app.setPalette(T.palette())
        self.addCleanup(lambda: (T.apply("dark"), app.setStyleSheet(T.qss())))

    def window(self, w, h, items=(), settings=False):
        tmp = Path(tempfile.mkdtemp())
        r = RecentItems(tmp / "recent.json")
        for i, (t, pos, dur) in enumerate(items):
            r.touch(f"{i:x}" * 40, t, "x.torrent", 5)
            r.update_position(f"{i:x}" * 40, pos, dur)
        win = MainWindow(EngineBridge(Settings(cache_root=str(tmp / "c"), tour_done=True), tmp / "s", r))
        win.resize(w, h)
        if settings:
            win.go(win.SETTINGS)
        win.show()
        for _ in range(8):
            app.processEvents()
        QTest.qWait(30)
        self.addCleanup(win.close)
        return win


class Composition(Themed):
    SAMPLES = [("Some.Movie.2024.1080p.WEB-DL.x264-GROUP", 300, 6000), ("IMG_2048.mov", 0, 0), ("Show.S01E02.720p.HDTV.x264", 100, 2000), ("千と千尋の神隠し.2001.1080p", 0, 0)]

    def geometry(self, win, widget):
        return widget.mapTo(win.home, widget.rect().topLeft()), widget.size()

    def test_the_column_is_balanced_and_text_inside_it_is_left_aligned_at_three_sizes(self):
        for w, h in ((720, 520), (1040, 700), (1440, 900)):
            with self.subTest(size=(w, h)):
                win = self.window(w, h, self.SAMPLES)
                dz = win.home.drop
                left = dz.mapTo(win.home, dz.rect().topLeft()).x()
                right = win.home.width() - (left + dz.width())
                self.assertLessEqual(abs(left - right), 20, f"column not balanced: left {left}, right {right}")      # the scroll bar accounts for a few pixels
                self.assertLessEqual(dz.width(), win.home.COLUMN_MAX)
                title = [x for x in dz.findChildren(QLabel) if x.property("role") == "hero"][0]
                lead = [x for x in dz.findChildren(QLabel) if x.property("role") == "lead"][0]
                xs = {title.mapTo(dz, title.rect().topLeft()).x(), lead.mapTo(dz, lead.rect().topLeft()).x(), dz.open_btn.mapTo(dz, dz.open_btn.rect().topLeft()).x()}
                self.assertEqual(len(xs), 1, f"text and action row do not share a left edge: {xs}")
                self.assertTrue(title.alignment() & Qt.AlignmentFlag.AlignLeft)

    def test_every_hero_control_stays_inside_the_hero_at_the_smallest_size(self):
        win = self.window(720, 520, self.SAMPLES)
        dz = win.home.drop
        for wdg in (dz.open_btn, dz.magnet, dz.paste_btn, dz.play_btn):
            r = wdg.mapTo(dz, wdg.rect().topLeft())
            self.assertGreaterEqual(r.x(), 0)
            self.assertLessEqual(r.x() + wdg.width(), dz.width(), f"{wdg} overflows the hero")

    def test_the_space_above_the_hero_grows_gently_with_the_window_height(self):
        small = self.window(1040, 520, self.SAMPLES).home.drop
        big = self.window(1040, 900, self.SAMPLES).home.drop
        y_small = small.mapTo(small.window(), small.rect().topLeft()).y()
        y_big = big.mapTo(big.window(), big.rect().topLeft()).y()
        self.assertGreater(y_big, y_small)
        self.assertLessEqual(y_big - y_small, 48)

    def test_rhythm_follows_the_hierarchy(self):
        self.assertGreater(T.GAP_SECTION, T.GAP_GROUP)
        self.assertGreater(T.GAP_GROUP, T.GAP_TIGHT)
        win = self.window(1040, 700, self.SAMPLES)
        h = win.home
        dz_bottom = h.drop.mapTo(h, h.drop.rect().bottomLeft()).y() + 1
        head_top = h.recent_title.mapTo(h, h.recent_title.rect().topLeft()).y()
        head_bottom = h.recent_title.mapTo(h, h.recent_title.rect().bottomLeft()).y() + 1
        host_top = h.recent_host.mapTo(h, h.recent_host.rect().topLeft()).y()
        self.assertEqual(head_top - dz_bottom, T.GAP_SECTION)
        self.assertEqual(host_top - head_bottom, T.GAP_GROUP)

    def test_section_heading_is_serif_with_a_rule_that_reaches_the_column_edge(self):
        for w in (720, 1040):
            win = self.window(w, 600, self.SAMPLES)
            head = win.home.recent_title
            self.assertEqual(head.title.property("role"), "sectionhead")
            self.assertIn("sectionhead", T.qss())
            rule = [c for c in head.findChildren(W.QFrame) if c.property("role") == "divider"][0]
            self.assertGreater(rule.width(), 100)
            right_edge = rule.mapTo(win.home, rule.rect().topRight()).x()
            dz = win.home.drop
            self.assertAlmostEqual(right_edge, dz.mapTo(win.home, dz.rect().topRight()).x(), delta=2)

    def test_empty_state_is_composed_and_the_hint_is_visible_in_the_serif_and_aligned(self):
        for w, h in ((720, 520), (1440, 900)):
            win = self.window(w, h, ())
            self.assertTrue(win.home.empty.isVisible())
            self.assertFalse(win.home.recent_host.isVisible())
            self.assertTrue(win.home.recent_title.isVisible())
            self.assertEqual(win.home.empty.property("role"), "emptyhint")
            self.assertIn("emptyhint", T.qss())
            x_hint = win.home.empty.mapTo(win.home, win.home.empty.rect().topLeft()).x()
            x_hero = win.home.drop.mapTo(win.home, win.home.drop.rect().topLeft()).x()
            self.assertEqual(x_hint, x_hero)
            self.assertGreaterEqual(win.home.empty.height(), win.home.empty.fontMetrics().lineSpacing())
            self.assertLessEqual(win.home.empty.width(), 560)
            self.assertGreaterEqual(contrast(T.TEXT2, T.BG), 4.5)

    def test_hero_headline_grows_with_the_column_and_always_fits(self):
        for w, expect in ((720, T.FS_HERO + 10), (1040, T.FS_HERO + 18), (1440, T.FS_HERO + 18)):
            win = self.window(w, 600, self.SAMPLES)
            dz = win.home.drop
            self.assertEqual(dz._hero_px, expect, w)
            r = dz.hero.mapTo(dz, dz.hero.rect().topLeft()).x() + dz.hero.fontMetrics().horizontalAdvance(dz.hero.text())
            self.assertLess(r, dz.width() - T.S8, f"the headline does not fit at {w} px")

    def test_hero_rule_and_card_grid_share_their_left_edge_and_the_grid_stays_inside_the_column(self):
        for w, h in ((720, 520), (1040, 700), (1440, 900)):
            win = self.window(w, h, self.SAMPLES + [("Another.Film.2010.1080p.WEB-DL", 0, 0), ("Last.One.2001.1080p.BluRay", 0, 0)])
            hs = win.home
            x0 = hs.drop.mapTo(hs, hs.drop.rect().topLeft()).x()
            cards = hs.recent_host.findChildren(RecentCard)
            left = min(c.mapTo(hs, c.rect().topLeft()).x() for c in cards)
            right = max(c.mapTo(hs, c.rect().topRight()).x() for c in cards)
            self.assertEqual(left, x0, f"grid and hero start at different x at {w} px")
            self.assertLessEqual(right, hs.drop.mapTo(hs, hs.drop.rect().topRight()).x() + 1)
            self.assertEqual(hs.recent_title.mapTo(hs, hs.recent_title.rect().topLeft()).x(), x0)

    def test_settings_row_titles_use_the_serif_role_and_the_layout_is_unchanged(self):
        win = self.window(720, 520, (), settings=True)
        rows = [x for x in win.settings_screen.findChildren(QLabel) if x.property("role") == "rowtitle"]
        self.assertGreaterEqual(len(rows), 5)
        self.assertIn('QLabel[role="rowtitle"]', T.qss())


class CompositionLight(Composition):
    theme = "light"


class Cards(Themed):
    def test_long_titles_never_break_the_card_or_overflow(self):
        for t in LONG:
            with self.subTest(title=t[:24]):
                c = RecentCard(item(1, t, 100, 6000))
                c.show()
                app.processEvents()
                self.assertEqual((c.width(), c.height()), (RecentCard.WIDTH, RecentCard.HEIGHT))
                self.assertLessEqual(len(c.name_label.text().split("\n")), 2)
                self.assertLessEqual(c.name_label.fontMetrics().boundingRect(c.name_label.text().split("\n")[0]).width(), c.name_label.width() + 1)
                self.assertGreaterEqual(c.name_label.height(), 2 * c.name_label.fontMetrics().lineSpacing())
                inside = c.rect().adjusted(0, 0, 0, 0)
                for lab in (c.year_label, c.name_label, c.progress_label):
                    self.assertTrue(inside.contains(lab.geometry()), f"{lab.text()!r} leaves the card")

    def test_original_name_stays_in_the_tooltip_for_wrapped_and_elided_titles(self):
        t = LONG[0]
        c = RecentCard(item(1, t))
        self.assertIn(t, c.toolTip().replace("\xa0", " "))

    def test_a_wider_card_variant_lays_out_without_overflow(self):
        class Wide(RecentCard):
            WIDTH = 212 * 2 + T.S3
        c = Wide(item(1, LONG[0], 100, 6000))
        c.show()
        app.processEvents()
        self.assertEqual(c.width(), 436)
        self.assertTrue(c.rect().contains(c.name_label.geometry()))

    def test_year_row_is_reserved_so_titles_line_up(self):
        a, b = RecentCard(item(1, "Film.2020.1080p.WEB-DL")), RecentCard(item(2, "IMG_2048"))
        for c in (a, b):
            c.show()
        app.processEvents()
        self.assertEqual(a.name_label.geometry().y(), b.name_label.geometry().y())

    def test_resting_edge_is_visible_but_not_heavy(self):
        for name in ("EDGE",):
            edge, bg, surface = getattr(T, name), T.BG, T.SURFACE
            self.assertGreaterEqual(contrast(edge, bg), 1.8)
            self.assertGreaterEqual(contrast(edge, surface), 1.7)
            self.assertLessEqual(contrast(edge, bg), 3.0, "the edge is heavy")
        win = self.window(1040, 700, [("Some.Movie.2024.1080p.WEB-DL", 0, 0)])
        c = win.home.findChildren(RecentCard)[0]
        c.clearFocus()
        img = c.grab().toImage()
        px = img.pixelColor(img.width() // 2, 0)                          # top edge, away from the rounded corners
        self.assertNotEqual(px.name().upper(), T.SURFACE.upper(), "no visible resting edge")
        self.assertEqual(px.name().upper(), T.EDGE.upper())

    def test_pressed_card_keeps_its_edge(self):
        win = self.window(1040, 700, [("Some.Movie.2024.1080p.WEB-DL", 0, 0)])
        c = win.home.findChildren(RecentCard)[0]
        c._pressed = True
        c.update()
        img = c.grab().toImage()
        self.assertEqual(img.pixelColor(img.width() // 2, 0).name().upper(), T.EDGE.upper())

    def test_progress_line_reflects_progress_and_watched(self):
        c = RecentCard(item(1, "Film.2020.1080p.WEB-DL", 3000, 6000))
        self.assertAlmostEqual(c.fraction, 0.5)
        self.assertFalse(c.watched)
        d = RecentCard({**item(2, "Film.2020.1080p.WEB-DL", 5900, 6000), "watched": True})
        self.assertEqual((d.fraction, d.watched), (1.0, True))
        self.assertEqual(RecentCard(item(3, "x")).fraction, 0.0)

    window = Composition.window


class CardsLight(Cards):
    theme = "light"


class Radii(unittest.TestCase):
    def test_a_small_system_editorial_sharper_than_controls(self):
        self.assertLessEqual(T.R_CARD, 4)
        self.assertGreater(T.R_CTRL, T.R_CARD)
        self.assertLessEqual(T.R_CTRL, 6)
        self.assertEqual(T.R_PILL, 999)
        self.assertIn(f"border-radius: {T.R_CTRL}px", T.qss())


if __name__ == "__main__":
    unittest.main()
