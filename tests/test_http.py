"""HTTP Range server behaviour on a fake store (deterministic, no libtorrent)."""
import asyncio
import random
import time
import unittest

from kino_stream.config import Config
from kino_stream.httpd import RangeError, StreamServer, parse_range
from kino_stream.scheduler import Scheduler
from kino_stream.store import PieceUnavailable
from tests.support import FakeStore, eventually, http_range

SIZE = 300_000
DATA = random.Random(5).randbytes(SIZE)


def cfg(**over):
    c = Config(readahead_s=0, min_readahead_bytes=60_000, mpv_cache_bytes=0, window_margin_bytes=0, urgent_s=0,
               urgent_min_bytes=10_000, assumed_bytes_per_s=10_000, pin_head_bytes=1_000, pin_tail_bytes=1_000,
               probe_max_bytes=5_000, chunk_bytes=10_000, piece_timeout=0.3, hard_timeout=1.5, recompute_interval=0.05)
    for k, v in over.items():
        setattr(c, k, v)
    return c


class Rig:
    def __init__(self, **over):
        self.cfg = cfg(**over)
        self.store = FakeStore([("m.mkv", DATA)], piece_length=1_000)
        self.sched = Scheduler(self.cfg, self.store, 0)
        self.server = StreamServer(self.cfg, self.store, self.sched, 0, "tok")

    async def __aenter__(self):
        await self.server.start()
        self.task = asyncio.create_task(self.sched.run())
        return self

    async def __aexit__(self, *a):
        self.task.cancel()
        await self.server.close()

    async def get(self, rng, read=None, **kw):
        return await http_range(self.server.port, self.server.path, rng, read, **kw)


class RangeParsing(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_range(None, 100), (0, 99, False))
        self.assertEqual(parse_range("bytes=0-", 100), (0, 99, True))
        self.assertEqual(parse_range("bytes=10-19", 100), (10, 19, True))
        self.assertEqual(parse_range("bytes=90-500", 100), (90, 99, True))
        self.assertEqual(parse_range("bytes=-10", 100), (90, 99, True))
        self.assertEqual(parse_range("bytes=-500", 100), (0, 99, True))

    def test_unsatisfiable(self):
        for bad in ("bytes=100-", "bytes=50-10", "bytes=-0", "bytes=0-5,10-20", "items=0-1", "bytes=-", "garbage"):
            with self.assertRaises(RangeError, msg=bad):
                parse_range(bad, 100)


class Protocol(unittest.IsolatedAsyncioTestCase):
    async def test_status_codes_and_headers(self):
        async with Rig() as r:
            r.store.give_all()
            st, h, body, *_ = await r.get("bytes=1000-1999")
            self.assertEqual((st, h["content-range"], h["content-length"], h["accept-ranges"]), (206, f"bytes 1000-1999/{SIZE}", "1000", "bytes"))
            self.assertEqual(body, DATA[1000:2000])
            st, h, body, *_ = await r.get(None, read=500)
            self.assertEqual((st, h["content-length"]), (200, str(SIZE)))
            st, h, *_ = await r.get(f"bytes={SIZE}-")
            self.assertEqual((st, h["content-range"]), (416, f"bytes */{SIZE}"))
            st, *_ = await http_range(r.server.port, "/wrong/m.mkv", None)
            self.assertEqual(st, 404)
            st, *_ = await r.get(None, host_header="evil.example:80")
            self.assertEqual(st, 403)                                     # DNS-rebinding guard

    async def test_suffix_range_and_keepalive(self):
        async with Rig() as r:
            r.store.give_all()
            reader, writer = await asyncio.open_connection("127.0.0.1", r.server.port)
            for rng, want in (("bytes=0-99", DATA[:100]), ("bytes=-50", DATA[-50:]), ("bytes=200-299", DATA[200:300])):
                writer.write(f"GET {r.server.path} HTTP/1.1\r\nHost: 127.0.0.1:{r.server.port}\r\nRange: {rng}\r\n\r\n".encode())
                head = await reader.readuntil(b"\r\n\r\n")
                n = int(next(l.split(b":")[1] for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")))
                self.assertEqual(await reader.readexactly(n), want)
            writer.close()
            self.assertEqual(r.server.stats["requests"], 3)

    async def test_head_request(self):
        async with Rig() as r:
            reader, writer = await asyncio.open_connection("127.0.0.1", r.server.port)
            writer.write(f"HEAD {r.server.path} HTTP/1.1\r\nHost: 127.0.0.1:{r.server.port}\r\n\r\n".encode())
            head = await reader.readuntil(b"\r\n\r\n")
            self.assertIn(f"Content-Length: {SIZE}".encode(), head)
            writer.close()


class Waiting(unittest.IsolatedAsyncioTestCase):
    async def test_request_waits_for_missing_pieces_and_never_returns_zeros(self):
        async with Rig() as r:
            r.store.give(*range(0, 100), *range(150, 300))                # pieces 100..149 (bytes 100000-149999) missing
            t0 = time.monotonic()
            req = asyncio.create_task(r.get("bytes=105000-109999"))
            await asyncio.sleep(0.5)
            self.assertFalse(req.done(), "must wait, not answer with incomplete/zero data")
            self.assertIn(105, r.store.demand.deadlines)                  # the scheduler made the piece urgent
            r.store.give(*range(105, 110))
            st, h, body, first, el = await asyncio.wait_for(req, 3)
            self.assertEqual(body, DATA[105000:110000])
            self.assertGreaterEqual(first, 0.45)
            self.assertEqual(r.server.stats["piece_waits"], 1)

    async def test_partial_pieces_are_not_sent(self):
        async with Rig() as r:
            r.store.give(*range(0, 300))
            r.store._have[7] = False                                      # bytes 7000-7999 missing inside the range
            req = asyncio.create_task(r.get("bytes=5000-9999"))
            await asyncio.sleep(0.4)
            self.assertFalse(req.done())
            r.store.give(7)
            _, _, body, *_ = await asyncio.wait_for(req, 2)
            self.assertEqual(body, DATA[5000:10000])

    async def test_hard_timeout_aborts_instead_of_completing_with_garbage(self):
        async with Rig(hard_timeout=0.8) as r:
            r.store.give(*range(0, 300))
            r.store._have[20] = False
            st, h, body, *_ = await r.get("bytes=19000-21999")
            self.assertEqual(st, 206)
            self.assertLess(len(body), 3000)                              # short body: the client sees an error, not zeros
            self.assertEqual(body, DATA[19000:19000 + len(body)])
            self.assertEqual(r.server.stats["aborted"], 1)

    async def test_stall_reasserts_and_wakes(self):
        async with Rig(piece_timeout=0.2, hard_timeout=5) as r:
            r.store.give(*range(0, 300))
            r.store._have[30] = False
            req = asyncio.create_task(r.get("bytes=29500-30499"))
            await asyncio.sleep(0.8)
            self.assertIn("stall", r.store.wakes)
            self.assertGreaterEqual(r.server.stats["stalls"], 1)
            r.store.give(30)
            _, _, body, *_ = await asyncio.wait_for(req, 2)
            self.assertEqual(body, DATA[29500:30500])

    async def test_piece_lost_between_check_and_read_is_waited_for(self):
        async with Rig() as r:
            r.store.give_all()
            real = r.store.read
            calls = {"n": 0}

            def flaky(fi, off, n):
                calls["n"] += 1
                if calls["n"] == 1:
                    r.store._have[2] = False
                    raise PieceUnavailable([2])
                return real(fi, off, n)
            r.store.read = flaky
            req = asyncio.create_task(r.get("bytes=1500-2499"))
            await asyncio.sleep(0.4)
            self.assertFalse(req.done())
            r.store.give(2)
            _, _, body, *_ = await asyncio.wait_for(req, 2)
            self.assertEqual(body, DATA[1500:2500])


class Cancellation(unittest.IsolatedAsyncioTestCase):
    async def test_interrupted_connection_cancels_wait_and_demand(self):
        """#10: client vanishes while the server waits for a piece -> connection removed, deadlines dropped."""
        async with Rig() as r:
            r.store.give(*range(0, 40))
            reader, writer = await asyncio.open_connection("127.0.0.1", r.server.port)
            writer.write(f"GET {r.server.path} HTTP/1.1\r\nHost: 127.0.0.1:{r.server.port}\r\nRange: bytes=100000-\r\n\r\n".encode())
            await reader.readuntil(b"\r\n\r\n")
            self.assertTrue(await eventually(lambda: 100 in r.store.demand.deadlines, 2))
            self.assertEqual(len(r.sched.conns), 1)
            writer.close()
            self.assertTrue(await eventually(lambda: not r.sched.conns, 2), "connection must be released")
            self.assertEqual(r.store.demand.deadlines, {})
            self.assertEqual(r.store.demand.wanted, set())
            self.assertEqual(r.server.stats["disconnects"], 1)

    async def test_open_ended_range_is_bounded_by_the_window(self):
        """Range: bytes=N- must not stream to EOF: the server stops at head + window until the head moves."""
        async with Rig() as r:
            r.store.give_all()
            reader, writer = await asyncio.open_connection("127.0.0.1", r.server.port)
            writer.write(f"GET {r.server.path} HTTP/1.1\r\nHost: 127.0.0.1:{r.server.port}\r\nRange: bytes=50000-\r\n\r\n".encode())
            await reader.readuntil(b"\r\n\r\n")
            got = 0
            t0 = time.monotonic()
            while time.monotonic() - t0 < 1.2:
                try:
                    c = await asyncio.wait_for(reader.read(65536), 0.2)
                except asyncio.TimeoutError:
                    continue
                got += len(c)
            writer.close()
            # window 60_000 at 10_000 B/s virtual playback => at most 60_000 + 1.2 s * 10_000 + one chunk
            self.assertLessEqual(got, 60_000 + 12_000 + 10_000)
            self.assertGreaterEqual(got, 60_000)
            self.assertLess(got, SIZE - 50_000)


if __name__ == "__main__":
    unittest.main()
