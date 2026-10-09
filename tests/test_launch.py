"""Launcher behaviour: argument parsing, single instance hand-over, external open requests, diagnostics redaction."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from kino_stream.recent import RecentItems  # noqa: E402
from kino_stream.settings import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])
from kino_stream_ui import app as appmod  # noqa: E402
from kino_stream_ui.app import InstanceServer, forward_to_running_instance, parse_target  # noqa: E402
from kino_stream_ui.bridge import EngineBridge  # noqa: E402
from kino_stream_ui.dialogs import redact  # noqa: E402
from kino_stream_ui.mainwindow import MainWindow  # noqa: E402

MAGNET = "magnet:?xt=urn:btih:" + "ab" * 20


class Parsing(unittest.TestCase):
    def test_targets(self):
        self.assertEqual(parse_target(MAGNET), MAGNET)
        self.assertEqual(parse_target("/tmp/a b.torrent"), "/tmp/a b.torrent")
        self.assertEqual(parse_target("file:///tmp/a%20b.torrent"), "/tmp/a b.torrent")
        for bad in ("", "http://x/y", "/tmp/movie.mkv", "magnet:", "file:///etc/passwd"):
            self.assertEqual(parse_target(bad), "", bad)

    def test_redaction(self):
        t = redact(f'{{"p": "{Path.home()}/.cache/kino-stream/x", "m": "{MAGNET}&tr=udp://tracker.example:6969/announce?passkey=SECRET", "u": "https://t.example/ann?k=SECRET"}}')
        self.assertNotIn("SECRET", t)
        self.assertNotIn(str(Path.home()), t)
        self.assertIn("btih:" + "ab" * 20, t)


class Window(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        st = Settings(cache_root=str(self.tmp / "caches"), tour_done=True)
        self.bridge = EngineBridge(st, self.tmp / "state", RecentItems(self.tmp / "recent.json"))
        self.opened = []
        self.bridge.open_source = lambda src, **kw: self.opened.append(src)       # no engine work in these tests
        self.win = MainWindow(self.bridge)
        self.win.show()
        self.addCleanup(self.win.close)

    def test_external_magnet_and_file_open(self):
        torrent = self.tmp / "t.torrent"
        torrent.write_bytes(b"d4:infod4:name1:xee")
        self.win.handle_external(MAGNET)
        self.win.overlay.hide()
        self.win.handle_external(str(torrent))
        self.assertEqual(self.opened, [MAGNET, str(torrent)])

    def test_missing_file_does_not_start_an_open(self):
        self.win.handle_external(str(self.tmp / "gone.torrent"))
        self.assertEqual(self.opened, [])
        self.assertFalse(self.win.overlay.isVisible())

    def test_request_during_tutorial_waits_for_it(self):
        self.win.show_tour()
        self.win.handle_external(MAGNET)
        self.assertEqual(self.opened, [])
        self.win.tour.skip.click()
        for _ in range(5):
            QCoreApplication.processEvents()
        self.assertEqual(self.opened, [MAGNET])

    def test_second_launch_is_forwarded_to_the_running_one(self):
        got = []
        srv = InstanceServer(got.append)
        self.addCleanup(srv.server.close)
        self.assertTrue(srv.ok)
        import threading
        import time
        res = []
        t = threading.Thread(target=lambda: res.append(forward_to_running_instance(MAGNET)))
        t.start()
        end = time.time() + 5
        while time.time() < end and (t.is_alive() or not got):
            QCoreApplication.processEvents()
            time.sleep(0.02)
        t.join()
        self.assertEqual((res, got), ([True], [MAGNET]))

    def test_no_running_instance_means_start_normally(self):
        from PyQt6.QtNetwork import QLocalServer
        QLocalServer.removeServer(appmod.instance_name())
        self.assertFalse(forward_to_running_instance(MAGNET, timeout_ms=200))


if __name__ == "__main__":
    unittest.main()
