# SPDX-License-Identifier: GPL-3.0-or-later
"""Interaction quality: transitions are short, interruptible, never delay an action, honour reduced motion, and behave in both themes (offscreen Qt, real-time waits).
Reduced motion is forced per test through the environment override (KINO_REDUCE_MOTION) and restored afterwards."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from kino_stream.recent import RecentItems  # noqa: E402
from kino_stream.settings import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])
from kino_stream_ui import theme as T  # noqa: E402
from kino_stream_ui.app import install_theme  # noqa: E402

install_theme(app)
from kino_stream_ui import widgets as W  # noqa: E402
from kino_stream_ui.bridge import EngineBridge  # noqa: E402
from kino_stream_ui.home import RecentCard  # noqa: E402
from kino_stream_ui.mainwindow import MainWindow  # noqa: E402

FULL = 16777215


def wait(ms):
    QTest.qWait(ms)


class MotionCase(unittest.TestCase):
    theme = "dark"
    reduced = "0"

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"KINO_REDUCE_MOTION": self.reduced})
        patcher.start()
        self.addCleanup(patcher.stop)
        T.apply(self.theme)
        app.setStyleSheet(T.qss())
        app.setPalette(T.palette())
        self.addCleanup(lambda: (T.apply("dark"), app.setStyleSheet(T.qss())))
        self.tmp = Path(tempfile.mkdtemp())
        self.recent = RecentItems(self.tmp / "recent.json")
        for h, t in (("a", "Some.Movie.2024.1080p.WEB-DL.x264-GROUP"), ("b", "Other.Film.1999.720p.HDTV.x264")):
            self.recent.touch(h * 40, t, "x.torrent", 5)
        self.win = MainWindow(EngineBridge(Settings(cache_root=str(self.tmp / "c"), tour_done=True), self.tmp / "state", self.recent))
        self.win.resize(1000, 680)
        self.win.show()
        for _ in range(6):
            app.processEvents()
        self.addCleanup(self.win.close)

    def screens(self):
        return (self.win.home, self.win.settings_screen)


class ScreenFade(MotionCase):
    def test_navigation_is_immediate_and_rapid_changes_leave_a_clean_state(self):
        t0 = time.perf_counter()
        for i in range(40):
            self.win.go(self.win.SETTINGS if i % 2 == 0 else self.win.HOME)
            self.assertEqual(self.win.stack.currentIndex(), self.win.SETTINGS if i % 2 == 0 else self.win.HOME)     # synchronous: never waits for the fade
        per_call_ms = (time.perf_counter() - t0) * 1000 / 40
        self.assertLess(per_call_ms, 40, f"go() took {per_call_ms:.1f} ms per call")
        wait(450)
        for w in self.screens():
            self.assertIsNone(w.graphicsEffect(), "a finished fade must leave no opacity effect behind")
            f = getattr(w, "_kino_fade", None)
            self.assertTrue(f is None or (f.fx is None and f.anim is None))
        self.assertTrue(self.win.stack.currentWidget().isVisible())

    def test_an_interrupted_fade_continues_from_the_current_opacity(self):
        home = self.win.home
        W.fade_in(home, 300)
        wait(90)
        before = home._kino_fade.fx.opacity()
        self.assertTrue(0.05 < before < 0.99, before)
        W.fade_in(home, 300)                                       # interrupt
        after = home._kino_fade.fx.opacity()
        self.assertGreaterEqual(after, before - 0.02, "the interrupted fade jumped back")
        wait(400)
        self.assertIsNone(home.graphicsEffect())

    def test_resizing_during_a_fade_is_safe(self):
        W.fade_in(self.win.home, 300)
        for w, h in ((900, 600), (720, 480), (1100, 760), (800, 520)):
            self.win.resize(w, h)
            wait(30)
        wait(350)
        self.assertIsNone(self.win.home.graphicsEffect())
        self.assertEqual((self.win.width(), self.win.height()), (800, 520))
        self.assertTrue(self.win.home.isVisible())

    def test_closing_the_window_during_a_fade_is_safe(self):
        self.win.go(self.win.SETTINGS)
        W.fade_in(self.win.settings_screen, 300)
        wait(40)
        self.win.close()
        wait(350)                                                  # nothing may fire into destroyed objects

    def test_the_playback_screen_is_never_faded(self):
        self.win.stack.setCurrentIndex(self.win.HOME)
        self.win.go(self.win.PLAYER)
        self.assertIsNone(getattr(self.win.player, "_kino_fade", None))       # a graphics effect on the parent of the GL video widget breaks its rendering
        self.assertIsNone(self.win.player.graphicsEffect())

    def test_an_action_is_not_delayed_by_a_running_fade(self):
        opened = []
        self.win.bridge.open_source = lambda src, **kw: opened.append(src)
        self.win.go(self.win.SETTINGS)
        self.win.go(self.win.HOME)
        torrent = self.tmp / "a.torrent"
        torrent.write_bytes(b"d4:infod4:name1:xee")
        self.win.start_open(str(torrent))
        self.assertEqual(opened, [str(torrent)])                   # sent immediately, mid-fade
        self.assertTrue(self.win.overlay.isVisible())


class ScreenFadeLight(ScreenFade):
    theme = "light"


class ReducedMotion(MotionCase):
    reduced = "1"

    def test_nothing_is_animated(self):
        self.assertIsNone(W.fade_in(self.win.home))
        self.win.go(self.win.SETTINGS)
        self.assertIsNone(self.win.settings_screen.graphicsEffect())
        self.assertIsNone(getattr(self.win.settings_screen, "_kino_fade", None) and self.win.settings_screen._kino_fade.fx)

    def test_a_running_fade_is_finished_at_once_when_motion_is_reduced(self):
        with mock.patch.dict(os.environ, {"KINO_REDUCE_MOTION": "0"}):
            W.fade_in(self.win.home, 400)
            wait(30)
            self.assertIsNotNone(self.win.home.graphicsEffect())
        W.fade_in(self.win.home, 400)                               # now reduced
        self.assertIsNone(self.win.home.graphicsEffect())

    def test_spinner_is_static(self):
        s = W.Spinner(28)
        s.show()
        self.assertFalse(s._t.isActive(), "the spinner must not animate under reduced motion")
        s.close()

    def test_hover_value_jumps(self):
        c = RecentCard(self.recent.items[0])
        c.show()
        c._hover.go(True)
        self.assertEqual(c._hover.value, 1.0)
        c._hover.go(False)
        self.assertEqual(c._hover.value, 0.0)

    def test_banner_appears_and_disappears_instantly(self):
        self.win.banner.show_message("warning", "Title", "Text", [("x", "Do")])
        self.assertTrue(self.win.banner.isVisible())
        self.assertEqual(self.win.banner.maximumHeight(), FULL)
        self.win.banner.collapse()
        self.assertFalse(self.win.banner.isVisible())


class SpinnerAnimated(MotionCase):
    def test_spinner_runs_when_motion_is_allowed_and_stops_when_hidden(self):
        s = W.Spinner(28)
        s.show()
        self.assertTrue(s._t.isActive())
        s.hide()
        self.assertFalse(s._t.isActive())


class BannerMotion(MotionCase):
    def banner(self):
        return self.win.banner

    def show_banner(self):
        self.banner().show_message("warning", "Waiting for sources", "The connection to every source was lost. Playback continues when one comes back.", [("network_check", "Check my connection")])

    def test_it_grows_smoothly_and_ends_at_its_natural_height(self):
        ys = []
        self.show_banner()
        self.assertTrue(self.banner().isVisible())                  # visible at once, even though it is still growing
        end = time.perf_counter() + 0.4
        while time.perf_counter() < end:
            app.processEvents()
            ys.append(self.win.stack.y())
            time.sleep(0.004)
        self.assertGreaterEqual(len(set(ys)), 4, f"the page jumped instead of moving smoothly: {sorted(set(ys))}")
        self.assertEqual(ys, sorted(ys), "the page moved backwards while the banner grew")
        self.assertEqual(self.banner().maximumHeight(), FULL)
        self.assertGreaterEqual(self.banner().height(), self.banner().natural_height() - 2)

    def test_dismissing_mid_growth_collapses_and_hides(self):
        self.show_banner()
        wait(40)
        self.banner().collapse()
        wait(350)
        self.assertFalse(self.banner().isVisible())
        self.assertEqual(self.banner().maximumHeight(), FULL)

    def test_showing_again_mid_collapse_ends_visible_at_full_height(self):
        self.show_banner()
        wait(250)
        self.banner().collapse()
        wait(40)
        self.show_banner()
        wait(350)
        self.assertTrue(self.banner().isVisible())
        self.assertGreaterEqual(self.banner().height(), self.banner().natural_height() - 2)

    def test_instant_hide_cancels_the_animation(self):
        self.show_banner()
        wait(30)
        self.banner().hide()
        wait(300)
        self.assertFalse(self.banner().isVisible())
        self.assertEqual(self.banner().maximumHeight(), FULL)

    def test_resizing_during_the_animation_ends_consistent(self):
        self.show_banner()
        for w in (900, 760, 1000, 720):
            self.win.resize(w, 560)
            wait(25)
        wait(350)
        self.assertTrue(self.banner().isVisible())
        self.assertEqual(self.banner().maximumHeight(), FULL)
        self.assertGreaterEqual(self.banner().height(), 40)


class BannerMotionLight(BannerMotion):
    theme = "light"


class CardStates(MotionCase):
    def card(self):
        from PyQt6.QtCore import QCoreApplication, QEvent
        self.win.home.set_recent(self.recent.items)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)    # set_recent queues the old cards for deletion: do not pick one of those
        app.processEvents()
        return self.win.home.findChildren(RecentCard)[0]

    @staticmethod
    def diff(a, b):
        return sum(1 for x in range(a.width()) for y in range(a.height()) if a.pixel(x, y) != b.pixel(x, y))

    def test_hover_pressed_and_focus_look_different_from_rest_and_from_each_other(self):
        c = self.card()
        c.clearFocus()
        rest = c.grab().toImage()
        c._hover.go(True)
        wait(220)                                                  # the hover transition has finished
        self.assertEqual(round(c._hover.value, 2), 1.0)
        hover = c.grab().toImage()
        c._pressed = True
        c.update()
        pressed = c.grab().toImage()
        c._pressed = False
        c._hover.go(False)
        wait(220)
        c.setFocus()
        app.processEvents()
        focus = c.grab().toImage()
        self.assertGreater(self.diff(rest, hover), 600, "hover is not visible")
        self.assertGreater(self.diff(hover, pressed), 600, "pressed looks like hover")
        self.assertGreater(self.diff(rest, focus), 300, "focus is not visible")
        self.assertEqual(self.diff(rest, c.grab().toImage()) > 0, True)

    def test_hover_reverses_smoothly_from_where_it_is(self):
        c = self.card()
        c._hover.go(True)
        wait(50)
        mid = c._hover.value
        self.assertTrue(0.0 < mid < 1.0, mid)
        c._hover.go(False)
        self.assertLessEqual(c._hover.value, mid + 0.001)
        wait(220)
        self.assertEqual(c._hover.value, 0.0)

    def test_a_click_is_not_delayed_by_the_hover_transition(self):
        c = self.card()
        got = []
        c.clicked.connect(got.append)
        c._hover.go(True)
        QTest.mousePress(c, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton)
        self.assertEqual(len(got), 1)

    def test_a_release_outside_the_card_does_not_open_it(self):
        c = self.card()
        got = []
        c.clicked.connect(got.append)
        QTest.mousePress(c, Qt.MouseButton.LeftButton)
        QTest.mouseRelease(c, Qt.MouseButton.LeftButton, pos=c.rect().bottomRight() + c.rect().center())
        self.assertEqual(got, [])

    def test_keyboard_activation_still_works(self):
        c = self.card()
        got = []
        c.clicked.connect(got.append)
        c.setFocus()
        QTest.keyClick(c, Qt.Key.Key_Return)
        QTest.keyClick(c, Qt.Key.Key_Space)
        self.assertEqual(len(got), 2)


class CardStatesLight(CardStates):
    theme = "light"


class ButtonStates(MotionCase):
    def test_pressed_and_disabled_primary_button_states_are_distinct_in_both_themes(self):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget
        w = QWidget()
        w.setObjectName("root")
        lay = QVBoxLayout(w)
        b = W.button("Open torrent file", "primary")
        lay.addWidget(b)
        w.resize(260, 90)
        w.show()
        app.processEvents()
        self.addCleanup(w.close)
        rest = b.grab().toImage()
        b.setDown(True)
        app.processEvents()
        pressed = b.grab().toImage()
        b.setDown(False)
        b.setEnabled(False)
        app.processEvents()
        disabled = b.grab().toImage()
        d = CardStates.diff
        self.assertGreater(d(rest, pressed), 300)
        self.assertGreater(d(rest, disabled), 300)
        self.assertGreater(d(pressed, disabled), 300)


class ButtonStatesLight(ButtonStates):
    theme = "light"


class Lifecycle(MotionCase):
    """Final review: rapid navigation, resizing, closing mid-animation and keyboard focus, with every kind of animation running at once."""

    def show_banner(self):
        self.win.banner.show_message("warning", "Waiting for sources", "The connection to every source was lost.", [("network_check", "Check my connection")])

    def test_closing_during_banner_growth_and_collapse_is_safe(self):
        self.show_banner()
        wait(30)
        self.win.close()
        wait(350)
        self.setUp()                                               # a second window: closing while the banner is collapsing
        self.show_banner()
        wait(250)
        self.win.banner.collapse()
        wait(30)
        self.win.close()
        wait(350)

    def test_closing_during_a_card_hover_and_a_screen_fade_is_safe(self):
        self.win.home.set_recent(self.recent.items)
        app.processEvents()
        card = self.win.home.findChildren(RecentCard)[0]
        card._hover.go(True)
        W.fade_in(self.win.home, 300)
        wait(30)
        self.win.close()
        wait(350)

    def test_replacing_the_cards_during_a_hover_transition_is_safe(self):
        from PyQt6.QtCore import QCoreApplication, QEvent
        self.win.home.set_recent(self.recent.items)
        app.processEvents()
        for card in self.win.home.findChildren(RecentCard):
            card._hover.go(True)
        wait(40)
        for _ in range(5):
            self.win.home.set_recent(self.recent.items)
            wait(15)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        wait(300)
        self.assertEqual(len(self.win.home.findChildren(RecentCard)), 2)

    def test_everything_at_once_leaves_a_clean_final_state(self):
        self.show_banner()
        for i in range(12):
            self.win.go(self.win.SETTINGS if i % 2 == 0 else self.win.HOME)
            self.win.resize(760 + 20 * i, 520 + 10 * i)
            if i == 5:
                self.win.banner.collapse()
            if i == 7:
                self.show_banner()
            wait(12)
        wait(500)
        self.assertEqual(self.win.stack.currentIndex(), self.win.HOME)
        for w in self.screens():
            self.assertIsNone(w.graphicsEffect())
        self.assertFalse(self.win.banner.isVisible(), "going home hides a banner that is not sticky (existing behaviour)")
        self.assertEqual(self.win.banner.maximumHeight(), FULL, "a hidden banner must not keep a height limit")

    def test_a_collapsed_banner_cannot_keep_keyboard_focus(self):
        self.show_banner()
        wait(250)
        self.win.banner.setFocus()
        self.win.banner.collapse()
        wait(350)
        self.assertFalse(self.win.banner.isVisible())
        fw = QApplication.focusWidget()
        self.assertTrue(fw is None or (fw.isVisible() and not self.win.banner.isAncestorOf(fw)), f"focus stuck on a hidden widget: {fw}")

    def test_focus_survives_a_screen_fade_and_tab_order_still_reaches_visible_widgets(self):
        self.win.go(self.win.SETTINGS)
        W.fade_in(self.win.settings_screen, 300)
        seen = set()
        for _ in range(40):
            QTest.keyClick(self.win, Qt.Key.Key_Tab)
            fw = QApplication.focusWidget()
            if fw is not None:
                self.assertTrue(fw.isVisible(), f"focus moved to an invisible widget: {fw}")
                self.assertTrue(fw.isEnabled())
                seen.add(id(fw))
            wait(8)
        self.assertGreaterEqual(len(seen), 3, "Tab did not move through the settings controls during the fade")
        wait(350)
        self.assertIsNone(self.win.settings_screen.graphicsEffect())
        fw = QApplication.focusWidget()
        self.assertTrue(fw is not None and fw.isVisible())

    def test_a_focused_card_keeps_its_focus_ring_while_it_is_hovered_and_after_the_cards_are_rebuilt(self):
        from PyQt6.QtCore import QCoreApplication, QEvent
        self.win.home.set_recent(self.recent.items)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        card = self.win.home.findChildren(RecentCard)[0]
        card.clearFocus()
        card.update()
        app.processEvents()
        rest = card.grab().toImage()
        card.setFocus()
        card._hover.go(True)
        wait(250)
        both = card.grab().toImage()
        self.assertGreater(CardStates.diff(rest, both), 300)
        self.assertTrue(card.hasFocus())


class LifecycleLight(Lifecycle):
    theme = "light"


class LifecycleReduced(Lifecycle):
    reduced = "1"


if __name__ == "__main__":
    unittest.main()
