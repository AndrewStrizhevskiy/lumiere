"""End-to-end: real libtorrent swarm -> kino-stream -> real mpv (headless), three container layouts.

Each run: start, play, seek forward, seek backward, check bytes/bounds, record startup and seek latency.
"""
import asyncio
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from kino_stream.config import KiB, MiB
from tests.support import Seeder, disk_usage, eventually, media, open_stream, record


@unittest.skipUnless(shutil.which("mpv") and shutil.which("ffmpeg"), "needs mpv and ffmpeg")
class PlayThroughMpv(unittest.IsolatedAsyncioTestCase):
    async def run_container(self, name: str):
        tmp = Path(tempfile.mkdtemp(prefix=f"ks-mpv-{name}-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = media()[name]
        size = src.stat().st_size
        sd = Seeder(src, upload_limit=1_500_000)
        self.addCleanup(sd.close)
        s = await open_stream(tmp, sd, src, readahead_s=8, min_readahead_bytes=1 * MiB + 512 * KiB, urgent_s=4,
                              urgent_min_bytes=256 * KiB, mpv_cache_bytes=1 * MiB, mpv_back_bytes=512 * KiB,
                              window_margin_bytes=512 * KiB)
        self.addAsyncCleanup(s.close)
        total = s.store.piece_map.num_pieces
        peak = 0

        t0 = time.monotonic()
        mpv = await s.play(headless=True, use_user_config=False)
        startup = await mpv.wait_playing(0.3, timeout=40)
        await mpv.wait_pos(3.0, timeout=30)
        duration = mpv.state.duration
        self.assertAlmostEqual(duration, 120, delta=2)
        self.assertEqual(s.sched.head_source(), "player", "mpv IPC must drive the playback head")
        peak = max(peak, disk_usage(tmp / "dl"))

        async def seek_to(t: float):
            before = len(mpv.events)
            t_cmd = time.monotonic()
            await mpv.seek(t)
            restart = None
            end = time.monotonic() + 40
            while time.monotonic() < end:
                ev = [e for e in mpv.events[before:] if e[1] == "playback-restart"]
                if ev:
                    restart = ev[0][0] - t_cmd
                    break
                await asyncio.sleep(0.02)
            self.assertIsNotNone(restart, "mpv never restarted playback after the seek")
            await mpv.wait_pos(t + 0.5, timeout=40)
            return restart, time.monotonic() - t_cmd - 0.5     # minus the half second of video we waited to see move

        fwd_restart, fwd_total = await seek_to(duration * 0.7)
        self.assertGreaterEqual(s.sched.counters["seeks"], 1)
        peak = max(peak, disk_usage(tmp / "dl"))
        pos_before_back = mpv.state.time_pos
        back_restart, back_total = await seek_to(15.0)
        peak = max(peak, disk_usage(tmp / "dl"))
        await asyncio.sleep(2.0)
        self.assertIsNone(mpv.proc.returncode, "mpv died during the test")
        self.assertGreater(mpv.state.time_pos, 16.0)

        st = s.store.stats()
        self.assertEqual(s.server.stats["mismatches"], 0, "served bytes differ from the original file")
        self.assertEqual(s.server.stats["aborted"], 0)
        self.assertEqual(st["hash_failed"], 0)
        self.assertEqual(st["alerts_dropped"], 0)
        frac = st["pieces_have"] / total
        self.assertLess(frac, 0.60, f"downloaded {st['pieces_have']}/{total} pieces: read-ahead is not bounded")
        probes = [e for e in s.sched.events if e[1] == "conn_open" and e[2]["kind"] == "probe"]
        res = {
            "startup_to_first_frame_s": round(startup, 2),
            "forward_seek_restart_s": round(fwd_restart, 2), "forward_seek_to_playing_s": round(fwd_total, 2),
            "backward_seek_restart_s": round(back_restart, 2), "backward_seek_to_playing_s": round(back_total, 2),
            "pieces_downloaded": st["pieces_have"], "pieces_total": total, "downloaded_fraction": round(frac, 3),
            "max_disk_bytes": peak, "file_bytes": size, "seeks_detected": s.sched.counters["seeks"],
            "probe_connections": len(probes), "http_requests": s.server.stats["requests"],
            "http_piece_waits": s.server.stats["piece_waits"], "stalls": s.server.stats["stalls"],
        }
        record(f"mpv_{name}", res)
        print(f"\n[{name}] {res}")

    async def test_mp4_moov_at_start(self):
        await self.run_container("moov_front")

    async def test_mp4_moov_at_end(self):
        await self.run_container("moov_end")

    async def test_mkv_cues_at_end(self):
        await self.run_container("mkv_cues_end")


@unittest.skipUnless(shutil.which("mpv") and shutil.which("ffmpeg"), "needs mpv and ffmpeg")
class BoundedCacheWithMpv(unittest.IsolatedAsyncioTestCase):
    async def test_playback_seek_and_back_seek_within_a_hard_6mib_cache(self):
        tmp = Path(tempfile.mkdtemp(prefix="ks-mpv-bounded-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = media()["moov_front"]
        sd = Seeder(src, upload_limit=1_500_000)
        self.addCleanup(sd.close)
        limit = 6 * MiB
        s = await open_stream(tmp, sd, src, cache_limit_bytes=limit, evict_min_interval=0.5, flush_interval=0.5,
                              readahead_s=8, min_readahead_bytes=1 * MiB, urgent_s=4, urgent_min_bytes=256 * KiB,
                              mpv_cache_bytes=1 * MiB, mpv_back_bytes=512 * KiB, window_margin_bytes=512 * KiB,
                              pin_head_bytes=256 * KiB, pin_tail_bytes=128 * KiB, cache_back_bytes=1 * MiB)
        self.addAsyncCleanup(s.close)
        peak = 0
        mpv = await s.play(headless=True, use_user_config=False)
        await mpv.wait_playing(0.3, timeout=40)
        for target in (None, 80.0, 10.0, 100.0, 5.0):
            if target is None:
                await mpv.wait_pos(25.0, timeout=60)
            else:
                await mpv.seek(target)
                await mpv.wait_pos(target + 2.0, timeout=60)
            for _ in range(10):
                peak = max(peak, disk_usage(tmp / "dl"))
                await asyncio.sleep(0.2)
        self.assertIsNone(mpv.proc.returncode)
        st = s.store.stats()
        self.assertLessEqual(peak, limit, f"allocated {peak} > limit {limit}")
        self.assertGreaterEqual(st["evictions"], 1)
        self.assertEqual(s.server.stats["mismatches"], 0)
        self.assertEqual(s.server.stats["aborted"], 0)
        record("bounded_cache_mpv_6MiB", {"peak": peak, "limit": limit, "evictions": st["evictions"],
                                           "rebuffers": mpv.rebuffers, "rebuffer_s": round(mpv.rebuffer_s, 1)})


@unittest.skipUnless(shutil.which("mpv") and shutil.which("ffmpeg"), "needs mpv and ffmpeg")
class SeederOutage(unittest.IsolatedAsyncioTestCase):
    async def test_playback_survives_a_seeder_outage_and_resumes(self):
        """Retry after temporarily unavailable pieces: seeder disappears for ~12 s mid-playback; mpv rebuffers, then plays on."""
        tmp = Path(tempfile.mkdtemp(prefix="ks-outage-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        src = media()["moov_front"]
        sd = Seeder(src, upload_limit=1_500_000)
        self.addCleanup(sd.close)
        s = await open_stream(tmp, sd, src, readahead_s=8, min_readahead_bytes=1 * MiB + 512 * KiB, urgent_s=4,
                              urgent_min_bytes=256 * KiB, mpv_cache_bytes=1 * MiB, mpv_back_bytes=512 * KiB,
                              window_margin_bytes=512 * KiB, piece_timeout=3.0, hard_timeout=60.0)
        self.addAsyncCleanup(s.close)
        mpv = await s.play(headless=True, use_user_config=False)
        await mpv.wait_playing(0.3, timeout=40)
        await mpv.wait_pos(20.0, timeout=40)              # mpv has buffered ahead of 20 s ...
        await mpv.seek(100)                               # ... then jump to a region that is certainly not downloaded
        sd.pause()                                        # the seeder vanishes before the data arrives
        await asyncio.sleep(12)
        self.assertIsNone(mpv.proc.returncode, "mpv must not die during the outage")
        stuck_pos = mpv.state.time_pos
        self.assertLess(stuck_pos or 0, 104, "playback should be stalled while pieces are missing")
        self.assertGreaterEqual(s.server.stats["stalls"], 1, "the stall must have been noticed and retried")
        sd.resume()
        t_back = time.monotonic()
        await mpv.wait_pos(103.0, timeout=60)
        self.assertEqual(s.server.stats["mismatches"], 0)
        self.assertEqual(s.server.stats["aborted"], 0)
        record("outage_12s_recovery_s", round(time.monotonic() - t_back, 2))


if __name__ == "__main__":
    unittest.main()
