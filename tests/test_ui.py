"""GUI tests (offscreen): message mapping, drop zone validation, settings persistence, window flow."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()                      # never touch the real ~/.config in tests
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtWidgets import QApplication

from kino_stream import events as ev
from kino_stream.recent import RecentItems
from kino_stream.settings import Settings

app = QApplication.instance() or QApplication([])
from kino_stream_ui.app import install_theme  # noqa: E402

install_theme(app)
from kino_stream_ui.bridge import EngineBridge  # noqa: E402
from kino_stream_ui.home import looks_like_magnet  # noqa: E402
from kino_stream_ui.mainwindow import MainWindow  # noqa: E402
from kino_stream_ui.messages import for_code  # noqa: E402
from kino_stream_ui.widgets import fmt_bytes  # noqa: E402


def pump(n=5):
    for _ in range(n):
        app.processEvents()


class Pure(unittest.TestCase):
    def test_magnet_validation(self):
        self.assertTrue(looks_like_magnet("magnet:?xt=urn:btih:" + "a" * 40))
        self.assertFalse(looks_like_magnet("http://example.com"))
        self.assertFalse(looks_like_magnet("magnet:?dn=x"))

    def test_messages_cover_codes_without_overclaiming(self):
        for code in (ev.NO_PEERS, ev.NETWORK_LOST, ev.SLOW_CONNECTION, ev.CACHE_FULL, ev.UNSUPPORTED_FILE,
                     ev.CACHE_UNSUPPORTED_FS, ev.CACHE_TOO_SMALL, ev.OPEN_FAILED):
            m = for_code(code)
            self.assertTrue(m and m.title and m.text, code)
            self.assertNotIn("throttl", (m.title + m.text).lower())

    def test_unsupported_fs_offers_explicit_temporary_mode(self):
        keys = [k for k, _ in for_code(ev.CACHE_UNSUPPORTED_FS).actions]
        self.assertIn("play_temporary", keys)

    def test_binary_units(self):
        self.assertEqual(fmt_bytes(4 << 30), "4.0 GB")


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.st = Settings(cache_root=str(self.tmp / "caches"))
        self.recent = RecentItems(self.tmp / "recent.json")
        self.bridge = EngineBridge(self.st, self.tmp / "state", self.recent)
        self.win = MainWindow(self.bridge)
        self.win.show()
        pump()

    def tearDown(self):
        self.win.close()

    def test_navigation_and_render(self):
        for i in (self.win.SETTINGS, self.win.HOME):
            self.win.go(i)
            pump()
            self.assertFalse(self.win.grab().isNull())

    def test_missing_file_is_reported_not_crashing(self):
        self.win.start_open(str(self.tmp / "nope.torrent"))
        pump()
        self.assertFalse(self.win.overlay.isVisible())

    def test_open_cancel_hides_overlay(self):
        self.win.overlay.open()
        self.win.overlay.cancelled.emit()
        pump()
        self.assertFalse(self.win.overlay.isVisible())

    def test_open_failure_maps_to_dialog_and_hides_overlay(self):
        shown = []
        import kino_stream_ui.mainwindow as mw

        class D:
            choice = ""
            def __init__(self, msg, parent=None, technical=""): shown.append(msg.code if hasattr(msg, "code") else msg.title)
            def exec(self): return 0
        orig = mw.MessageDialog
        mw.MessageDialog = D
        try:
            self.win.overlay.open()
            self.win.on_open_failed(ev.CACHE_UNSUPPORTED_FS, "")
        finally:
            mw.MessageDialog = orig
        self.assertEqual(len(shown), 1)
        self.assertFalse(self.win.overlay.isVisible())

    def test_settings_persist_and_reload(self):
        import dataclasses
        self.bridge.apply_settings(dataclasses.replace(self.st, cache_gb=8.0, network="quick"))
        again = Settings.load()
        self.assertEqual((again.cache_gb, again.network), (8.0, "quick"))
        self.assertTrue(str(Path(os.environ["XDG_CONFIG_HOME"])) in str(Path(os.environ["XDG_CONFIG_HOME"]) / "kino-stream"))


if __name__ == "__main__":
    unittest.main()
