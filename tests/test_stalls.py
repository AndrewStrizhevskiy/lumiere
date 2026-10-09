# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the 'long seek' class of problems (a 54 s seek was seen once): stalled/lost block requests,
unreachable peers, reconnects, obsolete requests. Rule: no request waits indefinitely, obsolete requests go away."""
import asyncio
import random
import shutil
import statistics
import tempfile
import time
import unittest
from pathlib import Path

import libtorrent as lt

from kino_stream.config import KiB, MiB
from kino_stream.store import Demand
from kino_stream.lt_store import PersistentFileStore
from tests.support import Seeder, eventually, http_range, leech_config, media, open_stream, record

PL = 65536


class StallCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-stall-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = media()["moov_front"]
        self.data = self.src.read_bytes()

    async def stream(self, upload, **over):
        sd = Seeder(self.src, upload_limit=upload)
        self.addCleanup(sd.close)
        kw = dict(min_readahead_bytes=1 * MiB, mpv_cache_bytes=0, window_margin_bytes=0, readahead_s=0, urgent_s=2,
                  urgent_min_bytes=256 * KiB, assumed_bytes_per_s=200_000, piece_timeout=2.0, hard_timeout=40.0)
        kw.update(over)
        s = await open_stream(self.tmp, sd, self.src, **kw)
        self.addAsyncCleanup(s.close)
        return s, sd

    async def open_main(self, s, start):
        r, w = await asyncio.open_connection("127.0.0.1", s.server.port)
        w.write(f"GET {s.server.path} HTTP/1.1\r\nHost: 127.0.0.1:{s.server.port}\r\nRange: bytes={start}-\r\n\r\n".encode())
        await r.readuntil(b"\r\n\r\n")
        return r, w


def requested_blocks(handle) -> dict[int, int]:
    """piece -> number of blocks libtorrent currently has an outstanding request for"""
    out = {}
    for q in handle.get_download_queue():
        n = sum(1 for b in q["blocks"] if b["state"] == 1)
        if n:
            out[q["piece_index"]] = n
    return out


class SeekStorm(StallCase):
    async def test_forty_random_seeks_never_stall_and_cancel_obsolete_requests(self):
        s, sd = await self.stream(600_000)
        pm = s.store.piece_map
        rnd = random.Random(7)
        lat, leftovers = [], []
        prev = None
        for i in range(40):
            start = rnd.randrange(0, len(self.data) - 400_000)
            t0 = time.monotonic()
            r, w = await self.open_main(s, start)
            got = await asyncio.wait_for(r.readexactly(128 * KiB), 30)        # a stall > 30 s fails the test
            lat.append(time.monotonic() - t0)
            self.assertEqual(got, self.data[start:start + 128 * KiB], f"seek {i} to {start}")
            if prev is not None and rnd.random() < 0.5:
                prev.close()                                                  # sometimes the old connection lingers
            prev = w
            await asyncio.sleep(1.5)
            # obsolete requests: nothing requested outside the new window (+ pinned head/tail + small slack)
            head = s.sched.head_byte()
            lo, hi = (head // PL) - 2, (head + s.sched.window_bytes()) // PL + 2
            pinned = {p for lo_, hi_ in s.sched.pinned for p in pm.range_pieces(s.file_index, lo_, hi_)}
            stray = [p for p in requested_blocks(s.store.handle) if not (lo <= p <= hi) and p not in pinned]
            leftovers.append(len(stray))
        prev.close()
        self.assertEqual(s.server.stats["mismatches"], 0)
        self.assertLess(max(lat), 15.0, f"slowest seek {max(lat):.1f}s: {sorted(lat)[-5:]}")
        self.assertLessEqual(max(leftovers), 2, f"obsolete requests still outstanding 1.5 s after a seek: {leftovers}")
        record("seek_storm_40", {"p50_s": round(statistics.median(lat), 2), "p95_s": round(sorted(lat)[37], 2),
                                 "max_s": round(max(lat), 2), "max_stray_requests": max(leftovers),
                                 "restarts": s.store.stats()["restarts"], "stalls": s.server.stats["stalls"]})


class LostRequests(StallCase):
    async def test_black_holed_seeder_requests_are_cancelled_and_reissued(self):
        """Requests go out, then the seeder stops answering (rate 1 B/s): the piece stalls. Once the seeder recovers the
        stalled pieces must arrive promptly - via the forced cancel + re-request path - not after a 50-60 s timeout."""
        s, sd = await self.stream(800_000, piece_timeout=2.0, stuck_after=4.0)
        a, n = 6_000_000, 400_000
        # the connection must be established and carrying data (the pinned container head/tail has arrived) before the black hole
        self.assertTrue(await eventually(lambda: s.store.stats().get("pieces_have", 0) >= 20, 20))
        sd.set_upload_limit(1)                                                 # black hole
        req = asyncio.create_task(http_range(s.server.port, s.server.path, f"bytes={a}-{a + n - 1}", deadline_s=90))
        noticed = await eventually(lambda: s.server.stats["stalls"] >= 1, 15)
        self.assertTrue(noticed, f"stall must be noticed; server={s.server.stats} store={ {k: v for k, v in s.store.stats().items() if k in ('peers', 'pieces_have', 'restarts', 'total_download')} } "
                                 f"range=({a},{a + n - 1}) req_done={req.done()} piece_len={s.store.piece_map.piece_length} "
                                 f"have_in_range={[s.store.have(p_) for p_ in s.store.piece_map.range_pieces(s.file_index, a, a + n - 1)]}")
        self.assertFalse(req.done())
        self.assertTrue(await eventually(lambda: s.store.stats()["restarts"] >= 1, 20),
                        "a connected-but-silent peer must trigger the stuck-connection restart")
        t_fix = time.monotonic()
        sd.set_upload_limit(800_000)
        st, h, body, fb, el = await asyncio.wait_for(req, 40)
        self.assertEqual(body, self.data[a:a + n])
        recovery = time.monotonic() - t_fix
        self.assertLess(recovery, 15.0, f"took {recovery:.1f}s after the seeder came back")
        self.assertGreaterEqual(s.store.stats()["forced_reasserts"], 1)
        self.assertGreaterEqual(s.store.stats()["restarts"], 1, "a silent-but-connected peer must trigger the stuck-connection restart")
        record("black_hole_recovery_s", round(recovery, 2))

    async def test_no_request_waits_indefinitely_when_no_peer_ever_returns(self):
        s, sd = await self.stream(800_000, hard_timeout=8.0, piece_timeout=2.0)
        sd.pause()
        await asyncio.sleep(1)
        t0 = time.monotonic()
        st, h, body, fb, el = await http_range(s.server.port, s.server.path, "bytes=7000000-7199999", deadline_s=60)
        took = time.monotonic() - t0
        self.assertLess(took, 20, "the connection must be given up after hard_timeout, not hang")
        self.assertLess(len(body), 200_000, "never a complete-looking body")
        self.assertEqual(s.server.stats["aborted"], 1)
        self.assertTrue(await eventually(lambda: not s.sched.conns, 3), "scheduler must release the connection")
        self.assertEqual(s.store.applied() == {} or all(v[1] is None for v in s.store.applied().values()), True,
                         "no deadlines may remain for the abandoned request")

    async def test_peer_unreachable_after_idle_is_recovered_by_restart(self):
        """The libtorrent quirk: after 'finished' + disconnect the seeder stays a non-candidate forever."""
        sd = Seeder(self.src, upload_limit=800_000)
        self.addCleanup(sd.close)
        cfg = leech_config(self.tmp, sd, restart_after=3.0, wake_interval=1.0)
        store = await PersistentFileStore.open(cfg, sd.ti, self.tmp / "dl")
        self.addAsyncCleanup(store.close)
        store.apply_demand(Demand(deadlines={p: 100 + p for p in range(10, 14)}))
        self.assertTrue(await eventually(lambda: all(store.have(p) for p in range(10, 14)), 20))
        store.apply_demand(Demand())
        sd.pause()
        await asyncio.sleep(4)
        sd.resume()
        store.apply_demand(Demand(deadlines={p: 100 + p for p in range(120, 124)}))
        t0 = time.monotonic()
        self.assertTrue(await eventually(lambda: all(store.have(p) for p in range(120, 124)), 40),
                        f"never recovered: {store.stats()}")
        self.assertGreaterEqual(store.stats()["restarts"], 1)
        record("unreachable_peer_recovery_s", round(time.monotonic() - t0, 2))


class ForwardAndBackwardSeeks(StallCase):
    async def test_seeks_at_the_edges_of_the_file(self):
        s, sd = await self.stream(600_000)
        n = len(self.data)
        for label, start in (("near start", 100), ("near end", n - 300_000), ("start again", 0), ("middle", n // 2),
                             ("very end", n - 70_000), ("back to start", 1_000)):
            t0 = time.monotonic()
            r, w = await self.open_main(s, start)
            want = min(64 * KiB, n - start)
            got = await asyncio.wait_for(r.readexactly(want), 30)
            self.assertEqual(got, self.data[start:start + want], label)
            self.assertLess(time.monotonic() - t0, 15, label)
            w.close()
        self.assertEqual(s.server.stats["mismatches"], 0)


if __name__ == "__main__":
    unittest.main()
