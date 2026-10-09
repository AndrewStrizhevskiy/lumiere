# SPDX-License-Identifier: GPL-3.0-or-later
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
_rt = tempfile.mkdtemp()
os.chmod(_rt, 0o700)
os.environ["XDG_RUNTIME_DIR"] = _rt                 # the hand-over socket must live in a private per-user directory

from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from kino_stream.recent import RecentItems  # noqa: E402
from kino_stream.settings import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])
from kino_stream_ui import app as appmod  # noqa: E402
from kino_stream_ui.app import InstanceServer, forward_to_running_instance, instance_socket_path, parse_target, socket_is_ours  # noqa: E402
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


class Redaction(unittest.TestCase):
    def test_magnet_with_name_first_and_other_url_schemes(self):
        t = redact(f'x magnet:?dn=Movie&tr=udp%3A%2F%2Ft.example%3A80%2Fannounce%3Fpasskey%3DSECRET&xt=urn:btih:{"cd" * 20} y '
                   'wss://t.example/a?k=SECRET tcp://1.2.3.4:6881 peer 10.1.2.3:51413 /home/otheruser/x [2001:db8:0:1::5]')
        self.assertNotIn("SECRET", t)
        self.assertNotIn("1.2.3.4", t)
        self.assertNotIn("10.1.2.3", t)
        self.assertNotIn("otheruser", t)
        self.assertNotIn("Movie", t)
        self.assertIn("btih:" + "cd" * 20, t)

    def test_magnet_without_hash_is_still_hidden(self):
        t = redact("magnet:?dn=Secret+Title&tr=http://t.example/ann?k=SECRET")
        self.assertNotIn("SECRET", t)
        self.assertNotIn("Secret+Title", t)


class SocketSafety(unittest.TestCase):
    def test_socket_lives_in_a_private_directory_not_tmp(self):
        p = Path(instance_socket_path())
        self.assertEqual(str(p.parent), os.environ["XDG_RUNTIME_DIR"])
        self.assertEqual(os.stat(p.parent).st_mode & 0o077, 0)

    def test_fallback_when_runtime_dir_is_not_private(self):
        old = os.environ["XDG_RUNTIME_DIR"]
        loose = tempfile.mkdtemp()
        os.chmod(loose, 0o755)
        os.environ["XDG_RUNTIME_DIR"] = loose
        try:
            p = Path(instance_socket_path())
            self.assertNotEqual(str(p.parent), loose)
            self.assertEqual(os.stat(p.parent).st_mode & 0o077, 0)
        finally:
            os.environ["XDG_RUNTIME_DIR"] = old

    def test_a_squatted_path_is_refused(self):
        from unittest import mock
        path = instance_socket_path()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(path):
            os.unlink(path)
        Path(path).write_text("not a socket")                    # a regular file in the place of the socket
        self.addCleanup(lambda: os.path.lexists(path) and os.unlink(path))
        self.assertFalse(socket_is_ours(path))
        self.assertFalse(forward_to_running_instance(MAGNET, timeout_ms=100))
        srv = InstanceServer(lambda s: None)
        self.assertFalse(srv.ok)
        self.assertEqual(Path(path).read_text(), "not a socket", "a foreign file must never be replaced")
        os.unlink(path)
        # a socket owned by someone else is refused too
        import socket
        sk = socket.socket(socket.AF_UNIX)
        sk.bind(path)
        self.addCleanup(sk.close)
        with mock.patch("kino_stream_ui.app.os.getuid", return_value=os.getuid() + 1):
            self.assertFalse(socket_is_ours(path))
        self.assertTrue(socket_is_ours(path))

    def test_oversized_request_is_capped(self):
        got = []
        srv = InstanceServer(got.append)
        self.addCleanup(srv.server.close)
        self.assertEqual(InstanceServer.MAX_REQUEST, 16 * 1024)


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
        QLocalServer.removeServer(instance_socket_path())
        self.assertFalse(forward_to_running_instance(MAGNET, timeout_ms=200))


if __name__ == "__main__":
    unittest.main()
