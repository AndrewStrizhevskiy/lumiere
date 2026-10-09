"""Real libtorrent against a local, throttled seeder: tracker-less, DHT-less, no internet."""
import asyncio
import random
import tempfile
import time
import unittest
from pathlib import Path

from kino_stream.config import KiB, MiB
from kino_stream.lt_store import PersistentFileStore
from kino_stream.store import Demand
from tests.support import (Seeder, disk_usage, eventually, http_range, leech_config, media, open_stream, random_file,
                           record, sha)


class SwarmCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ks-test-")
        self.tmp = Path(self._tmp.name)
        self.media = media()
        self.cleanups = []

    def tearDown(self):
        self._tmp.cleanup()

    async def asyncTearDown(self):
        for c in reversed(self.cleanups):
            r = c()
            if asyncio.iscoroutine(r):
                await r

    async def stream(self, name="moov_front", upload=0, **over):
        src = self.media[name]
        sd = Seeder(src, upload_limit=upload)
        self.cleanups.append(sd.close)
        s = await open_stream(self.tmp, sd, src, **over)
        self.cleanups.append(s.close)
        return s, sd, src


class SlowSeeder(SwarmCase):
    async def test_http_waits_for_pieces_from_a_slow_seeder(self):
        """#1: HTTP request -> scheduler -> piece deadline -> wait -> piece arrives -> bytes sent."""
        s, sd, src = await self.stream(upload=150_000, min_readahead_bytes=1 * MiB, mpv_cache_bytes=0, window_margin_bytes=0)
        await asyncio.sleep(1.0)                                             # let the pinned head/tail trickle in
        a, n = 8_000_000, 600_000
        req = asyncio.create_task(http_range(s.server.port, s.server.path, f"bytes={a}-{a + n - 1}"))
        await asyncio.sleep(0.5)
        self.assertFalse(req.done(), "must still be waiting for pieces")
        dl = {p: v for p, v in s.store.applied().items() if v[1] is not None}
        first = a // 65536
        self.assertTrue(dl, "deadlines must be set in libtorrent")
        mine = [p for p in dl if first <= p <= first + 10]                   # (the first one may have arrived already)
        self.assertTrue(mine, "the requested pieces must be time-critical")
        self.assertTrue(all(dl[p][0] == 7 for p in mine))
        st, hdrs, body, fb, el = await asyncio.wait_for(req, 60)
        self.assertEqual(body, src.read_bytes()[a:a + n])
        self.assertGreater(el, 2.0, "600 KB at 150 KB/s cannot arrive instantly")
        self.assertGreaterEqual(s.server.stats["piece_waits"], 1)
        self.assertEqual(s.server.stats["mismatches"], 0)
        self.assertEqual(s.store.stats()["hash_failed"], 0)
        record("slow_seeder_600KB_at_150KBps_seconds", round(el, 2))


class Correctness(SwarmCase):
    async def test_random_ranges_match_original_bytes(self):
        """#5 part 1."""
        s, sd, src = await self.stream(min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0)
        data = src.read_bytes()
        rnd = random.Random(11)
        for _ in range(25):
            a = rnd.randrange(len(data) - 1)
            n = rnd.choice([1, 17, 4095, 65535, 65536, 65537, 200_000])
            b = min(len(data) - 1, a + n - 1)
            st, h, body, *_ = await http_range(s.server.port, s.server.path, f"bytes={a}-{b}", deadline_s=60)
            self.assertEqual((st, body == data[a:b + 1]), (206, True), f"range {a}-{b}")
        self.assertEqual(s.server.stats["mismatches"], 0)

    async def test_whole_file_sequential_read_matches_hash(self):
        """#5 part 2: every byte of the file, through one open-ended request, hashes like the source."""
        s, sd, src = await self.stream(assumed_bytes_per_s=100 * MiB)      # fast virtual clock: window never binds
        st, h, body, *_ = await http_range(s.server.port, s.server.path, "bytes=0-", deadline_s=120)
        import hashlib
        self.assertEqual(hashlib.sha256(body).hexdigest(), sha(src))
        self.assertEqual(s.server.stats["mismatches"], 0)


class BoundedReadahead(SwarmCase):
    async def test_open_ended_range_cannot_download_the_torrent(self):
        """#4: Range: N- with a fast seeder; only the window (+pins) is ever downloaded; disk usage stays bounded."""
        s, sd, src = await self.stream(min_readahead_bytes=1 * MiB, mpv_cache_bytes=0, window_margin_bytes=0,
                                       assumed_bytes_per_s=20_000, urgent_min_bytes=256 * KiB, readahead_s=0, urgent_s=0)
        total_pieces = s.store.piece_map.num_pieces
        start = 6_000_000
        reader, writer = await asyncio.open_connection("127.0.0.1", s.server.port)
        writer.write(f"GET {s.server.path} HTTP/1.1\r\nHost: 127.0.0.1:{s.server.port}\r\nRange: bytes={start}-\r\n\r\n".encode())
        await reader.readuntil(b"\r\n\r\n")
        got, peak, t0 = 0, 0, time.monotonic()
        while time.monotonic() - t0 < 7:
            try:
                c = await asyncio.wait_for(reader.read(1 << 20), 0.25)
                got += len(c)
            except asyncio.TimeoutError:
                pass
            peak = max(peak, disk_usage(self.tmp / "dl"))
        writer.close()
        have = s.store.stats()["pieces_have"]
        pin_pieces = -(-(1 * MiB + 512 * KiB) // 65536) + 1
        window_pieces = (1 * MiB) // 65536
        slack = 20_000 * 7 // 65536 + 6
        self.assertLessEqual(got, 1 * MiB + 20_000 * 8 + 256 * KiB)
        self.assertLessEqual(have, pin_pieces + window_pieces + slack, f"downloaded {have}/{total_pieces} pieces")
        self.assertLess(have, total_pieces * 0.25)
        self.assertLess(sd.uploaded, 0.25 * src.stat().st_size)
        self.assertLess(peak, 0.30 * src.stat().st_size)
        record("bounded_readahead", {"pieces_downloaded": have, "pieces_total": total_pieces,
                                     "max_disk_bytes": peak, "file_bytes": src.stat().st_size, "http_bytes_sent": got})


class Seeking(SwarmCase):
    async def test_forward_then_backward_seek_reprioritises_and_reuses(self):
        """#2 and #3 against real libtorrent."""
        s, sd, src = await self.stream(upload=400_000, min_readahead_bytes=1 * MiB, mpv_cache_bytes=0,
                                       window_margin_bytes=0, assumed_bytes_per_s=50_000, urgent_min_bytes=256 * KiB,
                                       readahead_s=0, urgent_s=0)
        pm, store = s.store.piece_map, s.store
        data = src.read_bytes()
        port, path = s.server.port, s.server.path

        async def open_main(start):
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nRange: bytes={start}-\r\n\r\n".encode())
            await r.readuntil(b"\r\n\r\n")
            return r, w

        r1, w1 = await open_main(0)
        first = await asyncio.wait_for(r1.readexactly(300_000), 60)
        self.assertEqual(first, data[:300_000])
        self.assertTrue(await eventually(lambda: any(v[1] is not None for v in store.applied().values()), 5)
                        or s.sched.main is not None)
        old_region = {p for p in range(0, 40) if not store.have(p)}
        self.assertTrue(old_region, "test needs undownloaded pieces in the old window")

        # --- forward seek (mpv opens a new connection far away; the old one is still open at this point)
        t_seek = time.monotonic()
        r2, w2 = await open_main(9_000_000)
        got = await asyncio.wait_for(r2.readexactly(200_000), 60)
        seek_latency = time.monotonic() - t_seek
        self.assertEqual(got, data[9_000_000:9_200_000])
        self.assertEqual(s.sched.counters["seeks"], 1)
        ap = store.applied()
        new_first = 9_000_000 // 65536
        self.assertTrue(any(p in ap for p in range(new_first, new_first + 20)), "new region must be demanded")
        self.assertFalse(any(ap.get(p, (0, None))[1] is not None for p in old_region), "old deadlines must be cancelled")
        self.assertFalse(any(p in ap for p in old_region if not store.have(p) and p > 20), "old window is not wanted any more")
        w1.close()
        await asyncio.sleep(3)
        still_missing = [p for p in old_region if not store.have(p)]
        self.assertGreater(len(still_missing), len(old_region) // 2, "abandoned region must not keep downloading")
        # --- backward seek: pieces already on disk are reused, nothing is downloaded again
        before = store.stats()["total_download"]
        have_before = store.stats()["pieces_have"]
        w2.close()
        t_back = time.monotonic()
        r3, w3 = await open_main(0)
        again = await asyncio.wait_for(r3.readexactly(250_000), 60)
        back_latency = time.monotonic() - t_back
        self.assertEqual(again, data[:250_000])
        self.assertLess(back_latency, 0.5, "already downloaded data must be served immediately")
        self.assertLess(store.stats()["total_download"] - before, 150_000, "nothing re-downloaded for cached range")
        self.assertEqual(s.sched.counters["seeks"], 2)
        w3.close()
        record("seek_http_level", {"forward_first_200KB_s": round(seek_latency, 2), "backward_cached_250KB_s": round(back_latency, 3)})


class IdleRegression(SwarmCase):
    """#9: after ~10 s without demand libtorrent is 'finished' and drops the seeder; a new deadline must still work."""

    async def _idle_then_demand(self, **over):
        src = self.media["moov_front"]
        sd = Seeder(src, upload_limit=0)
        self.cleanups.append(sd.close)
        cfg = leech_config(self.tmp, sd, **over)
        store = await PersistentFileStore.open(cfg, sd.ti, self.tmp / "dl")
        self.cleanups.append(store.close)
        store.apply_demand(Demand(deadlines={10: 100, 11: 200}))
        self.assertTrue(await eventually(lambda: store.have(10) and store.have(11), 15), "initial demand must work")
        store.apply_demand(Demand())                                         # nothing wanted any more
        await asyncio.sleep(10)
        t0 = time.monotonic()
        store.apply_demand(Demand(deadlines={150: 100, 151: 200}))
        ok = await eventually(lambda: store.have(150) and store.have(151), 8)
        return store, ok, time.monotonic() - t0

    async def test_new_deadline_after_idle_period_downloads(self):
        store, ok, dt = await self._idle_then_demand()
        self.assertEqual(store.session.get_settings()["min_reconnect_time"], 0)
        self.assertTrue(ok, "a deadline set after 10 s idle did not download")
        record("idle10s_then_deadline_seconds", round(dt, 2))

    async def test_wake_alone_without_the_setting(self):
        """Documents the behaviour when only wake()/connect_peer() is relied on (min_reconnect_time left at libtorrent's 60)."""
        store, ok, dt = await self._idle_then_demand(min_reconnect_time=60)
        record("idle10s_with_min_reconnect_60_and_wake_ok", ok)
        print(f"\n[info] min_reconnect_time=60 + wake(): deadline after idle downloaded = {ok} ({dt:.1f}s)")


class Alerts(SwarmCase):
    async def test_no_alert_overflow_under_heavy_piece_traffic(self):
        """#11: 48 MiB in 16 KiB pieces (3072 piece_finished + 12k block alerts) over loopback with a narrow mask."""
        root = random_file(self.tmp / "big.bin", 48 * MiB, 3)
        sd = Seeder(root, piece_length=16 * KiB)
        self.cleanups.append(sd.close)
        cfg = leech_config(self.tmp, sd)
        store = await PersistentFileStore.open(cfg, sd.ti, self.tmp / "dl")
        self.cleanups.append(store.close)
        n = store.piece_map.num_pieces
        self.assertEqual(store.session.get_settings()["alert_queue_size"], cfg.alert_queue_size)
        store.apply_demand(Demand(wanted=set(range(n))))
        self.assertTrue(await eventually(lambda: store.stats()["pieces_have"] == n, 90), store.stats())
        st = store.stats()
        self.assertEqual(st["alerts_dropped"], 0)
        self.assertEqual(st["pieces_finished"], n)
        self.assertEqual(st["hash_failed"], 0)
        record("alerts_48MiB_16KiB_pieces", {"alerts": st["alerts"], "dropped": st["alerts_dropped"], "pieces": n})


class MultiFile(SwarmCase):
    async def test_shared_boundary_piece_is_downloaded_whole_and_correctly_attributed(self):
        root = self.tmp / "multi"
        root.mkdir()
        random_file(root / "0_prefix.bin", 200_003, 1)                       # not a multiple of the piece size
        vid = random_file(root / "1_video.mkv", 1_500_000, 2)
        random_file(root / "2_suffix.bin", 90_001, 3)
        sd = Seeder(root)
        self.cleanups.append(sd.close)
        s = await open_stream(self.tmp, sd, vid, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0)
        self.cleanups.append(s.close)
        pm = s.store.piece_map
        idx = {Path(f.path).name: f.index for f in pm.files}            # libtorrent orders files as the directory lists them
        vi, pi = idx["1_video.mkv"], idx["0_prefix.bin"]
        self.assertEqual(s.file_index, vi)                               # largest video file was picked
        shared = pm.range_pieces(vi, 0, 0)[0]
        self.assertTrue(pm.is_shared(shared))
        self.assertEqual({o[0] for o in pm.owners(shared)} - {vi}, {pi, } if pm.files[pi].end == pm.files[vi].start else {idx["2_suffix.bin"]})
        st, h, body, *_ = await http_range(s.server.port, s.server.path, "bytes=0-1499999", deadline_s=60)
        self.assertEqual(body, vid.read_bytes())
        self.assertTrue(s.store.have(shared))                                # the whole shared piece came down...
        for other in (pi, idx["2_suffix.bin"]):
            rest = [p for p in pm.range_pieces(other, 0, pm.files[other].size - 1) if not any(o[0] == vi for o in pm.owners(p))]
            self.assertFalse(any(s.store.have(p) for p in rest), "...but the rest of the neighbouring files did not")
        self.assertEqual(s.server.stats["mismatches"], 0)


class Resume(SwarmCase):
    async def test_resume_data_keeps_progress(self):
        src = self.media["moov_front"]
        sd = Seeder(src)
        self.cleanups.append(sd.close)
        cfg = leech_config(self.tmp, sd)
        store = await PersistentFileStore.open(cfg, sd.ti, self.tmp / "dl")
        store.apply_demand(Demand(deadlines={p: 100 + p for p in range(30, 40)}))
        self.assertTrue(await eventually(lambda: all(store.have(p) for p in range(30, 40)), 20))
        await store.close()
        self.assertTrue(list((cfg.state_dir).glob("*.resume")))
        cfg2 = leech_config(self.tmp, sd, state_dir=cfg.state_dir)
        store2 = await PersistentFileStore.open(cfg2, sd.ti, self.tmp / "dl")
        self.cleanups.append(store2.close)
        self.assertTrue(all(store2.have(p) for p in range(30, 40)), "progress lost across restart")
        self.assertEqual(store2.stats()["total_download"], 0)
        data = src.read_bytes()
        self.assertEqual(store2.read(0, 30 * 65536, 10 * 65536), data[30 * 65536:40 * 65536])


class NoSecondCopy(SwarmCase):
    async def test_single_data_file_no_partfile_leftovers(self):
        """#E: the downloaded bytes live in exactly one file (the final file); the HTTP layer serves that same file."""
        s, sd, src = await self.stream(min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0)
        await http_range(s.server.port, s.server.path, "bytes=3000000-3500000", deadline_s=60)
        files = [p for p in (self.tmp / "dl").rglob("*") if p.is_file()]
        names = sorted(p.name for p in files)
        self.assertEqual(names, [src.name], f"unexpected files on disk: {names}")
        alloc = disk_usage(self.tmp / "dl")
        have = s.store.stats()["pieces_have"]
        self.assertLessEqual(alloc, (have + 2) * 65536 + 1 * MiB)             # allocated ~ downloaded pieces, nothing duplicated
        record("no_second_copy", {"files": names, "allocated_bytes": alloc, "pieces_have": have,
                                  "apparent_bytes": files[0].stat().st_size})


class MagnetPath(SwarmCase):
    """magnet -> metadata exchange -> torrent added -> correct file selected -> HTTP bytes (no DHT, no tracker)."""

    async def test_magnet_end_to_end_multifile(self):
        root = self.tmp / "release"
        root.mkdir()
        (root / "readme.txt").write_text("not a video\n" * 100)
        random_file(root / "extras.bin", 3 * MiB, 1)                         # bigger than the video, but not a video
        vid = random_file(root / "movie.mkv", 1_200_000, 2)
        sd = Seeder(root)
        self.cleanups.append(sd.close)
        ih = str(sd.ti.info_hash())
        magnet = f"magnet:?xt=urn:btih:{ih}&dn=release&x.pe=127.0.0.1:{sd.port}"
        from kino_stream.session import StreamSession
        cfg = leech_config(self.tmp, sd, verify_source=vid, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0)
        t_open = time.monotonic()
        s = await StreamSession.open(cfg, magnet, self.tmp / "dl")            # accepted: metadata arrives from the swarm
        record("magnet_open_to_ready_s", round(time.monotonic() - t_open, 2))
        self.cleanups.append(s.close)
        pm = s.store.piece_map
        self.assertEqual(s.store._infohash, ih, "the torrent we added is the one the magnet named")          # right torrent
        self.assertEqual(sorted(Path(f.path).name for f in pm.files), ["extras.bin", "movie.mkv", "readme.txt"])  # metadata
        self.assertEqual(Path(pm.files[s.file_index].path).name, "movie.mkv")  # video identified (not the larger .bin)
        st, h, body, fb, el = await http_range(s.server.port, s.server.path, "bytes=0-1199999", deadline_s=60)   # streaming
        self.assertEqual(body, vid.read_bytes())
        self.assertEqual(s.server.stats["mismatches"], 0)
        files = {p.name: p for p in (self.tmp / "dl").rglob("*") if p.is_file()}
        # unselected files may exist as sparse stubs (they share boundary pieces with the movie) but hold ~no data
        for name in ("extras.bin", "readme.txt"):
            if name in files:
                self.assertLessEqual(files[name].stat().st_blocks * 512, 2 * 65536 + 8192, f"{name} was downloaded")
        self.assertGreaterEqual(files["movie.mkv"].stat().st_blocks * 512, 1_200_000)


if __name__ == "__main__":
    unittest.main()
