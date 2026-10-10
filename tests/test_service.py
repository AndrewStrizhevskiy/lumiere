# SPDX-License-Identifier: GPL-3.0-or-later
"""Engine facade (no GUI): settings, recent items, managed caches, EngineService on a local swarm."""
import asyncio
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from lumiere import events as ev
from lumiere.caches import MARKER, NotManaged, delete_managed_cache, list_caches, prepare_cache_dir
from lumiere.config import MiB
from lumiere.recent import RecentItems
from lumiere.scheduler import PlayerState
from lumiere.service import EngineError, EngineService, OpenOptions
from lumiere.settings import Settings
from lumiere.store import CacheDirNotManagedError
from tests.support import Seeder, free_port, http_range, media

import libtorrent as lt


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_defaults_and_mapping_to_engine_config(self):
        c = Settings().to_config()
        self.assertEqual(c.cache_limit_bytes, 4 * (1 << 30))
        self.assertEqual(c.cache_back_seconds, 600.0)
        self.assertEqual((c.piece_timeout, c.hard_timeout, c.mpv_network_timeout), (20.0, 90.0, 150))
        self.assertEqual(c.encryption, "default")
        self.assertFalse(c.upnp, "the router must never be asked to open ports")
        q = Settings(network="quick", encryption="always", cache_gb=10, keep_minutes=30).to_config()
        self.assertEqual((q.hard_timeout, q.encryption, q.cache_limit_bytes, q.cache_back_seconds), (20.0, "forced", 10 * (1 << 30), 1800.0))
        t = Settings().to_config(temporary=True)
        self.assertEqual(t.cache_limit_bytes, 0)

    def test_roundtrip_persistence(self):
        p = self.d / "s.json"
        Settings(cache_gb=7.5, keep_minutes=20, network="balanced", encryption="off", on_close="delete", tour_done=True).save(p)
        s = Settings.load(p)
        self.assertEqual((s.cache_gb, s.keep_minutes, s.network, s.encryption, s.on_close, s.tour_done), (7.5, 20.0, "balanced", "off", "delete", True))

    def test_damaged_file_never_prevents_start(self):
        p = self.d / "s.json"
        p.write_text("{not json")
        s = Settings.load(p)
        self.assertEqual(s, Settings())
        self.assertTrue((self.d / "s.json.bad").exists(), "the damaged file is kept for inspection, not deleted")

    def test_invalid_values_are_clamped_unknown_keys_ignored(self):
        p = self.d / "s.json"
        p.write_text(json.dumps({"cache_gb": -3, "keep_minutes": 9999, "network": "turbo", "encryption": 5, "on_close": "x", "future_key": 1}))
        s = Settings.load(p)
        self.assertEqual((s.cache_gb, s.keep_minutes, s.network, s.encryption, s.on_close), (0.5, 240.0, "patient", "auto", "keep"))

    def test_missing_file_gives_defaults(self):
        self.assertEqual(Settings.load(self.d / "nope.json"), Settings())


class RecentTests(unittest.TestCase):
    def test_order_progress_and_damage(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        r = RecentItems(d / "recent.json")
        r.touch("aa", "First", "a.torrent")
        r.touch("bb", "Second", "magnet:?x")
        r.touch("aa", "First", "a.torrent")
        self.assertEqual([i["infohash"] for i in r.items], ["aa", "bb"])
        r.update_position("aa", 3000, 3200)
        self.assertTrue(RecentItems(d / "recent.json").items[0]["watched"])
        (d / "recent.json").write_text("garbage")
        self.assertEqual(RecentItems(d / "recent.json").items, [])
        self.assertTrue((d / "recent.json.bad").exists())


class CacheDirTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_marker_and_guarded_delete(self):
        d = prepare_cache_dir(self.root, "ab" * 20)
        (d / "movie.mkv").write_bytes(b"x" * 10000)
        self.assertTrue((d / MARKER).exists())
        self.assertEqual(len(list_caches(self.root)), 1)
        state = self.root / "state"
        state.mkdir()
        (state / ("ab" * 20 + ".cache.json")).write_text("{}")
        freed = delete_managed_cache(self.root, d, state)
        self.assertGreaterEqual(freed, 0)
        self.assertFalse(d.exists())
        self.assertFalse((state / ("ab" * 20 + ".cache.json")).exists())

    def test_foreign_directories_are_never_adopted_or_deleted(self):
        foreign = self.root / ("cd" * 20)
        foreign.mkdir()
        (foreign / "precious.txt").write_text("mine")
        with self.assertRaises(CacheDirNotManagedError):
            prepare_cache_dir(self.root, "cd" * 20)
        with self.assertRaises(NotManaged):
            delete_managed_cache(self.root, foreign)
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / MARKER).write_text(json.dumps({"infohash": "zz"}))
        with self.assertRaises(NotManaged):                       # marked, but not a direct child of the cache root
            delete_managed_cache(self.root, outside)
        self.assertEqual((foreign / "precious.txt").read_text(), "mine")
        self.assertTrue(outside.exists())


class CacheDeletionIsConfined(unittest.TestCase):
    """A marker file is untrusted data: a hostile or damaged one must never steer deletion outside the cache root."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root, self.state = self.base / "root", self.base / "state"
        self.root.mkdir(); self.state.mkdir()
        self.victim = self.base / "victim.cache.json"
        self.victim.write_text("do not delete")

    def test_traversal_in_the_marker_infohash_is_refused(self):
        d = self.root / "evil"
        d.mkdir()
        (d / MARKER).write_text(json.dumps({"infohash": "../victim"}))
        (d / "data").write_text("x")
        with self.assertRaises(NotManaged):
            delete_managed_cache(self.root, d, self.state)
        self.assertEqual(self.victim.read_text(), "do not delete")
        self.assertTrue((d / "data").exists())

    def test_marker_must_match_the_directory_name(self):
        d = self.root / ("aa" * 20)
        d.mkdir()
        (d / MARKER).write_text(json.dumps({"infohash": "bb" * 20}))
        with self.assertRaises(NotManaged):
            delete_managed_cache(self.root, d, self.state)
        self.assertTrue(d.exists())

    def test_symlinked_directory_is_refused_and_target_survives(self):
        target = self.base / "target"
        target.mkdir()
        (target / MARKER).write_text(json.dumps({"infohash": "cc" * 20}))
        (target / "keep.txt").write_text("keep")
        link = self.root / ("cc" * 20)
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(NotManaged):
            delete_managed_cache(self.root, link, self.state)
        self.assertEqual((target / "keep.txt").read_text(), "keep")

    def test_invalid_infohash_never_becomes_a_directory(self):
        for bad in ("../x", "a/b", "", "ZZ" * 20, "ab" * 19):
            with self.assertRaises(CacheDirNotManagedError):
                prepare_cache_dir(self.root, bad)
        self.assertEqual([p.name for p in self.root.iterdir()], [])


class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-svc-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = media()["moov_front"]
        self.sd = Seeder(self.src, upload_limit=1_000_000)
        self.addCleanup(self.sd.close)
        self.torrent = self.tmp / "t.torrent"
        self.torrent.write_bytes(lt.bencode(lt.create_torrent(self.sd.ti).generate()))
        self.infohash = str(self.sd.ti.info_hash())
        self.settings = Settings(cache_root=str(self.tmp / "caches"))
        self.svc = EngineService(self.settings, state_directory=self.tmp / "state")
        self.svc.start()
        self.addCleanup(self.svc.shutdown)
        self.events: list = []
        self.kinds: list = []
        self.threads: set = set()

        def cb(kind, payload):
            self.threads.add(threading.get_ident())
            self.kinds.append(kind)
            if kind == "event":
                self.events.append(payload)
        self.svc.subscribe(cb)

    def opts(self, **kw):
        o = OpenOptions(peers=[("127.0.0.1", self.sd.port)], **kw)
        o.engine_overrides = dict(dht=False, lsd=False, listen=f"127.0.0.1:{free_port()}", limits_on_lan=True, metadata_timeout=15.0,
                                  min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0, readahead_s=0, urgent_s=0,
                                  assumed_bytes_per_s=2_000_000, wake_interval=1.0, cache_limit_bytes=kw_limit(kw),
                                  cache_back_seconds=0.0, cache_back_bytes=512 * 1024)
        o.engine_overrides.update(self.extra)
        return o

    extra: dict = {}

    def wait_event(self, code, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if any(e.code == code for e in self.events):
                return True
            time.sleep(0.1)
        return False


def kw_limit(kw):
    return 0 if kw.get("temporary") else 6 * MiB


class ServiceTests(ServiceCase):
    def test_open_serve_status_and_close_keep(self):
        m = self.svc.open(str(self.torrent), self.opts()).result(40)
        self.assertEqual((m.infohash, m.bounded, m.file_size), (self.infohash, True, self.src.stat().st_size))
        self.assertTrue(Path(m.cache_dir).is_dir() and (Path(m.cache_dir) / MARKER).exists())
        port = int(m.url.split(":")[2].split("/")[0])
        path = "/" + m.url.split("/", 3)[3]
        loop = asyncio.new_event_loop()
        st, h, body, *_ = loop.run_until_complete(http_range(port, path, "bytes=2000000-2299999", deadline_s=60))
        loop.close()
        self.assertEqual(body, self.src.read_bytes()[2000000:2300000])
        end = time.time() + 5
        while time.time() < end and self.svc.snapshot().get("phase") in ("opening", "idle"):
            time.sleep(0.1)
        s = self.svc.snapshot()
        for k in ("peers", "down_Bps", "cache_used", "cache_limit", "ahead_seconds", "pieces_have", "phase", "title"):
            self.assertIn(k, s)
        self.assertEqual(s["cache_limit"], 6 * MiB)
        self.svc.close_media().result(20)
        self.assertTrue(Path(m.cache_dir).exists(), "default policy keeps the data for resuming")
        self.assertIn("opened", self.kinds)
        self.assertIn("closed", self.kinds)
        self.assertEqual(self.threads, {self.svc.thread_ident}, "every callback must run on the engine thread, never on the caller's")
        self.assertNotEqual(self.svc.thread_ident, threading.get_ident())

    def test_delete_on_close_removes_only_the_managed_directory(self):
        self.svc.update_settings(Settings(cache_root=str(self.tmp / "caches"), on_close="delete"))
        keep = self.tmp / "caches" / "unrelated"
        keep.mkdir(parents=True)
        (keep / "mine.txt").write_text("keep me")
        m = self.svc.open(str(self.torrent), self.opts()).result(40)
        self.svc.close_media().result(20)
        self.assertFalse(Path(m.cache_dir).exists())
        self.assertEqual((keep / "mine.txt").read_text(), "keep me")

    def test_player_state_drives_the_playback_head(self):
        self.svc.open(str(self.torrent), self.opts()).result(40)
        self.svc.update_player(PlayerState(ts=time.monotonic(), time_pos=3.0, duration=120.0, fw_bytes=500_000))
        time.sleep(0.6)
        self.assertEqual(self.svc._session.sched.head_source(), "player")

    def test_availability_map_reflects_downloaded_regions(self):
        m = self.svc.open(str(self.torrent), self.opts()).result(40)
        port = int(m.url.split(":")[2].split("/")[0])
        loop = asyncio.new_event_loop()
        loop.run_until_complete(http_range(port, "/" + m.url.split("/", 3)[3], "bytes=7000000-7400000", deadline_s=60))
        loop.close()
        av = self.svc.availability(100)
        self.assertEqual(len(av), 100)
        mid = int(7_200_000 / m.file_size * 100)
        self.assertGreater(av[mid], 0.5)
        self.assertEqual(av[mid + 20] if mid + 20 < 100 else 0.0, 0.0)

    def test_unsupported_filesystem_gives_a_code_and_opt_in_temporary_mode_works(self):
        with mock.patch("lumiere.bounded_store.supports_punch", return_value=(False, "EOPNOTSUPP simulated")):
            with self.assertRaises(EngineError) as cm:
                self.svc.open(str(self.torrent), self.opts()).result(40)
        self.assertEqual(cm.exception.code, ev.CACHE_UNSUPPORTED_FS)
        self.assertTrue(any(e.code == ev.CACHE_UNSUPPORTED_FS and e.level == "error" for e in self.events))
        # explicit opt-in: no limit, deleted on close, flagged so the UI can warn
        m = self.svc.open(str(self.torrent), self.opts(temporary=True)).result(40)
        self.assertTrue(m.temporary and not m.bounded and m.cache_limit == 0)
        self.svc.close_media().result(20)
        self.assertFalse(Path(m.cache_dir).exists(), "temporary mode always deletes its data when closed")

    def test_foreign_cache_directory_is_refused_and_untouched(self):
        foreign = self.tmp / "caches" / self.infohash
        foreign.mkdir(parents=True)
        (foreign / "precious.bin").write_bytes(b"1234")
        with self.assertRaises(EngineError) as cm:
            self.svc.open(str(self.torrent), self.opts()).result(40)
        self.assertEqual(cm.exception.code, ev.CACHE_DIR_NOT_MANAGED)
        self.assertEqual((foreign / "precious.bin").read_bytes(), b"1234")

    def test_too_small_limit_and_unreadable_torrent_have_codes(self):
        self.extra = {"cache_limit_bytes": 1 * MiB, "pin_head_bytes": 1 * MiB}
        with self.assertRaises(EngineError) as cm:
            self.svc.open(str(self.torrent), self.opts()).result(40)
        self.assertEqual(cm.exception.code, ev.CACHE_TOO_SMALL)
        with self.assertRaises(EngineError) as cm:
            self.svc.open(str(self.tmp / "missing.torrent"), self.opts()).result(40)
        self.assertEqual(cm.exception.code, ev.OPEN_FAILED)

    def test_cancel_open_leaves_a_clean_idle_engine(self):
        magnet = f"magnet:?xt=urn:btih:{'ab' * 20}"                      # nobody has this: metadata never arrives
        o = OpenOptions()
        o.engine_overrides = dict(dht=False, lsd=False, listen=f"127.0.0.1:{free_port()}", metadata_timeout=60.0, cache_limit_bytes=6 * MiB)
        fut = self.svc.open(magnet, o)
        time.sleep(1.5)
        self.assertEqual(self.svc.snapshot()["phase"], "opening")
        self.svc.cancel_open()
        with self.assertRaises(Exception):
            fut.result(15)
        time.sleep(0.5)
        self.assertEqual(self.svc.snapshot()["phase"], "idle")
        self.assertIsNone(self.svc._session)
        m = self.svc.open(str(self.torrent), self.opts()).result(40)         # and it is immediately usable again
        self.assertTrue(m.url)

    def test_network_events_no_sources_lost_and_restored(self):
        self.svc.NET_LOST_AFTER = 1.5
        m = self.svc.open(str(self.torrent), self.opts()).result(40)
        port = int(m.url.split(":")[2].split("/")[0])
        path = "/" + m.url.split("/", 3)[3]

        async def reader():
            try:
                await http_range(port, path, "bytes=9000000-9999999", deadline_s=120)
            except Exception:
                pass
        t = threading.Thread(target=lambda: asyncio.run(reader()), daemon=True)
        end = time.time() + 20
        while time.time() < end and not (self.svc.snapshot().get("peers") or 0):
            time.sleep(0.2)
        # (sources must have been connected once; the first demand makes the engine dial the hinted peer)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(http_range(port, path, "bytes=1000000-1100000", deadline_s=60))
        loop.close()
        self.assertGreater(self.svc.snapshot().get("peers") or 0, 0)
        self.sd.pause()                                                  # every source disappears while data is wanted
        t.start()
        self.assertTrue(self.wait_event(ev.NETWORK_LOST, 40), [e.code for e in self.events])
        self.sd.resume()
        self.assertTrue(self.wait_event(ev.NETWORK_RESTORED, 60), [e.code for e in self.events])

    def test_no_sources_event_when_nobody_ever_connects(self):
        self.svc.NO_PEERS_AFTER = 2.0
        o = self.opts()
        o.peers = []                                                     # no hints, no DHT, no tracker: nobody to talk to
        self.svc.open(str(self.torrent), o).result(40)
        self.assertTrue(self.wait_event(ev.NO_PEERS, 15), [e.code for e in self.events])

    def test_cache_pressure_is_reported_as_an_event(self):
        m = self.svc.open(str(self.torrent), self.opts()).result(40)
        port = int(m.url.split(":")[2].split("/")[0])
        path = "/" + m.url.split("/", 3)[3]

        async def read_all():
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nRange: bytes=0-\r\n\r\n".encode())
            await r.readuntil(b"\r\n\r\n")
            end = time.time() + 40
            got = 0
            while time.time() < end:
                try:
                    got += len(await asyncio.wait_for(r.read(1 << 20), 0.25))
                except asyncio.TimeoutError:
                    pass
                # the player reports what it has consumed: the playhead follows the bytes the client has read
                self.svc.update_player(PlayerState(ts=time.monotonic(), time_pos=got / 125_000, duration=120.0, fw_bytes=0))
                if any(e.code == ev.CACHE_FULL for e in self.events):
                    break
            w.close()
        asyncio.run(read_all())
        self.assertTrue(any(e.code == ev.CACHE_FULL for e in self.events), [e.code for e in self.events])


class NetworkCheckTests(ServiceCase):
    def test_verdicts_are_tagged_and_never_claim_throttling(self):
        n = "lumiere.doctor.netprobe"
        with mock.patch(n + ".exit_info", return_value={"ip": "1.2.3.4"}), mock.patch(n + ".dns_udp", return_value=True), \
                mock.patch(n + ".dht_replies", return_value=(0, 4)), mock.patch(n + ".udp_tracker_replies", return_value=(0, 4)), \
                mock.patch(n + ".tcp_http_ports", return_value={6881: True, 51413: True}), mock.patch(n + ".default_route_iface", return_value="tun0"):
            r = self.svc.network_check().result(30)
        tags = dict((k, v) for v, k in r["verdicts"])
        self.assertEqual(tags["udp_bittorrent_no_answer"], "confirmed")
        self.assertEqual(tags["protocol_filtering_possible"], "hypothesis")
        self.assertEqual(tags["isp_throttling"], "not_measured")
        self.assertEqual(tags["vpn_in_path"], "observed")
        self.assertNotIn(("confirmed", "isp_throttling"), r["verdicts"])


if __name__ == "__main__":
    unittest.main()
