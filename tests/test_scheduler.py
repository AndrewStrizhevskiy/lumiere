# SPDX-License-Identifier: GPL-3.0-or-later
"""Scheduler logic on a fake store: no sockets, no libtorrent, deterministic clock."""
import asyncio
import unittest

from kino_stream.config import Config
from kino_stream.scheduler import PlayerState, Scheduler
from tests.support import FakeStore


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def make(size=100_000, **over):
    cfg = Config(readahead_s=0, min_readahead_bytes=10_000, mpv_cache_bytes=0, window_margin_bytes=0,
                 urgent_s=0, urgent_min_bytes=3_000, assumed_bytes_per_s=1_000, pin_head_bytes=2_000,
                 pin_tail_bytes=1_000, probe_max_bytes=5_000, seek_back_slack=500, seek_fwd_slack=500, chunk_bytes=1_000)
    for k, v in over.items():
        setattr(cfg, k, v)
    store = FakeStore([("movie.mkv", bytes(size))], piece_length=1_000)
    clk = Clock()
    return Scheduler(cfg, store, 0, clock=clk), store, clk


class Scheduling(unittest.TestCase):
    def test_before_any_request_only_container_head_and_tail_are_pinned(self):
        s, st, _ = make()
        d = st.demand
        self.assertEqual(d.pinned, {0, 1, 99})
        self.assertFalse(d.deadlines)
        self.assertFalse(d.wanted)

    def test_main_connection_gets_urgent_window_then_readahead(self):
        s, st, _ = make()
        s.open_connection(0, 99_999)
        d = st.demand
        self.assertEqual(sorted(d.deadlines)[:4], [0, 1, 2, 3])
        self.assertLess(d.deadlines[0], d.deadlines[3])                  # nearer pieces are more urgent
        self.assertEqual(sorted(d.wanted), list(range(4, 11)))           # up to head + 10_000
        self.assertEqual(d.pinned, {99})                                 # 0 and 1 already urgent
        self.assertNotIn(50, d.all_pieces())                             # an open-ended Range is NOT "download to EOF"

    def test_tail_probe_is_pinned_not_treated_as_playback(self):
        s, st, _ = make()
        s.open_connection(0, 99_999)
        probe = s.open_connection(99_900, 99_999)
        self.assertEqual(probe.kind, "probe")
        self.assertEqual(s.main.start, 0)                                # head still belongs to the main connection
        self.assertIn(99, st.demand.deadlines)                           # the probe's bytes are urgent
        s.close_connection(probe)
        self.assertNotIn(99, st.demand.deadlines)
        self.assertIn(99, st.demand.pinned)                              # but stay pinned

    def test_dynamic_pin_from_probe_beyond_default_tail(self):
        s, st, _ = make()
        c = s.open_connection(90_000, 94_999)                            # 5000 bytes: a probe, not at the very end
        self.assertEqual(c.kind, "probe")
        self.assertTrue(set(range(90, 95)) <= st.demand.pinned | set(st.demand.deadlines))
        s.close_connection(c)
        self.assertTrue(set(range(90, 95)) <= st.demand.pinned)

    def test_gate_limits_open_ended_request_and_opens_with_head(self):
        s, st, clk = make()
        c = s.open_connection(0, 99_999)
        self.assertEqual(s.gate_limit(c), 10_000)
        clk.t += 5                                                       # virtual playback: 1000 B/s
        self.assertEqual(s.head_byte(), 0)                               # head cannot pass what was sent
        c.pos = 10_000
        self.assertEqual(s.head_byte(), 5_000)
        self.assertEqual(s.gate_limit(c), 15_000)

    def test_player_state_is_authoritative_head(self):
        s, st, clk = make()
        c = s.open_connection(0, 99_999)
        c.pos = 30_000
        s.update_player(PlayerState(ts=clk.t, fw_bytes=8_000, time_pos=20.0, duration=100.0))
        self.assertEqual(s.head_source(), "player")
        self.assertEqual(s.head_byte(), 22_000)
        self.assertEqual(s.gate_limit(c), 32_000)
        clk.t += 10                                                      # sample goes stale -> virtual clock again
        self.assertEqual(s.head_source(), "virtual")

    def test_forward_seek_cancels_old_window_and_makes_new_one_urgent(self):
        s, st, clk = make()
        c1 = s.open_connection(0, 99_999)
        old = set(st.demand.deadlines) | st.demand.wanted
        self.assertIn(2, old)
        c2 = s.open_connection(70_000, 99_999)
        self.assertEqual(s.counters["seeks"], 1)
        self.assertTrue(c1.superseded)
        d = st.demand
        self.assertEqual(sorted(d.deadlines)[:4], [70, 71, 72, 73])
        for p in range(2, 40):                                           # the abandoned region is no longer wanted at all
            self.assertNotIn(p, d.all_pieces())
        self.assertEqual(s.gate_limit(c1), c1.pos)                       # the stale connection may not stream further

    def test_backward_seek(self):
        s, st, clk = make()
        s.open_connection(0, 99_999)
        s.open_connection(70_000, 99_999)
        s.open_connection(10_000, 99_999)
        self.assertEqual(s.counters["seeks"], 2)
        self.assertEqual(sorted(st.demand.deadlines)[:2], [10, 11])
        self.assertNotIn(75, st.demand.all_pieces())

    def test_reopen_inside_window_is_not_a_seek(self):
        s, st, clk = make()
        c1 = s.open_connection(0, 99_999)
        c1.pos = 4_000
        clk.t += 3
        s.open_connection(3_000, 99_999)                                 # mpv re-opens close to where it was
        self.assertEqual(s.counters["seeks"], 0)

    def test_closing_connections_drops_http_demand(self):
        s, st, clk = make()
        c = s.open_connection(40_000, 99_999)
        self.assertIn(40, st.demand.deadlines)
        s.close_connection(c)
        self.assertEqual(st.demand.deadlines, {})
        self.assertEqual(st.demand.wanted, set())
        self.assertEqual(st.demand.pinned, {0, 1, 99})

    def test_window_never_smaller_than_mpv_cache(self):
        s, st, _ = make(mpv_cache_bytes=30_000, window_margin_bytes=2_000)
        self.assertEqual(s.window_bytes(), 32_000)

    def test_hash_failure_forces_reassert(self):
        s, st, _ = make()
        s.open_connection(0, 99_999)
        before = len(st.forced)
        st.listeners[0]("hash_failed", 2)
        self.assertEqual(st.forced[-1], {2})
        self.assertGreater(len(st.forced), before)

    def test_stall_wakes_store(self):
        s, st, _ = make()
        s.open_connection(0, 99_999)
        s.note_stall([3])
        self.assertIn("stall", st.wakes)

    def test_short_file_smaller_than_pins(self):
        s, st, _ = make(size=1_500)
        self.assertTrue(st.demand.pinned <= {0, 1})


class Permit(unittest.IsolatedAsyncioTestCase):
    async def test_permit_waits_for_head_to_advance(self):
        s, st, clk = make()
        c = s.open_connection(0, 99_999)
        self.assertTrue(await s.permit(c, 10_000, lambda: True))
        task = asyncio.create_task(s.permit(c, 12_000, lambda: True))
        await asyncio.sleep(0.2)
        self.assertFalse(task.done())                                    # gated: beyond head + window
        c.pos = 10_000
        clk.t += 3                                                       # head 3000 -> limit 13000
        self.assertTrue(await asyncio.wait_for(task, 1))

    async def test_permit_returns_false_when_client_leaves(self):
        s, st, clk = make()
        c = s.open_connection(0, 99_999)
        alive = [True]
        task = asyncio.create_task(s.permit(c, 50_000, lambda: alive[0]))
        await asyncio.sleep(0.1)
        alive[0] = False
        self.assertFalse(await asyncio.wait_for(task, 1))


if __name__ == "__main__":
    unittest.main()
