# SPDX-License-Identifier: GPL-3.0-or-later
"""First-run tutorial: navigation, skip/finish, persistence across restarts, Help reopen, sizes, reduced motion, isolation from the engine."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from lumiere.recent import RecentItems  # noqa: E402
from lumiere.settings import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])
from lumiere_ui.app import install_theme  # noqa: E402

install_theme(app)
from lumiere_ui import motion  # noqa: E402
from lumiere_ui.bridge import EngineBridge  # noqa: E402
from lumiere_ui.mainwindow import MainWindow  # noqa: E402
from lumiere_ui.tour import STEPS, TourOverlay, steps  # noqa: E402


def pump(n=8):
    for _ in range(n):
        app.processEvents()


def wait_idle(w, ms=600):
    QTest.qWait(ms)
    pump()


class TourBase(unittest.TestCase):
    reduce = "1"                                  # instant transitions keep the tests deterministic

    def setUp(self):
        os.environ["LUMIERE_REDUCE_MOTION"] = self.reduce
        self.tmp = Path(tempfile.mkdtemp())
        self.settings_path = Path(os.environ["XDG_CONFIG_HOME"]) / "lumiere" / "settings.json"
        if self.settings_path.exists():
            self.settings_path.unlink()
        self.boot()

    def boot(self):
        st = Settings.load(self.settings_path) if self.settings_path.exists() else Settings(cache_root=str(self.tmp / "caches"))
        self.bridge = EngineBridge(st, self.tmp / "state", RecentItems(self.tmp / "recent.json"))
        self.win = MainWindow(self.bridge)
        self.win.resize(1000, 680)
        self.win.show()
        pump()

    def shutdown(self):
        self.win.close()

    def tearDown(self):
        self.shutdown()
        os.environ.pop("LUMIERE_REDUCE_MOTION", None)


class Navigation(TourBase):
    def test_five_steps_forward_and_back(self):
        t = self.win.tour
        self.win.show_tour()
        pump()
        self.assertTrue(t.isVisible())
        self.assertEqual((t.index, t.back.isEnabled(), t.next.text()), (0, False, "Next"))
        for i in range(1, STEPS):
            t.go_next()
            pump()
            self.assertEqual(t.index, i)
        self.assertEqual(t.next.text(), "Finish")
        self.assertFalse(t.skip.isVisible())
        t.go_back()
        self.assertEqual(t.index, STEPS - 2)
        self.assertEqual(t.next.text(), "Next")

    def test_titles_are_the_agreed_five(self):
        titles = [s.title for s in steps(4)]
        self.assertEqual(len(titles), 5)
        self.assertEqual(titles[1], "Open a video")

    def test_keyboard_navigation(self):
        t = self.win.tour
        self.win.show_tour()
        pump()
        QTest.keyClick(t, Qt.Key.Key_Right)
        QTest.keyClick(t, Qt.Key.Key_Right)
        self.assertEqual(t.index, 2)
        QTest.keyClick(t, Qt.Key.Key_Left)
        self.assertEqual(t.index, 1)
        QTest.keyClick(t, Qt.Key.Key_Escape)
        self.assertFalse(t.isVisible())

    def test_accessibility_names_follow_the_step(self):
        t = self.win.tour
        self.win.show_tour()
        self.assertIn("step 1 of 5", t.card.accessibleName())
        t.go_next()
        self.assertIn("step 2 of 5: Open a video", t.card.accessibleName())
        self.assertTrue(t.card.accessibleDescription())
        for b in (t.skip, t.back, t.next):
            self.assertTrue(b.accessibleName())
        self.assertEqual(t.focusPolicy(), Qt.FocusPolicy.StrongFocus)

    def test_honest_wording_about_streaming(self):
        s = steps(4)
        text = " ".join(x.body + " " + x.note for x in s).lower()
        self.assertIn("cannot be guaranteed", text)
        for bad in ("uninterrupted", "always smooth", "never buffer", "no buffering"):
            self.assertNotIn(bad, text)
        self.assertIn("4 gb", s[3].body.lower())


class Completion(TourBase):
    def test_first_launch_shows_and_finish_persists(self):
        self.assertFalse(self.win.bridge.settings.tour_done)
        self.win.maybe_show_tour()
        QTest.qWait(400)
        self.assertTrue(self.win.tour.isVisible())
        for _ in range(STEPS):
            self.win.tour.go_next()
            pump()
        self.assertFalse(self.win.tour.isVisible())
        self.assertTrue(self.win.bridge.settings.tour_done)
        self.assertTrue(Settings.load(self.settings_path).tour_done)

    def test_skip_counts_as_done(self):
        self.win.show_tour()
        self.win.tour.skip.click()
        self.assertTrue(Settings.load(self.settings_path).tour_done)

    def test_not_shown_again_after_restart_and_other_settings_keep_the_flag(self):
        self.win.show_tour()
        self.win.tour.skip.click()
        pump()
        # a later settings edit must not reset the flag (the settings screen holds its own copy)
        sc = self.win.settings_screen
        sc.cache.setValue(sc.cache.value() + 1)
        QTest.qWait(700)
        pump()
        self.assertTrue(Settings.load(self.settings_path).tour_done)
        self.shutdown()
        self.boot()
        self.win.maybe_show_tour()
        QTest.qWait(500)
        self.assertFalse(self.win.tour.isVisible())

    def test_help_menu_reopens_at_step_one(self):
        self.win.show_tour()
        self.win.tour.go_next()
        self.win.tour.skip.click()
        acts = [a for m in self.win.menuBar().findChildren(type(self.win.menuBar().addMenu("x"))) for a in m.actions()]
        again = [a for a in acts if a.text() == "Show Tutorial Again"]
        self.assertEqual(len(again), 1)
        again[0].trigger()
        pump()
        self.assertTrue(self.win.tour.isVisible())
        self.assertEqual(self.win.tour.index, 0)

    def test_home_help_button_reopens(self):
        self.win.home.helpRequested.emit()
        self.assertTrue(self.win.tour.isVisible())


class Isolation(TourBase):
    def test_tour_never_touches_the_engine(self):
        calls = []
        for name in ("open_source", "feed_player", "player_event", "close_media", "cancel_open"):
            setattr(self.bridge, name, lambda *a, _n=name, **k: calls.append(_n))
        self.win.show_tour()
        for _ in range(STEPS):
            self.win.tour.go_next()
            pump()
        self.assertEqual(calls, [])
        self.assertEqual(self.bridge.service.snapshot().get("phase"), "idle")

    def test_module_has_no_engine_imports(self):
        src = (Path(__file__).parents[1] / "lumiere_ui" / "tour.py").read_text()
        for bad in ("lumiere.", "libtorrent", "bridge", "service"):
            self.assertNotIn(f"import {bad}", src)
            self.assertNotIn(f"from {bad}", src)


class Sizes(TourBase):
    def test_card_fits_at_minimum_and_large_windows(self):
        for w, h in ((720, 480), (900, 600), (1280, 800), (1920, 1080)):
            self.win.resize(w, h)
            self.win.show_tour()
            pump()
            for i in range(STEPS):
                self.win.tour.index = i
                self.win.tour._apply()
                pump(4)
                card = self.win.tour.card
                host = self.win.tour.rect()
                self.assertTrue(host.contains(card.geometry()), f"{w}x{h} step {i}: card {card.geometry()} outside {host}")
                self.assertGreaterEqual(card.width(), 400)
            self.win.tour.skip.click() if self.win.tour.isVisible() else None
            self.win.tour.hide()


class Motion(TourBase):
    reduce = "1"

    def test_reduced_motion_is_instant_and_static(self):
        self.assertTrue(motion.reduced_motion())
        t = self.win.tour
        self.win.show_tour()
        self.assertIsNone(t.graphicsEffect(), "no fade-in with reduced motion")
        t.go_next()
        self.assertEqual(t.index, 1)                       # no animation in flight: the step changed synchronously
        self.assertEqual(t.illu._anim.state().name, "Stopped")
        self.assertEqual(t.illu.phase, 1.0)

    def test_env_overrides_system_setting(self):
        os.environ["LUMIERE_REDUCE_MOTION"] = "0"
        self.assertFalse(motion.reduced_motion())
        os.environ["LUMIERE_REDUCE_MOTION"] = "1"
        self.assertTrue(motion.reduced_motion())


class AnimatedMotion(TourBase):
    reduce = "0"

    def test_transition_completes_and_illustration_runs(self):
        t = self.win.tour
        self.win.show_tour()
        wait_idle(self.win, 400)
        self.assertEqual(t.illu._anim.state().name, "Running")
        t.go_next()
        wait_idle(self.win, 700)
        self.assertEqual(t.index, 1)
        self.assertAlmostEqual(t.fx.opacity(), 1.0, places=1)
        t.go_next()
        t.go_next()                                         # a click during a transition is ignored, not queued
        wait_idle(self.win, 700)
        self.assertEqual(t.index, 2)


if __name__ == "__main__":
    unittest.main()
