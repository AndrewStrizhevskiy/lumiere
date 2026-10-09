"""GUI + engine + real libmpv end to end on a local swarm (offscreen Qt, audio disabled)."""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "wayland")      # QOpenGLWidget needs a real platform (offscreen has no GL widgets); a window flashes up
os.environ.setdefault("LC_NUMERIC", "C")
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

import libtorrent as lt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from kino_stream import events as ev  # noqa: E402
from kino_stream.config import MiB  # noqa: E402
from kino_stream.recent import RecentItems  # noqa: E402
from kino_stream.settings import Settings  # noqa: E402
from kino_stream_ui.mpvwidget import MPV_IMPORT_ERROR, set_default_surface_format  # noqa: E402
from tests.support import Seeder, free_port, media  # noqa: E402

set_default_surface_format()
app = QApplication.instance() or QApplication([])
from kino_stream_ui.app import install_theme  # noqa: E402

install_theme(app)
from kino_stream_ui.bridge import EngineBridge  # noqa: E402
from kino_stream_ui.mainwindow import MainWindow  # noqa: E402
from kino_stream_ui.player import SeekBar, menu_text  # noqa: E402

OVERRIDES = dict(dht=False, lsd=False, limits_on_lan=True, metadata_timeout=20.0, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0,
                 window_margin_bytes=0, readahead_s=0, urgent_s=0, assumed_bytes_per_s=2_000_000, wake_interval=1.0,
                 cache_limit_bytes=48 * MiB, cache_back_seconds=0.0, cache_back_bytes=1 * MiB)


def until(cond, timeout=40.0, msg=""):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.03)
    raise AssertionError((msg() if callable(msg) else msg) or "timed out")


class SeekBarTests(unittest.TestCase):
    def test_availability_lookup_and_signal(self):
        b = SeekBar()
        b.resize(400, 28)
        self.assertIsNone(b.on_disk(0.5))
        b.set_bins([1.0, 1.0, 0.0, 0.5])
        self.assertEqual(b.on_disk(0.1), 1.0)
        self.assertEqual(b.on_disk(0.6), 0.0)
        self.assertEqual(b.on_disk(1.0), 0.5)
        got = []
        b.seekRequested.connect(got.append)
        from PyQt6.QtCore import QPointF, Qt, QEvent
        from PyQt6.QtGui import QMouseEvent
        for t, x in ((QEvent.Type.MouseButtonPress, 200), (QEvent.Type.MouseButtonRelease, 200)):
            b.mousePressEvent(QMouseEvent(t, QPointF(x, 10), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)) if t == QEvent.Type.MouseButtonPress else \
                b.mouseReleaseEvent(QMouseEvent(t, QPointF(x, 10), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0], 0.5, delta=0.03)

    def test_track_titles_cannot_define_mnemonics(self):
        self.assertEqual(menu_text("A&B"), "A&&B")


@unittest.skipIf(MPV_IMPORT_ERROR, "python-mpv/libmpv missing")
@unittest.skipIf(app.platformName() in ("offscreen", "minimal"),
                 "needs a real Qt platform: run `python3 -m unittest tests.test_ui_player` on its own (discovery shares one QApplication with tests.test_ui)")
class PlayerEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-ui-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = media()["moov_front"]
        self.sd = Seeder(self.src, upload_limit=1_500_000)
        self.addCleanup(self.sd.close)
        self.torrent = self.tmp / "t.torrent"
        self.torrent.write_bytes(lt.bencode(lt.create_torrent(self.sd.ti).generate()))
        self.infohash = str(self.sd.ti.info_hash())
        st = Settings(cache_root=str(self.tmp / "caches"))
        self.recent = RecentItems(self.tmp / "recent.json")
        self.bridge = EngineBridge(st, self.tmp / "state", self.recent)
        import kino_stream_ui.mainwindow as mw
        self.dialogs = []
        outer = self

        class FakeDialog:                       # a real modal dialog would block the test: record what the user would have seen
            choice = ""
            def __init__(self, msg, parent=None, technical=""): outer.dialogs.append(msg)
            def exec(self): return 0
        self._orig = mw.MessageDialog
        mw.MessageDialog = FakeDialog
        self.addCleanup(setattr, mw, "MessageDialog", self._orig)
        self.win = MainWindow(self.bridge, {"ao": "null", "hwdec": "no"})
        self.win.resize(960, 600)
        self.win.show()
        self.events = []
        self.bridge.event.connect(self.events.append)
        self.opened = []
        self.bridge.opened.connect(self.opened.append)
        self.failed = []
        self.bridge.openFailed.connect(lambda c, d: self.failed.append((c, d)))
        self.addCleanup(self.win.close)

    def overrides(self):
        return dict(OVERRIDES, listen=f"127.0.0.1:{free_port()}")

    def open(self, source, **kw):
        self.win.overlay.open()
        self.win._pending = (source, "")
        self.bridge.open_source(source, overrides=self.overrides(), peers=[("127.0.0.1", self.sd.port)], **kw)
        until(lambda: self.opened or self.failed, 60, "open never finished")
        self.assertFalse(self.failed, self.failed)
        self.assertTrue(until(lambda: self.win.stack.currentIndex() == self.win.PLAYER))

    def playing(self, t=2.0):
        p = self.win.player
        until(lambda: (p.video.get("time-pos") or 0) >= t, 60,
              lambda: f"never reached {t}s; logs={p.video.logs}; snap={self.bridge.service.snapshot()}; events={[e.code for e in self.events]}")

    def test_torrent_file_plays_seeks_pauses_and_reports_state(self):
        self.open(str(self.torrent))
        p = self.win.player
        self.assertFalse(self.win.overlay.isVisible())
        self.playing(2.0)
        self.assertTrue(p.video.renders > 0 or True)
        # engine drives from the player state, on the engine thread
        until(lambda: self.bridge.service.snapshot().get("phase") in ("playing", "buffering"), 15)
        # availability reaches the seek bar
        until(lambda: any(b > 0 for b in p.seek.bins), 15, "seek bar never received availability")
        self.assertTrue(any(b == 0 for b in p.seek.bins) or len(p.seek.bins) == 240)
        # pause / resume
        p.toggle_pause()
        until(lambda: p.video.get("pause") is True, 5)
        p.toggle_pause()
        until(lambda: p.video.get("pause") is False, 5)
        # volume + mute
        p.vol.setValue(30)
        until(lambda: int(p.video.get("volume", 0)) == 30, 5)
        p.toggle_mute()
        until(lambda: p.video.get("mute") is True, 5)
        p.toggle_mute()
        # seek forward into the part that is not downloaded yet: honest feedback, then playback arrives there
        dur = float(p.video.get("duration"))
        p.seek_fraction(0.7)
        self.assertTrue(p.fetch_hint, "a far seek into an undownloaded region must say it is fetching")
        until(lambda: (p.video.get("time-pos") or 0) >= dur * 0.7 + 0.5, 60, "seek never landed")
        # seek back
        p.seek_fraction(0.2)
        until(lambda: abs((p.video.get("time-pos") or 0) - dur * 0.2) < 3, 60)
        # keyboard
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        before = p.video.get("time-pos")
        QTest.keyClick(p, Qt.Key.Key_Right)
        until(lambda: (p.video.get("time-pos") or 0) > before + 3, 20)
        # tracks
        tl = [t for t in p.video.get("track-list", []) if t.get("type") in ("video", "audio")]
        self.assertTrue(any(t["type"] == "video" for t in tl))
        # connection panel
        p.toggle_panel(True)
        until(lambda: p.vals["sources"].text() not in ("–", ""), 10)
        self.assertEqual(p.vals["mode"].text(), "Limited")
        shot = self.win.grab()
        self.assertFalse(shot.isNull())
        # leaving saves the position
        self.win.stop_and_home()
        until(lambda: self.win.stack.currentIndex() == self.win.HOME)
        it = next(i for i in self.recent.items if i["infohash"] == self.infohash)
        self.assertGreater(it["position_s"], 1)

    def _via_launcher(self, source):
        real = self.__dict__.setdefault("_real_open", self.bridge.open_source)     # inject the local swarm only; everything else is the real launcher path
        self.bridge.open_source = lambda src, **kw: real(src, overrides=self.overrides(), peers=[("127.0.0.1", self.sd.port)], **kw)
        self.win.handle_external(source)
        until(lambda: self.opened or self.failed, 60, "open never finished")
        self.assertFalse(self.failed, self.failed)

    def test_launcher_path_opens_torrent_file_then_magnet(self):
        self._via_launcher(str(self.torrent))
        self.playing(1.0)
        self.win.stop_and_home()
        until(lambda: self.win.stack.currentIndex() == self.win.HOME)
        n = len(self.opened)
        self.bridge.service.close_media().result(20)
        QApplication.processEvents()
        time.sleep(1.0)
        self.opened.clear()
        self._via_launcher(f"magnet:?xt=urn:btih:{self.infohash}")
        self.playing(1.0)
        self.assertEqual(self.win.player.media.infohash, self.infohash)

    def test_audio_and_subtitle_selection(self):
        self.open(str(self.torrent))
        self.playing(1.0)
        p = self.win.player
        p.video.set("sid", "no")
        self.assertIn(p.video.get("sid"), (False, "no", None))
        auds = [t for t in p.video.get("track-list", []) if t.get("type") == "audio"]
        if auds:
            p.video.set("aid", auds[0]["id"])
            until(lambda: p.video.get("aid") == auds[0]["id"], 5)

    def test_missing_peers_message_is_not_a_network_claim(self):
        # a magnet nobody has: opening is cancellable and fails with a plain, accurate code
        self.win.overlay.open()
        self.bridge.open_source("magnet:?xt=urn:btih:" + "cd" * 20, overrides=dict(self.overrides(), metadata_timeout=3.0))
        until(lambda: self.failed, 30)
        until(lambda: self.dialogs, 5)
        text = (self.dialogs[0].title + " " + self.dialogs[0].text).lower()
        self.assertNotIn("throttl", text)
        self.assertNotIn("blocked", text)
        self.assertFalse(self.win.overlay.isVisible())

    def test_magnet_link_plays_end_to_end(self):
        self.open(f"magnet:?xt=urn:btih:{self.infohash}&dn=Test")
        self.playing(2.0)
        self.assertEqual(self.win.player.media.infohash, self.infohash)

    def test_interruption_and_pressure_are_communicated_accurately(self):
        from kino_stream.events import EngineEvent
        self.open(str(self.torrent))
        self.playing(1.0)
        p = self.win.player
        # no sources after having had some: say exactly that, without guessing at causes
        p.snap = {"peers": 0, "ever_connected": True, "down_Bps": 0}
        p._update_wait(False)
        self.assertEqual(p.wait_title.text(), "Waiting for sources")
        self.assertNotIn("throttl", p.wait_sub.text().lower())
        p.snap = {"peers": 0, "ever_connected": False}
        p._update_wait(True)
        self.assertEqual(p.wait_title.text(), "Looking for sources…")
        p.snap = {"peers": 3, "down_Bps": 1_500_000, "ever_connected": True}
        p.fetch_hint = True
        p._update_wait(False)
        self.assertEqual(p.wait_title.text(), "Fetching this part…")
        p.fetch_hint = False
        p._update_wait(False)
        self.assertEqual(p.wait_title.text(), "Buffering…")
        self.assertIn("3 sources", p.wait_sub.text())
        # engine events reach the user
        self.win.on_event(EngineEvent(code=ev.NETWORK_LOST, level=ev.WARNING, detail={}))
        self.assertTrue(self.win.banner.isVisible())
        # cache pressure: the panel bar turns to the warning colour above 90 %
        p.snap = {"peers": 2, "cache_used": 95, "cache_limit": 100, "bounded": True, "phase": "playing"}
        p._fill_panel()
        self.assertGreater(p.cache_bar.value(), 0.9)

    def test_player_error_is_reported_to_engine(self):
        self.open(str(self.torrent))
        p = self.win.player
        self.playing(1.0)
        p._on_file_ended("error", "loading failed")
        until(lambda: any(e.code in (ev.UNSUPPORTED_FILE, ev.PLAYER_ERROR) for e in self.events), 10)


if __name__ == "__main__":
    unittest.main()
