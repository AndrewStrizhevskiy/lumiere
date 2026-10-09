# SPDX-License-Identifier: GPL-3.0-or-later
"""Several seeders with different speeds: libtorrent must keep the stream going when peers come and go, and the
scheduler must not depend on one particular peer. Also: lost alerts must never leave an HTTP request waiting forever."""
import asyncio
import random
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from kino_stream.config import KiB, MiB
from kino_stream.store import Demand
from tests.support import Seeder, eventually, http_range, leech_config, media, open_stream, record, sha


class MultiPeer(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-mp-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)      # registered first => runs last, after the stores are closed
        self.src = media()["moov_front"]
        self.data = self.src.read_bytes()

    async def stream(self, seeders, **over):
        kw = dict(min_readahead_bytes=1 * MiB, mpv_cache_bytes=0, window_margin_bytes=0, readahead_s=0, urgent_s=0,
                  assumed_bytes_per_s=10 * MiB, piece_timeout=2.0, hard_timeout=40.0)
        kw.update(over)
        s = await open_stream(self.tmp, seeders, self.src, **kw)
        self.addAsyncCleanup(s.close)
        return s

    def seeder(self, limit, **kw):
        sd = Seeder(self.src, upload_limit=limit, **kw)
        self.addCleanup(sd.close)
        return sd

    async def read_range(self, s, a, n, timeout=60):
        st, h, body, fb, el = await http_range(s.server.port, s.server.path, f"bytes={a}-{a + n - 1}", deadline_s=timeout)
        self.assertEqual(body, self.data[a:a + n], f"range {a}+{n}")
        return el

    async def test_one_peer_disappears(self):
        a, b, c = self.seeder(500_000), self.seeder(500_000), self.seeder(500_000)
        s = await self.stream([a, b, c])
        task = asyncio.create_task(self.read_range(s, 3_000_000, 2_000_000))
        await asyncio.sleep(1.5)
        c.close()                                                   # one of three vanishes mid-transfer
        el = await asyncio.wait_for(task, 60)
        self.assertEqual(s.server.stats["mismatches"], 0)
        record("multipeer_one_peer_lost_2MB_s", round(el, 2))

    async def test_fastest_peer_disappears(self):
        fast, mid, slow = self.seeder(1_500_000), self.seeder(400_000), self.seeder(200_000)
        s = await self.stream([fast, mid, slow])
        task = asyncio.create_task(self.read_range(s, 2_000_000, 3_000_000))
        await asyncio.sleep(1.5)
        fast.close()
        el = await asyncio.wait_for(task, 90)
        st = s.store.stats()
        self.assertGreaterEqual(st["peer_disconnects"], 1)
        self.assertEqual(s.server.stats["aborted"], 0)
        record("multipeer_fastest_lost_3MB_s", round(el, 2))

    async def test_bad_piece_from_one_peer_is_recovered_from_another(self):
        # Poisoned copy: same torrent, but piece 100 (and 101) are corrupted on the 'fast' seeder.
        good = self.seeder(300_000)
        bad_dir = self.tmp / "poison"
        bad_dir.mkdir()
        bad = bad_dir / self.src.name
        buf = bytearray(self.data)
        pl = good.ti.piece_length()
        for piece in (100, 101):
            buf[piece * pl + 17: piece * pl + 17 + 64] = b"\x00BADBAD\x00" * 7
        bad.write_bytes(buf)
        poisoned = Seeder(bad, upload_limit=3_000_000, ti=good.ti, data_parent=bad_dir, trust_data=True)
        self.addCleanup(poisoned.close)
        s = await self.stream([poisoned])                              # only the poisoned peer is known at first
        task = asyncio.create_task(self.read_range(s, 100 * pl, 3 * pl, timeout=90))
        self.assertTrue(await eventually(lambda: s.store.stats()["hash_failed"] >= 1, 20), "bad piece not detected")
        await asyncio.sleep(0.5)
        self.assertFalse(task.done(), "corrupt data must not be served while waiting for a good copy")
        s.store.cfg.peers.append(("127.0.0.1", good.port))             # a healthy peer shows up
        s.store.wake("good peer")
        el = await asyncio.wait_for(task, 90)
        st = s.store.stats()
        self.assertEqual(s.server.stats["mismatches"], 0, "corrupt bytes must never reach the player")
        record("multipeer_bad_piece", {"hash_failed": st["hash_failed"], "bans": st["bans"], "seconds": round(el, 2)})

    async def test_new_peer_joins_and_speeds_things_up(self):
        slow = self.seeder(200_000)
        s = await self.stream([slow], min_readahead_bytes=6 * MiB, window_margin_bytes=0)
        t0, d0 = time.monotonic(), s.store.stats()["total_download"]
        task = asyncio.create_task(self.read_range(s, 1_000_000, 5_000_000, timeout=120))
        await asyncio.sleep(4)
        rate_before = (s.store.stats()["total_download"] - d0) / (time.monotonic() - t0)
        fast = self.seeder(3_000_000)
        s.store.cfg.peers.append(("127.0.0.1", fast.port))          # e.g. learned via PEX / tracker / DHT
        s.store.wake("new peer")
        t1, d1 = time.monotonic(), s.store.stats()["total_download"]
        await asyncio.wait_for(task, 120)
        rate_after = (s.store.stats()["total_download"] - d1) / max(time.monotonic() - t1, 0.1)
        self.assertGreater(rate_after, rate_before * 2, f"{rate_before:.0f} -> {rate_after:.0f} B/s")
        record("multipeer_new_peer_rate_B_per_s", {"before": int(rate_before), "after": int(rate_after)})

    async def test_no_usable_peers_for_a_while_then_recovery(self):
        a, b = self.seeder(800_000), self.seeder(800_000)
        s = await self.stream([a, b], hard_timeout=60.0)
        task = asyncio.create_task(self.read_range(s, 5_000_000, 3_000_000, timeout=120))
        await asyncio.sleep(1.5)
        a.pause(); b.pause()                                          # every peer gone
        await asyncio.sleep(7)
        self.assertFalse(task.done())
        a.resume(); b.resume()
        el = await asyncio.wait_for(task, 90)
        st = s.store.stats()
        self.assertGreater(st["zero_peer_s"], 3, f"zero-peer time must be measured: {st['zero_peer_s']}")
        self.assertEqual(s.server.stats["aborted"], 0)
        record("multipeer_zero_peers_7s", {"zero_peer_s": st["zero_peer_s"], "total_s": round(el, 2),
                                           "disconnects": st["peer_disconnects"]})


class LostAlerts(unittest.IsolatedAsyncioTestCase):
    async def test_http_never_waits_forever_when_piece_alerts_are_lost(self):
        """Simulate the original bug: 60% of piece_finished notifications vanish. Reconciliation must still deliver."""
        tmp = Path(tempfile.mkdtemp(prefix="ks-lost-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = media()["moov_front"]
        sd = Seeder(src)
        self.addCleanup(sd.close)
        s = await open_stream(tmp, sd, src, min_readahead_bytes=4 * MiB, mpv_cache_bytes=0, window_margin_bytes=0,
                              readahead_s=0, urgent_s=0, assumed_bytes_per_s=10 * MiB, wake_interval=1.0)
        self.addAsyncCleanup(s.close)
        rnd = random.Random(1)
        orig = s.store._dispatch
        dropped = {"n": 0}

        def lossy(n, batch):
            kept = []
            for kind, v in batch:
                if kind == "piece" and rnd.random() < 0.6:
                    dropped["n"] += 1
                    continue
                kept.append((kind, v))
            orig(n, kept)
        s.store._dispatch = lossy
        st, h, body, *_ = await http_range(s.server.port, s.server.path, "bytes=2000000-5999999", deadline_s=60)
        self.assertEqual(body, src.read_bytes()[2000000:6000000])
        self.assertGreater(dropped["n"], 10, "the test must actually lose alerts")
        record("lost_alerts_recovered", {"dropped_piece_alerts": dropped["n"]})


if __name__ == "__main__":
    unittest.main()
