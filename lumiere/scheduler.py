# SPDX-License-Identifier: GPL-3.0-or-later
"""Stream scheduler: decides which pieces matter and how far HTTP connections may run.

Concepts (kept apart on purpose):
  http_demand      what open HTTP connections need next (bytes at each connection's position)
  playback_head    byte offset the viewer is actually at. From the player when it reports fresh state
                   (head = bytes_sent_on_main_connection - mpv forward-cache bytes), otherwise from a virtual clock
                   that advances at the assumed bitrate from where the current main connection started.
                   It is NEVER "the last byte requested".
  window           how far ahead of the head we download *and* allow the main connection to stream
  pinned_ranges    container head/tail extents (moov / Cues / headers); extended by probe requests actually seen
  cached_pieces    owned by the PieceStore; asked via store.have()

A Range request reaching to EOF is not a request to download everything: the connection is gated at
head + window and released as the head moves.
"""
from __future__ import annotations

import asyncio
import collections
import itertools
import time
from dataclasses import dataclass, field
from typing import Callable

from .config import Config
from .piecemap import PieceMap
from .store import CacheTooSmallError, Demand, PieceStore, RetentionHint


@dataclass
class PlayerState:
    ts: float                          # monotonic time of the sample
    time_pos: float | None = None
    duration: float | None = None
    fw_bytes: int | None = None        # demuxer-cache-state/fw-bytes: bytes mpv holds ahead of the playback position
    paused: bool = False
    paused_for_cache: bool = False
    seeking: bool = False
    cache_speed: float | None = None


@dataclass
class Conn:
    id: int
    start: int                         # first byte (file offset)
    last: int                          # last byte, inclusive
    kind: str                          # "main" | "probe"
    opened_at: float
    pos: int = 0                       # next byte to send (bytes before it were handed to the socket)
    closed: bool = False
    superseded: bool = False

    @property
    def remaining(self) -> int:
        return self.last + 1 - self.pos


class Scheduler:
    def __init__(self, cfg: Config, store: PieceStore, file_index: int, clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.store = store
        self.pm: PieceMap = store.piece_map
        self.file_index = file_index
        self.size = self.pm.files[file_index].size
        self.clock = clock
        self._ids = itertools.count(1)
        self.conns: dict[int, Conn] = {}
        self.player: PlayerState | None = None
        self.expect_player = False     # True once a player with IPC is attached: then the clock never guesses the head
        self.pinned: list[tuple[int, int]] = [(0, min(cfg.pin_head_bytes, self.size) - 1)]
        if cfg.pin_tail_bytes and self.size > cfg.pin_head_bytes:
            self.pinned.append((max(0, self.size - cfg.pin_tail_bytes), self.size - 1))
        self._vbase = 0                # virtual clock: head byte at _vt0
        self._vt0 = clock()
        self._last_head = 0
        self._had_main = False
        self._last_key = None
        self._last_head_piece_abs = -1
        self.events: collections.deque = collections.deque(maxlen=2000)   # (t, name, detail)
        self.counters = collections.Counter()
        self._pinned_bytes_cache = None
        if cfg.cache_limit_bytes:
            mw = self.max_window
            if mw < 4 * self.pm.piece_length:
                raise CacheTooSmallError(
                    f"cache limit {cfg.cache_limit_bytes} B is too small: after the reserve ({cfg.cache_reserve(piece_len=self.pm.piece_length)} B), the "
                    f"backward-seek window ({self.back_bytes()} B) and pinned container data ({self._pinned_bytes()} B) only "
                    f"{max(mw, 0)} B are left for read-ahead (piece size {self.pm.piece_length} B)")
        store.add_listener(self._on_store_event)
        self.recompute()

    # ----------------------------------------------------------------------------- bookkeeping
    def log(self, name: str, **detail) -> None:
        self.events.append((self.clock(), name, detail))

    def _on_store_event(self, name: str, payload) -> None:
        if name in ("hash_failed", "lost"):               # make sure the piece is asked for again
            self.recompute(force=[payload])

    @property
    def main(self) -> Conn | None:
        mains = [c for c in self.conns.values() if c.kind == "main" and not c.closed and not c.superseded]
        return max(mains, key=lambda c: c.id) if mains else None

    def bytes_per_s(self) -> float:
        ps = self.player
        if ps and ps.duration and ps.duration > 1:
            return max(self.size / ps.duration, 1.0)
        return float(self.cfg.assumed_bytes_per_s)

    def back_bytes(self) -> int:
        """Retention behind the playhead; follows the measured bitrate when it is configured in seconds."""
        return self.cfg.back_bytes(self.bytes_per_s())

    def _pinned_bytes(self) -> int:
        pm = self.pm
        return sum(len(pm.range_pieces(self.file_index, lo, hi)) for lo, hi in self.pinned) * pm.piece_length

    @property
    def max_window(self):
        """Largest read-ahead window that keeps pins + back window + window + reserve inside the cache limit (None = unbounded)."""
        if not self.cfg.cache_limit_bytes:
            return None
        return (self.cfg.cache_limit_bytes - self.cfg.cache_reserve(piece_len=self.pm.piece_length) - self.back_bytes()
                - self._pinned_bytes() - 3 * self.pm.piece_length)

    def bitrate_known(self) -> bool:
        ps = self.player
        return bool(ps and ps.duration and ps.duration > 1)

    def window_bytes(self) -> int:
        # Until the player has told us the duration, a seconds-based window would be a guess that can span the whole
        # file: use only the byte-based floor (min read-ahead, and what mpv itself will buffer).
        bps = self.bytes_per_s() if (self.bitrate_known() or not self.expect_player) else 0.0
        w = min(self.cfg.window_bytes(bps), self.size)
        return w if self.max_window is None else min(w, self.max_window)

    # ------------------------------------------------------------------------------ connections
    def probe_max(self) -> int:
        """A request reaching EOF with at most this many bytes left is a container probe (moov / Cues), not playback.
        Capped relative to the file so that a seek into the last few percent of a small file is still a seek."""
        return min(self.cfg.probe_max_bytes, max(64 * 1024, self.size // 32))

    def open_connection(self, start: int, last: int) -> Conn:
        """Called by the HTTP layer for every GET. Classifies it (probe/main) and detects seeks."""
        now = self.clock()
        remaining = last + 1 - start
        c = Conn(next(self._ids), start, last, "probe" if remaining <= self.probe_max() else "main", now, pos=start)
        if c.kind == "probe":
            self._pin(start, last)
        else:
            prev = self.main
            if not self._had_main:
                seek = False                                   # first main connection: playback starts here
                self._reset_head(start)
            else:
                # compare with where the head was, even if the previous connection is already closed (mpv often
                # closes the old connection before it opens the new one)
                head = self.head_byte()
                seek = (start < head - self.cfg.seek_back_slack
                        or start > head + self.window_bytes() + self.cfg.seek_fwd_slack)
                if seek:
                    self._reset_head(start)
                    self.counters["seeks"] += 1
            if prev is not None:
                prev.superseded = True
            self._had_main = True
            self.log("main_open", start=start, seek=seek)
        self.conns[c.id] = c
        self.log("conn_open", id=c.id, kind=c.kind, start=start, last=last)
        self.recompute()
        return c

    def advance(self, c: Conn, pos: int) -> None:
        c.pos = pos
        h = min(self.head_byte(), self.size - 1)
        if h // self.pm.piece_length != self._last_head_piece_abs or c.kind == "probe":
            self.recompute()

    def close_connection(self, c: Conn) -> None:
        if c.closed:
            return
        c.closed = True
        self.conns.pop(c.id, None)
        self.log("conn_close", id=c.id, pos=c.pos, kind=c.kind)
        self.recompute()

    def update_player(self, ps: PlayerState) -> None:
        self.player = ps

    def _pin(self, a: int, b: int) -> None:
        for lo, hi in self.pinned:
            if lo <= a and b <= hi:
                return
        if sum(hi - lo + 1 for lo, hi in self.pinned) + (b - a + 1) <= self.cfg.pin_cap_bytes:
            self.pinned.append((a, b))
            self.log("pin", start=a, last=b)

    def _reset_head(self, start: int) -> None:
        self._vbase, self._vt0, self._last_head = start, self.clock(), start

    # -------------------------------------------------------------------------------- the head
    def head_byte(self) -> int:
        c = self.main
        if c is None:
            return self._last_head
        ps = self.player
        if ps and ps.fw_bytes is not None and self.clock() - ps.ts <= self.cfg.player_fresh_s:
            h = c.pos - ps.fw_bytes                      # authoritative: sent minus what mpv still holds unplayed
        elif self.expect_player:
            h = self._last_head if self._last_head >= c.start else c.start   # hold: never guess while a player is attached
        else:
            h = self._vbase + int((self.clock() - self._vt0) * self.bytes_per_s())
        h = max(c.start, min(h, c.pos, self.size - 1))
        self._last_head = h
        return h

    def head_source(self) -> str:
        ps = self.player
        return "player" if ps and ps.fw_bytes is not None and self.clock() - ps.ts <= self.cfg.player_fresh_s else "virtual"

    # ------------------------------------------------------------------------------- the gate
    def gate_limit(self, c: Conn) -> int:
        """Exclusive upper bound of bytes this connection may be sent now."""
        if c.closed:
            return c.pos
        if c.kind == "probe":
            return c.last + 1
        if c.superseded:
            return c.pos
        return min(c.last + 1, self.head_byte() + self.window_bytes())

    async def permit(self, c: Conn, end: int, alive: Callable[[], bool]) -> bool:
        """Wait until bytes up to `end` (exclusive) may be sent. False if the connection is gone."""
        waited = False
        while alive() and not c.closed:
            if end <= self.gate_limit(c):
                if waited:
                    self.counters["gate_waits"] += 1
                return True
            waited = True
            await asyncio.sleep(0.05)
        return False

    # ------------------------------------------------------------------------------- the demand
    def build_demand(self) -> Demand:
        d = Demand()
        pm, f = self.pm, self.file_index
        step = int(min(2000, max(20, self.pm.piece_length / self.bytes_per_s() * 1000)))
        for lo, hi in self.pinned:
            d.pinned.update(pm.range_pieces(f, lo, hi))
        main = self.main
        if main is not None:
            head = self.head_byte()
            win = self.window_bytes()
            urgent = min(self.cfg.urgent_bytes(self.bytes_per_s() if (self.bitrate_known() or not self.expect_player) else 0.0), win)
            end = min(main.last, self.size - 1)
            u_end = min(head + urgent, end)
            r_end = min(head + win, end)
            if head <= end:
                for i, p in enumerate(pm.range_pieces(f, head, u_end)):
                    d.deadlines[p] = 100 + i * step
                if r_end > u_end:
                    d.wanted.update(pm.range_pieces(f, u_end + 1, r_end))
        for c in self.conns.values():                  # http_demand: what connections are about to read
            if c.closed or c.superseded or c.pos > c.last:
                continue
            limit = min(c.last + 1, self.gate_limit(c)) if c.kind == "main" else c.last + 1
            if limit <= c.pos:
                # gated main: its next bytes are outside the window; nothing to fetch for it
                continue
            hi = min(limit - 1, c.pos + 2 * self.cfg.chunk_bytes - 1)
            for i, p in enumerate(pm.range_pieces(f, c.pos, hi)):
                d.deadlines[p] = min(d.deadlines.get(p, 1 << 30), 50 + i * step)
        d.wanted -= set(d.deadlines)
        d.pinned -= set(d.deadlines)
        return d

    def recompute(self, force=()) -> Demand:
        d = self.build_demand()
        key = d.key()
        h = min(self.head_byte(), self.size - 1)
        self._last_head_piece_abs = h // self.pm.piece_length
        if self.cfg.cache_limit_bytes:
            head = min(self.head_byte(), self.size - 1)
            lo_b = max(0, head - self.back_bytes())
            hi_b = min(self.size - 1, head + self.window_bytes())
            f = self.file_index
            pinned = set()
            for lo, hi in self.pinned:
                pinned.update(self.pm.range_pieces(f, lo, hi))
            self.store.retain(RetentionHint(head_piece=self.pm.range_pieces(f, head, head)[0],
                                            keep_lo=self.pm.range_pieces(f, lo_b, lo_b)[0],
                                            keep_hi=self.pm.range_pieces(f, hi_b, hi_b)[0], pinned=pinned))
        if key != self._last_key or force:
            self._last_key = key
            self.store.apply_demand(d, force=force)
            self.counters["demand_updates"] += 1
        return d

    def note_stall(self, pieces) -> None:
        """A reader has waited piece_timeout for these: re-assert their deadlines and wake the swarm."""
        self.counters["stalls"] += 1
        self.log("stall", pieces=sorted(pieces)[:8])
        self.store.wake("stall")
        self.recompute(force=pieces)

    async def run(self) -> None:
        """Background tick: the head moves with time even when no bytes flow."""
        while True:
            await asyncio.sleep(self.cfg.recompute_interval)
            self.recompute()
