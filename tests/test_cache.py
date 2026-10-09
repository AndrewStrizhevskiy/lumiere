# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 2: bounded cache, safe eviction, crash recovery. Local swarm only (no internet)."""
import asyncio
import hashlib
import os
import random
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import libtorrent as lt

from kino_stream.bounded_store import BoundedSparseStore
from kino_stream.cacheindex import CacheIndex, SimulatedCrash
from kino_stream.config import KiB, MiB
from kino_stream.piecemap import PieceMap
from kino_stream.punch import allocated_bytes, supports_punch
from kino_stream.store import Demand, StoreError
from tests.support import (Seeder, eventually, http_range, leech_config, media, open_stream, random_file, record)

PL = 64 * KiB


def piece_ok(ti, path: Path, p: int) -> bool:
    a = p * ti.piece_length()
    with open(path, "rb") as f:
        f.seek(a)
        return hashlib.sha1(f.read(ti.piece_size(p))).digest() == bytes(ti.hash_for_piece(p))


class CacheCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-cache-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = media()["moov_front"]
        self.sd = Seeder(self.src, upload_limit=0)
        self.addCleanup(self.sd.close)
        self.ti = self.sd.ti
        self.data_path = self.tmp / "dl" / self.src.name

    def cfg(self, **over):
        kw = dict(cache_limit_bytes=64 * MiB, evict_min_interval=0.2, flush_interval=0.3, wake_interval=1.0)
        kw.update(over)
        return leech_config(self.tmp, self.sd, **kw)

    async def open(self, select=0, **over) -> BoundedSparseStore:
        s = await BoundedSparseStore.open(self.cfg(**over), self.ti, self.tmp / "dl", select=select)
        self.addAsyncCleanup(self._close, s)
        return s

    async def _close(self, s):
        try:
            if s.session is not None:
                await s.close()
        except Exception:
            pass

    async def fill(self, s, pieces):
        pieces = list(pieces)
        s.apply_demand(Demand(deadlines={p: 100 + i for i, p in enumerate(pieces[:200])}))
        self.assertTrue(await eventually(lambda: all(s.have(p) for p in pieces), 40), "download did not finish")
        await s._flush_durable()

    def lt_have(self, s):
        return {i for i in range(s.piece_map.num_pieces) if s.handle.have_piece(i)}


class Eviction(CacheCase):
    async def test_evicted_pieces_leave_every_view_and_space_is_released(self):
        s = await self.open()
        await self.fill(s, range(20, 120))
        before = allocated_bytes(self.tmp / "dl")
        E = list(range(50, 80))
        self.assertTrue(await s.evict(E))
        keep = set(range(20, 120)) - set(E)
        self.assertFalse(any(s.have(p) for p in E))
        self.assertEqual(self.lt_have(s), keep, "libtorrent's have-state must equal the pieces that remain on disk")
        self.assertEqual(s.index.retained_set(), keep)
        self.assertTrue(all(piece_ok(self.ti, self.data_path, p) for p in keep), "a retained piece was damaged")
        self.assertTrue(piece_ok(self.ti, self.data_path, 49) and piece_ok(self.ti, self.data_path, 80))
        freed = before - allocated_bytes(self.tmp / "dl")
        self.assertGreaterEqual(freed, 0.95 * len(E) * PL, f"only {freed} bytes released")
        self.assertIsNone(s.index.txn)
        record("evict_30_pieces_txn_s", s.cache_stats["last_txn_s"])

    async def test_evicted_pieces_can_be_downloaded_again(self):
        s = await self.open()
        await self.fill(s, range(20, 80))
        E = list(range(30, 50))
        await s.evict(E)
        s.apply_demand(Demand(deadlines={p: 100 + i for i, p in enumerate(E)}))
        self.assertTrue(await eventually(lambda: all(s.have(p) for p in E), 40))
        self.assertTrue(all(piece_ok(self.ti, self.data_path, p) for p in E), "re-downloaded bytes must verify")

    async def test_read_of_evicted_piece_never_returns_zeros(self):
        s = await self.open()
        await self.fill(s, range(20, 60))
        await s.evict([30, 31, 32])
        from kino_stream.store import PieceUnavailable
        with self.assertRaises(PieceUnavailable):
            s.read(0, 30 * PL + 10, 100)
        self.assertEqual(s.read(0, 40 * PL, 100), self.src.read_bytes()[40 * PL:40 * PL + 100])

    async def test_only_pieces_exclusive_to_the_streamed_file_can_be_evicted(self):
        root = self.tmp / "multi"
        root.mkdir()
        random_file(root / "0_prefix.bin", 200_003, 1)
        vid = random_file(root / "1_video.mkv", 1_500_000, 2)
        random_file(root / "2_suffix.bin", 90_001, 3)
        sd = Seeder(root)
        self.addCleanup(sd.close)
        pm = PieceMap.from_torrent_info(sd.ti)
        vi = next(f.index for f in pm.files if f.path.endswith("1_video.mkv"))
        cfg = leech_config(self.tmp, sd, cache_limit_bytes=64 * MiB, evict_min_interval=0.2, flush_interval=0.3)
        s = await BoundedSparseStore.open(cfg, sd.ti, self.tmp / "dl2", select=vi)
        self.addAsyncCleanup(self._close, s)
        allv = list(pm.range_pieces(vi, 0, pm.files[vi].size - 1))
        await self.fill(s, allv)
        shared = [p for p in allv if pm.is_shared(p)]
        self.assertGreaterEqual(len(shared), 1, "the video shares a boundary piece with a neighbouring file")
        self.assertFalse(await s.evict(shared), "shared boundary pieces must never be evicted")
        excl = [p for p in allv if not pm.is_shared(p)]
        half = excl[::2]
        self.assertTrue(await s.evict(half))
        left = set(allv) - set(half)
        self.assertEqual(self.lt_have(s) & set(allv), left)
        vpath = self.tmp / "dl2" / pm.files[vi].path
        for p in sorted(left)[:40] + shared:                      # neighbours of punched pieces, boundary pieces
            a, b = pm.piece_span(p)
            owners = pm.owners(p)
            buf = bytearray()
            for fi, fa, fb in owners:
                fp = self.tmp / "dl2" / pm.files[fi].path
                if fp.exists():
                    with open(fp, "rb") as fh:
                        fh.seek(fa)
                        buf += fh.read(fb - fa)
            if len(owners) == 1:
                self.assertEqual(hashlib.sha1(bytes(buf)).digest(), bytes(sd.ti.hash_for_piece(p)), f"piece {p} damaged")


class Safety(CacheCase):
    async def test_peers_never_receive_or_see_an_evicted_piece(self):
        """An observer that can only download from the evicting node, while it evicts repeatedly."""
        s = await self.open(upload_limit=300_000)
        await self.fill(s, range(10, 130))
        s.apply_demand(Demand())                                     # nothing is wanted any more: evicted pieces stay evicted
        port = int(s.cfg.listen.rsplit(":", 1)[1])
        obs = lt.session({"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False, "enable_upnp": False,
                          "enable_natpmp": False, "allow_multiple_connections_per_ip": True, "min_reconnect_time": 0,
                          "max_failcount": 1000, "alert_mask": int(lt.alert.category_t.status_notification)})
        p = lt.add_torrent_params()
        p.ti, p.save_path = self.ti, str(self.tmp / "obs")
        p.flags = (p.flags & ~lt.torrent_flags.auto_managed & ~lt.torrent_flags.paused) | lt.torrent_flags.disable_pex
        h = obs.add_torrent(p)
        hash_failed = 0
        rnd = random.Random(3)
        leaked = []
        for cycle in range(4):
            retained = sorted(s.index.retained_set())
            E = rnd.sample(retained, 12)
            await s.evict(E)
            adv_end = time.monotonic() + 4
            while time.monotonic() < adv_end:
                h.connect_peer(("127.0.0.1", port))
                await asyncio.sleep(0.25)
                for a in obs.pop_alerts():
                    if isinstance(a, lt.hash_failed_alert):
                        hash_failed += 1
                for pi in h.get_peer_info():
                    if tuple(pi.ip) == ("127.0.0.1", port) and pi.pieces and sum(pi.pieces) > 0:
                        adv = {i for i, b in enumerate(pi.pieces) if b}
                        leaked += sorted(adv & (set(range(s.piece_map.num_pieces)) - s.index.retained_set()))
        have = {i for i in range(self.ti.num_pieces()) if h.have_piece(i)}
        self.assertEqual(hash_failed, 0, "a peer received corrupt data from us")
        self.assertEqual(leaked, [], "an evicted piece was advertised")
        self.assertTrue(have, "the observer must actually have downloaded something")
        obs_file = self.tmp / "obs" / self.src.name
        self.assertTrue(all(piece_ok(self.ti, obs_file, i) for i in have), "observer holds a corrupt piece")
        record("observer_pieces_received_during_evictions", len(have))

    async def test_unsupported_filesystem_fails_clearly_and_leaves_data_alone(self):
        d = self.tmp / "dl"
        d.mkdir()
        f = d / "precious.bin"
        f.write_bytes(os.urandom(100_000))
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        with mock.patch("kino_stream.bounded_store.supports_punch", return_value=(False, "EOPNOTSUPP simulated")):
            with self.assertRaises(StoreError) as cm:
                await BoundedSparseStore.open(self.cfg(), self.ti, d, select=0)
        self.assertIn("not possible", str(cm.exception))
        self.assertIn("EOPNOTSUPP", str(cm.exception))
        self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), digest)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["precious.bin"], "nothing else may be created")

    async def test_refuses_a_directory_with_data_but_no_index(self):
        d = self.tmp / "dl"
        d.mkdir()
        f = d / self.src.name
        f.write_bytes(os.urandom(300_000))
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        with self.assertRaises(StoreError) as cm:
            await BoundedSparseStore.open(self.cfg(), self.ti, d, select=0)
        self.assertIn("not managed", str(cm.exception))
        self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), digest)

    async def test_corrupt_index_retains_nothing_and_reclaims_space(self):
        s = await self.open()
        await self.fill(s, range(10, 60))
        await s.close()
        idx_path = next((self.tmp / "state").glob("*.cache.json"))
        idx_path.write_text("{ this is not json")
        s2 = await self.open()
        self.assertFalse(any(s2.have(p) for p in range(s2.piece_map.num_pieces)))
        self.assertEqual(self.lt_have(s2), set())
        self.assertLess(allocated_bytes(self.tmp / "dl"), 4 * PL, "orphaned data must be released")
        self.assertEqual(s2.cache_stats["index_dropped"], 1)

    async def test_startup_verification_drops_a_damaged_retained_piece(self):
        s = await self.open()
        await self.fill(s, range(10, 40))
        await s.close()
        with open(self.data_path, "r+b") as f:                    # bit rot / external modification while we were down
            f.seek(25 * PL + 100)
            f.write(b"\xff" * 50)
        s2 = await self.open(cache_verify_sample=1000)
        self.assertFalse(s2.have(25))
        self.assertEqual(s2.cache_stats["verify_failed"], 1)
        self.assertEqual(self.lt_have(s2), set(range(10, 40)) - {25})


CRASH_POINTS = ["before_journal", "after_journal", "after_doom", "after_remove", "mid_punch", "after_punch",
                "after_index_punched", "after_readd", "before_commit", "after_commit"]


class CrashRecovery(CacheCase):
    async def test_crash_at_every_stage_of_an_eviction_recovers_to_an_exact_state(self):
        E = list(range(40, 60))
        base = set(range(30, 80))
        for point in CRASH_POINTS:
            with self.subTest(crash_at=point):
                shutil.rmtree(self.tmp / "dl", True)
                shutil.rmtree(self.tmp / "state", True)
                s = await BoundedSparseStore.open(self.cfg(), self.ti, self.tmp / "dl", select=0)
                await self.fill(s, sorted(base))

                def hook(name, point=point):
                    if name == point:
                        raise SimulatedCrash(name)
                s.crash_hook = hook
                with self.assertRaises(SimulatedCrash):
                    await s.evict(E)
                await s.abandon()                                  # the process 'dies': no flush, no cleanup
                s2 = await BoundedSparseStore.open(self.cfg(), self.ti, self.tmp / "dl", select=0)
                try:
                    expected = base if point == "before_journal" else base - set(E)
                    self.assertEqual(self.lt_have(s2), expected, "libtorrent must start with exactly the surviving pieces")
                    self.assertEqual({p for p in range(231) if s2.have(p)}, expected)
                    self.assertEqual(s2.index.retained_set(), expected)
                    self.assertIsNone(s2.index.txn, "the journal must be closed after recovery")
                    self.assertTrue(all(piece_ok(self.ti, self.data_path, p) for p in expected), "damaged survivor")
                    if point not in ("before_journal", "after_commit"):
                        self.assertEqual(s2.cache_stats["recovered_txn"], 1)
                    if point != "before_journal":
                        # evicted space really is released, and the pieces can be fetched again
                        self.assertLess(allocated_bytes(self.tmp / "dl"), (len(expected) + 4) * PL)
                        s2.apply_demand(Demand(deadlines={p: 100 + i for i, p in enumerate(E)}))
                        self.assertTrue(await eventually(lambda: all(s2.have(p) for p in E), 30))
                        self.assertTrue(all(piece_ok(self.ti, self.data_path, p) for p in E))
                finally:
                    await s2.close()

    async def test_journal_beats_stale_resume_data(self):
        """Resume data written BEFORE the eviction claims the evicted pieces; it must be ignored."""
        s = await self.open()
        await self.fill(s, range(20, 60))
        stale = self.tmp / "state" / f"{s._infohash}.resume"
        from kino_stream.lt_store import PersistentFileStore
        self.assertTrue(await PersistentFileStore._save_resume(s), "could not create the stale resume file")
        E = list(range(30, 40))
        s.crash_hook = lambda n: (_ for _ in ()).throw(SimulatedCrash(n)) if n == "after_punch" else None
        with self.assertRaises(SimulatedCrash):
            await s.evict(E)
        await s.abandon()
        s2 = await self.open()
        self.assertTrue(stale.exists(), "the stale resume file is on disk and claims the evicted pieces")
        self.assertEqual(self.lt_have(s2), set(range(20, 60)) - set(E))


class CacheLimit(CacheCase):
    async def test_hard_limit_is_never_exceeded_while_streaming_the_whole_file_and_back_window_is_kept(self):
        limit = 6 * MiB
        s = await open_stream(self.tmp, self.sd, self.src, cache_limit_bytes=limit, evict_min_interval=0.5,
                              flush_interval=0.3, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0, window_margin_bytes=0,
                              readahead_s=0, urgent_s=0, urgent_min_bytes=256 * KiB, assumed_bytes_per_s=2_500_000,
                              pin_head_bytes=256 * KiB, pin_tail_bytes=128 * KiB, cache_back_bytes=768 * KiB)
        self.addAsyncCleanup(s.close)
        data = self.src.read_bytes()
        port, path = s.server.port, s.server.path
        peak = 0
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nRange: bytes=0-\r\n\r\n".encode())
        await r.readuntil(b"\r\n\r\n")
        got = bytearray()
        stop_at = int(len(data) * 0.7)
        t0 = time.monotonic()
        while len(got) < stop_at and time.monotonic() - t0 < 60:
            chunk = await asyncio.wait_for(r.read(256 * KiB), 30)
            got += chunk
            peak = max(peak, allocated_bytes(self.tmp / "dl"))
        self.assertEqual(bytes(got), data[:len(got)], "bytes served while evicting must match the source")
        st = s.store.stats()
        self.assertGreaterEqual(st["evictions"], 1, "a 6 MiB cache cannot hold 10 MiB of playback without evicting")
        self.assertLessEqual(peak, limit, f"allocated {peak} > limit {limit}")
        # the client stops reading; the head settles; the back window must still be on disk
        await asyncio.sleep(2.0)
        h = s.store._hint
        window = range(h.keep_lo, h.head_piece)          # (head_piece itself is the next piece to be sent)
        missing = [p for p in window if not s.store.have(p)]
        self.assertEqual(missing, [], f"the backward-seek window was evicted: window {h.keep_lo}..{h.head_piece}, hint {h}")
        # seek back INSIDE the window: served from disk, nothing re-downloaded
        head_b = s.sched.head_byte()
        start = head_b - 300 * KiB
        d0 = s.store.stats()["total_download"]
        st2, hd, body, fb, el = await http_range(port, path, f"bytes={start}-{start + 99_999}", deadline_s=30)
        self.assertEqual(body, data[start:start + 100_000])
        self.assertLess(s.store.stats()["total_download"] - d0, 3 * PL, "in-window seek must not re-download")
        # seek back far OUTSIDE the window: evicted, so it is downloaded again - and correct
        self.assertFalse(s.store.have(60), "piece 60 should have been evicted by now")
        d1 = s.store.stats()["total_download"]
        st3, hd, body, fb, el = await http_range(port, path, f"bytes={60 * PL}-{60 * PL + 199_999}", deadline_s=60)
        self.assertEqual(body, data[60 * PL:60 * PL + 200_000])
        self.assertGreater(s.store.stats()["total_download"] - d1, 150 * KiB, "evicted data must have been fetched again")
        w.close()
        self.assertEqual(s.server.stats["mismatches"], 0)
        record("cache_limit_6MiB_stream_15MB", {"peak_allocated": peak, "limit": limit, "evictions": st["evictions"],
                                                  "pieces_evicted": st["pieces_evicted"], "last_txn_s": st["last_txn_s"]})

    async def test_limit_that_cannot_hold_the_window_is_rejected_with_a_clear_message(self):
        with self.assertRaises(ValueError) as cm:
            await open_stream(self.tmp, self.sd, self.src, cache_limit_bytes=1 * MiB, pin_head_bytes=1 * MiB)
        self.assertIn("too small", str(cm.exception))

    async def test_http_range_works_during_an_eviction(self):
        s = await open_stream(self.tmp, self.sd, self.src, cache_limit_bytes=48 * MiB, min_readahead_bytes=2 * MiB,
                              mpv_cache_bytes=0, window_margin_bytes=0, readahead_s=0, urgent_s=0, assumed_bytes_per_s=5_000_000,
                              evict_min_interval=0.2, flush_interval=0.3)
        self.addAsyncCleanup(s.close)
        data = self.src.read_bytes()
        st, h, body, *_ = await http_range(s.server.port, s.server.path, f"bytes={2_000_000}-{2_299_999}", deadline_s=30)
        self.assertEqual(body, data[2_000_000:2_300_000])
        a = 2_000_000 // PL
        E = list(range(a, a + 5))
        ev = asyncio.create_task(s.store.evict(E))
        await asyncio.sleep(0.15)                                    # the transaction is in progress
        st, h, body, *_ = await http_range(s.server.port, s.server.path, f"bytes={2_000_000}-{2_299_999}", deadline_s=60)
        self.assertEqual(body, data[2_000_000:2_300_000], "evicted range requested during/after eviction must still be correct")
        self.assertTrue(await ev)
        self.assertEqual(s.server.stats["mismatches"], 0)
        self.assertEqual(s.server.stats["aborted"], 0)


class BoundedMagnet(CacheCase):
    async def test_bounded_cache_works_with_a_magnet_link_and_survives_a_restart(self):
        from kino_stream.session import StreamSession
        ih = str(self.ti.info_hash())
        magnet = f"magnet:?xt=urn:btih:{ih}&dn=t&x.pe=127.0.0.1:{self.sd.port}"
        cfg = self.cfg(cache_limit_bytes=48 * MiB, verify_source=self.src, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0,
                       window_margin_bytes=0)
        s = await StreamSession.open(cfg, magnet, self.tmp / "dl")
        st, h, body, *_ = await http_range(s.server.port, s.server.path, "bytes=3000000-3399999", deadline_s=60)
        self.assertEqual(body, self.src.read_bytes()[3000000:3400000])
        await s.close()
        self.assertTrue(list((self.tmp / "state").glob("*.cache.json")))
        cfg2 = self.cfg(cache_limit_bytes=48 * MiB, verify_source=self.src, min_readahead_bytes=2 * MiB, mpv_cache_bytes=0,
                        window_margin_bytes=0)
        s2 = await StreamSession.open(cfg2, magnet, self.tmp / "dl")
        self.addAsyncCleanup(s2.close)
        d0 = s2.store.stats().get("total_download", 0)
        st, h, body, *_ = await http_range(s2.server.port, s2.server.path, "bytes=3000000-3399999", deadline_s=60)
        self.assertEqual(body, self.src.read_bytes()[3000000:3400000])
        self.assertLess(s2.store.stats().get("total_download", 0) - d0, 3 * PL, "retained pieces must be reused after a restart")


class IndexUnit(unittest.TestCase):
    def test_atomic_roundtrip_and_journal_states(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        i = CacheIndex(d / "i.json", "abc", 10, 100)
        i.add_retained([1, 2, 3, 4])
        i.save()
        i.begin_txn([2, 3])
        j = CacheIndex.load(d / "i.json", "abc", 10, 100)
        self.assertEqual(j.txn["state"], "begin")
        self.assertEqual(j.retained_set(), {1, 2, 3, 4})
        j.mark_punched()
        k = CacheIndex.load(d / "i.json", "abc", 10, 100)
        self.assertEqual((k.txn["state"], k.retained_set()), ("punched", {1, 4}))
        k.commit()
        self.assertIsNone(CacheIndex.load(d / "i.json", "abc", 10, 100).txn)
        self.assertTrue(CacheIndex.load(d / "i.json", "WRONG", 10, 100).corrupt)
        self.assertFalse((d / "i.json.tmp").exists())

    def test_hole_punching_probe_is_honest(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        ok, why = supports_punch(d)
        self.assertTrue(ok, why)
        self.assertEqual(list(d.iterdir()), [], "the probe must clean up after itself")


if __name__ == "__main__":
    unittest.main()
