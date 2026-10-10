# SPDX-License-Identifier: GPL-3.0-or-later
"""BoundedSparseStore: PersistentFileStore + a hard disk limit, safe eviction and crash recovery.

Eviction transaction (docs/STAGE2_DESIGN.md has the full table of crash points):

    flush      fdatasync data, index.retained := live have                     (durable truth before we change anything)
    journal    index.txn = {E, "begin"}  (atomic, fsync'ed)                    <- from here recovery ROLLS FORWARD
    doom       E becomes unavailable to readers; wait until no reader holds one
    remove     remove the torrent from the libtorrent session                  (nothing can be served or advertised now)
    punch      PUNCH_HOLE every piece of E, block-aligned inward, fdatasync
    index      retained -= E, txn.state = "punched"                            (BEFORE libtorrent is started again)
    re-add     add_torrent(have_pieces = index.retained, no_verify_files)
    verify     libtorrent's have == index.retained for every piece, else FAIL-SAFE (remove torrent, serve nothing)
    commit     index.txn = None

libtorrent itself never gets to decide `have`: its resume data is not used, and a piece leaves `retained` before the
torrent is started again, so an evicted piece can be neither advertised to peers nor uploaded nor served over HTTP.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import Iterable

import libtorrent as lt

from .cacheindex import CacheIndex
from .lt_store import PRIO_OFF, PersistentFileStore
from .piecemap import PieceMap
from .punch import allocated_bytes, block_size, punch_inward, supports_punch
from .store import CacheDirNotManagedError, CacheUnsupportedError, Demand, PieceUnavailable, RetentionHint, StoreError

log = logging.getLogger("kino_stream.cache")


class BoundedSparseStore(PersistentFileStore):
    USE_RESUME = False

    def __init__(self, cfg, loop):
        super().__init__(cfg, loop)
        self.index: CacheIndex | None = None
        self._unflushed: set[int] = set()
        self._readers: dict[int, int] = {}
        self._rlock = threading.Lock()
        self._evict_lock = asyncio.Lock()
        self._closing = False
        self._hint: RetentionHint | None = None
        self._cache_task: asyncio.Task | None = None
        self._last_evict = 0.0
        self._last_flush = time.monotonic()
        self._usage = 0
        self._full_demand: Demand | None = None
        self._readd_have: list[bool] | None = None
        self._bpm: PieceMap | None = None
        self._bsel: int | None = None
        self._excl: set[int] = set()
        self._warned_full = False
        self._kick = asyncio.Event()
        self._flush_lock = asyncio.Lock()
        self._stat_cache: dict = {}
        self.truncated = 0                     # read-ahead pieces held back by admission control (diagnostics)
        self.crash_hook = None                 # tests: callable(name) that may raise SimulatedCrash
        self.cache_stats = {"evictions": 0, "pieces_evicted": 0, "aborted": 0, "punch_failures": 0, "recovered_txn": 0,
                            "verify_failed": 0, "orphans_reclaimed": 0, "last_txn_s": 0.0, "index_dropped": 0}

    def _at(self, name: str) -> None:
        if self.crash_hook is not None:
            self.crash_hook(name)

    # ------------------------------------------------------------------------------------------------- open
    @classmethod
    async def open(cls, cfg, source, save_path, select=None) -> "BoundedSparseStore":
        if cfg.cache_limit_bytes <= 0:
            raise ValueError("BoundedSparseStore needs cache_limit_bytes > 0")
        ok, why = supports_punch(Path(save_path))
        if not ok:
            raise CacheUnsupportedError(f"bounded cache is not possible here: {why}. Existing data in {save_path} was not touched. "
                             f"Use a filesystem with hole punching (ext4, xfs, btrfs, tmpfs) or run without --cache-limit.")
        store = await super().open(cfg, source, save_path, select)
        store._cache_task = asyncio.create_task(store._cache_loop())
        return store

    # --------------------------------------------------------------------------------- recovery (before any peer)
    def _initial_have(self, ti):
        if self._readd_have is not None:               # re-add inside a transaction / restart: index is already exact
            return self._readd_have
        pm = PieceMap.from_torrent_info(ti)
        sel = self._select(pm) if callable(self._select) else self._select
        if sel is None:
            sel = max(pm.files, key=lambda f: f.size).index
        self._bpm, self._bsel = pm, sel
        self._excl = set(pm.exclusive_pieces(sel))
        ih = str(ti.info_hash())
        path = self.cfg.state_dir / f"{ih}.cache.json"
        data = self.save_path / pm.files[sel].path
        idx = CacheIndex.load(path, ih, pm.num_pieces, pm.piece_length)
        if not idx.loaded_from_disk and not idx.corrupt:
            if data.exists() and data.stat().st_blocks > 0:
                raise CacheDirNotManagedError(f"{data} contains data but there is no cache index for it: this directory is not managed by a "
                                 f"bounded cache (or its index was deleted). Refusing to touch it; use an empty --save-path.")
            idx.save()                                  # from now on 'data without index' means 'foreign data'
        self.index = idx
        bs = block_size(self.save_path)
        if idx.corrupt:
            log.error("cache index unreadable: retaining nothing and reclaiming the space")
            self.cache_stats["index_dropped"] += 1
        adjacent: set[int] = set()
        if idx.txn is not None:
            adjacent = self._roll_forward(idx, pm, sel, data, bs)
        # data lost or truncated -> nothing can be trusted
        f = pm.files[sel]
        if idx.retained_set() and (not data.exists() or data.stat().st_size < f.size):
            log.error("data file missing or truncated: dropping all retained pieces")
            idx.retained = bytearray(pm.num_pieces)
            idx.save()
        self._verify_sample(idx, pm, sel, data, ti, adjacent)
        self._reclaim_orphans(idx, pm, sel, data, bs)
        idx.save()
        return idx.as_bool_list()

    def _piece_file_range(self, pm: PieceMap, sel: int, p: int) -> tuple[int, int]:
        a, b = pm.piece_span(p)
        f0 = pm.files[sel].start
        return a - f0, b - f0

    def _punch_pieces(self, pm, sel, data: Path, pieces, bs, hook_mid: bool = False) -> int:
        failures = 0
        pieces = list(pieces)
        for i, p in enumerate(pieces):
            if hook_mid and i == len(pieces) // 2:
                self._at("mid_punch")
            a, b = self._piece_file_range(pm, sel, p)
            try:
                punch_inward(data, a, b, bs)
            except OSError as e:
                failures += 1
                self.cache_stats["punch_failures"] += 1
                log.error("punching piece %d failed: %s", p, e)
        try:
            fd = os.open(data, os.O_RDWR)
            try:
                os.fdatasync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        return failures

    def _roll_forward(self, idx: CacheIndex, pm, sel, data, bs) -> set[int]:
        """An unfinished eviction was found: finish it. Never trusts stale libtorrent resume data."""
        E = list(idx.txn["evict"])
        log.warning("recovering unfinished eviction %s (%d pieces, state %s)", idx.txn["id"], len(E), idx.txn["state"])
        self.cache_stats["recovered_txn"] += 1
        if idx.txn["state"] == "begin" and data.exists():
            self._punch_pieces(pm, sel, data, E, bs)
        if idx.txn["state"] == "begin":
            idx.mark_punched()
        idx.commit()
        adj = set()
        for p in E:
            adj.update(q for q in (p - 1, p + 1) if 0 <= q < pm.num_pieces)
        return adj - set(E)

    def _verify_sample(self, idx, pm, sel, data, ti, extra: set[int]) -> None:
        if not data.exists():
            return
        cand = [p for p in idx.retained_set() if p in self._excl]
        rnd = random.Random(idx.epoch)
        pick = set(rnd.sample(cand, min(self.cfg.cache_verify_sample, len(cand)))) | {p for p in extra if idx.retained[p] and p in self._excl}
        bad = []
        with open(data, "rb") as fh:
            for p in sorted(pick):
                a, b = self._piece_file_range(pm, sel, p)
                fh.seek(a)
                if hashlib.sha1(fh.read(b - a)).digest() != bytes(ti.hash_for_piece(p)):
                    bad.append(p)
        if bad:
            log.error("startup verification: %d retained piece(s) are corrupt, dropping them: %s", len(bad), bad[:8])
            self.cache_stats["verify_failed"] += len(bad)
            for p in bad:
                idx.retained[p] = 0
            idx.save()

    def _reclaim_orphans(self, idx, pm, sel, data, bs) -> None:
        """Pieces downloaded after the last index flush (or evicted-but-unpunched) are on disk but not retained:
        release their space (idempotent)."""
        if not data.exists():
            return
        expected = len(idx.retained_set()) * pm.piece_length
        if data.stat().st_blocks * 512 <= expected + 2 * pm.piece_length + 8 * bs:
            return
        orphans = [p for p in self._excl if not idx.retained[p]]
        self._punch_pieces(pm, sel, data, orphans, bs)
        self.cache_stats["orphans_reclaimed"] += len(orphans)

    # ----------------------------------------------------------------------------------------------- tracking
    def _mark_have(self, piece: int) -> None:
        super()._mark_have(piece)
        if self.index is not None and not self.index.retained[piece]:
            self._unflushed.add(piece)
        if self.piece_map is not None and self._have.count(1) * self.piece_map.piece_length >= self.cfg.cache_high * self.cfg.cache_limit_bytes:
            self._kick.set()                           # react to growth immediately, not at the next poll

    def retain(self, hint: RetentionHint) -> None:
        self._hint = hint

    def estimated_usage(self) -> int:
        """Immediate (no sampling lag) usage from our own bitmap: every live piece occupies its block-aligned length."""
        pm = self.piece_map
        return 0 if pm is None else self._have.count(1) * pm.piece_length

    def apply_demand(self, demand: Demand, force: Iterable[int] = ()) -> None:
        """Admission control: urgent (deadline) and pinned pieces are always requested; read-ahead is requested only as far
        as the budget (limit - reserve) allows, nearest to the head first. This is what makes the limit a HARD limit."""
        self._full_demand = demand
        pm = self.piece_map
        if pm is not None:
            budget = (self.cfg.cache_limit_bytes - self.cfg.cache_reserve(piece_len=pm.piece_length)) // pm.piece_length
            free = max(0, budget - self._have.count(1))
            head = self._hint.head_piece if self._hint else 0
            pinned = [p for p in demand.pinned if not self._have[p] and p not in demand.deadlines]
            urgent = sorted((p for p in demand.deadlines if not self._have[p]), key=lambda p: demand.deadlines[p])
            wanted = sorted((p for p in demand.wanted if not self._have[p]), key=lambda p: abs(p - head))
            order = pinned + urgent + wanted                       # container metadata, then what playback needs now, then read-ahead
            if len(order) > free:
                # Over budget. Stale data must be evicted FIRST (playback may wait for that); we never request beyond the limit.
                self.truncated += len(order) - free
                self._kick.set()
                order = order[:free]
            allowed = set(order)
            demand = Demand(deadlines={p: d for p, d in demand.deadlines.items() if p in allowed or self._have[p]},
                            wanted={p for p in demand.wanted if p in allowed or self._have[p]},
                            pinned={p for p in demand.pinned if p in allowed or self._have[p]})
        super().apply_demand(demand, force)

    def read(self, file_index: int, offset: int, length: int) -> bytes:
        pm = self.piece_map
        need = list(pm.range_pieces(file_index, offset, offset + length - 1))
        with self._rlock:                              # register as a reader BEFORE looking, so eviction can wait for us
            gone = [p for p in need if not self._have[p]]
            if gone:
                raise PieceUnavailable(gone)
            for p in need:
                self._readers[p] = self._readers.get(p, 0) + 1
        try:
            late = self._unverified(file_index, need)              # complete per libtorrent but not yet readable from the file (see PersistentFileStore._unverified)
            if late:
                raise PieceUnavailable(late)
            fd = self._fd(file_index)
            out = bytearray()
            while len(out) < length:
                chunk = os.pread(fd, length - len(out), offset + len(out))
                if not chunk:
                    raise PieceUnavailable(need)       # never pad with zeros
                out += chunk
            self._counters["reads"] += 1
            return bytes(out)
        finally:
            with self._rlock:
                for p in need:
                    self._readers[p] -= 1
                    if not self._readers[p]:
                        del self._readers[p]

    def _sync_all(self) -> None:
        for fp in self.save_path.rglob("*"):
            if fp.is_file():
                fd = os.open(fp, os.O_RDONLY)
                try:
                    os.fdatasync(fd)
                finally:
                    os.close(fd)

    async def _flush_durable(self) -> None:
        """Make every live piece durable, then record it in the index (a piece is 'retained' only once synced)."""
        if self.index is None:
            return
        async with self._flush_lock:
            await self._flush_durable_locked()

    async def _flush_durable_locked(self) -> None:
        if self.index.txn is not None:                                         # an eviction transaction owns the index right now
            return
        pend = {p for p in self._unflushed if self._have[p]}
        if not pend:
            self._unflushed.clear()
            self._last_flush = time.monotonic()
            return
        if self.handle is not None and not self._restarting:
            try:
                self.handle.flush_cache()
            except Exception:
                pass

        def work():
            for fp in self.save_path.rglob("*"):
                if fp.is_file():
                    fd = os.open(fp, os.O_RDONLY)
                    try:
                        os.fdatasync(fd)
                    finally:
                        os.close(fd)
        await asyncio.to_thread(work)
        self.index.add_retained(pend)
        await asyncio.to_thread(self.index.save)
        self._unflushed -= pend
        self._last_flush = time.monotonic()

    # ---------------------------------------------------------------------------------------------- policy loop
    async def _cache_loop(self) -> None:
        lim = self.cfg.cache_limit_bytes
        measured_at = 0.0
        while True:
            try:
                await asyncio.wait_for(self._kick.wait(), 0.25)
            except asyncio.TimeoutError:
                pass
            self._kick.clear()
            try:
                if self.piece_map is None or self._error or self._restarting:
                    continue
                now = time.monotonic()
                if now - measured_at >= 1.0:                                   # real st_blocks, for stats and as a cross-check
                    self._usage = await asyncio.to_thread(allocated_bytes, self.save_path)
                    measured_at = now
                if self._unflushed and now - self._last_flush >= self.cfg.flush_interval:
                    await self._flush_durable()
                if self._evict_lock.locked() or self._closing:
                    continue
                usage = max(self.estimated_usage(), self._usage if now - measured_at < 1.5 else 0)
                pressure = self.truncated > 0
                if (usage >= self.cfg.cache_high * lim or pressure) and (
                        now - self._last_evict >= self.cfg.evict_min_interval or usage >= self.cfg.cache_emergency * lim or pressure):
                    self.truncated = 0
                    victims = self.plan_eviction(usage)
                    if victims:
                        await self.evict(victims, reason=f"usage {usage} >= {self.cfg.cache_high:.0%} of limit")
                        self._usage = await asyncio.to_thread(allocated_bytes, self.save_path)
                        measured_at = time.monotonic()
                    elif not self._warned_full:
                        self._warned_full = True
                        log.warning("cache is full of data that must be kept (window/back/pinned): consider a larger limit")
                    if self._full_demand is not None:
                        self.apply_demand(self._full_demand)
                    self._last_evict = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("cache loop iteration failed")

    def plan_eviction(self, usage: int) -> list[int]:
        """Victims: retained pieces outside the retention window, never pinned/demanded/shared, farthest from the head first."""
        hint = self._hint
        if hint is None or self.piece_map is None:
            return []
        keep = set(hint.pinned)
        if self._full_demand is not None:
            keep |= self._full_demand.all_pieces()
        cand = [p for p in self._excl if self._have[p] and self.index.retained[p] and p not in keep
                and not (hint.keep_lo <= p <= hint.keep_hi)]
        if not cand:
            return []
        cand.sort(key=lambda p: -abs(p - hint.head_piece))
        lim = self.cfg.cache_limit_bytes
        want_free = max(0, usage - int(self.cfg.cache_low * lim))
        k = max(self.cfg.evict_min_batch_pieces, -(-want_free // self.piece_map.piece_length))
        return sorted(cand[:k])

    # ---------------------------------------------------------------------------------- the eviction transaction
    async def evict(self, pieces: Iterable[int], reason: str = "") -> bool:
        """Evict pieces. Returns True if done, False if aborted harmlessly before anything destructive."""
        async with self._evict_lock:
            if self._error:
                raise StoreError(self._error)
            if self._restarting:
                return False
            pm, sel = self._bpm, self._bsel
            E = sorted(p for p in set(pieces) if p in self._excl and self._have[p] and (self.index.retained[p] or p in self._unflushed))
            if not E:
                return False
            t0 = time.monotonic()
            await self._flush_durable()                                       # live have == index.retained from here
            E = [p for p in E if self.index.retained[p]]
            if not E:
                return False
            self._at("before_journal")
            self.index.begin_txn(E)                                           # --- point of no return (roll forward)
            self._at("after_journal")
            with self._rlock:                                                 # doom: nobody may start reading E
                for p in E:
                    self._have[p] = 0
                    self._disk_ok.discard(p)                       # when it is downloaded again it must be verified again
            self._at("after_doom")
            deadline = time.monotonic() + self.cfg.drain_timeout
            while True:
                with self._rlock:
                    busy = [p for p in E if self._readers.get(p)]
                if not busy:
                    break
                if time.monotonic() > deadline:                               # nothing destructive happened yet: back out
                    with self._rlock:
                        for p in E:
                            self._have[p] = 1
                    self.index.abort_txn()
                    self.cache_stats["aborted"] += 1
                    log.warning("eviction aborted: readers still hold %s", busy[:4])
                    return False
                await asyncio.sleep(0.01)
            self._restarting = True                                           # pauses sampler/ticker/wake, blocks restarts
            try:
                self._dl_base += self.handle.status().total_payload_download
                self._removed = self.loop.create_future()
                self.session.remove_torrent(self.handle)
                await asyncio.wait_for(self._removed, 10)                     # torrent is gone: nothing is served/advertised
                self._at("after_remove")
                data = self.save_path / pm.files[sel].path
                Eset = set(E)
                # Pieces that finished after the last flush are valid on disk: make them durable and keep them. (Dropping
                # them silently left fully allocated but unclaimed data behind: the cache then exceeded its limit.)
                late = [i for i in range(pm.num_pieces) if self._have[i] and not self.index.retained[i] and i not in Eset]
                if late:
                    await asyncio.to_thread(self._sync_all)
                    self.index.add_retained(late)
                bs = block_size(self.save_path)
                fails = await asyncio.to_thread(self._punch_pieces, pm, sel, data, E, bs, True)
                # whatever else is allocated but not claimed (a piece completed in the instant before removal, whose
                # alert we had not processed yet) is released too - the torrent is gone, nothing can be writing
                claimed = {i for i in range(pm.num_pieces) if self.index.retained[i] and i not in Eset}
                if data.exists() and data.stat().st_blocks * 512 > len(claimed) * pm.piece_length + 2 * pm.piece_length:
                    stray = [i for i in self._excl if i not in claimed and i not in Eset]
                    await asyncio.to_thread(self._punch_pieces, pm, sel, data, stray, bs)
                    self.cache_stats["orphans_reclaimed"] += len(stray)
                self._at("after_punch")
                self.index.mark_punched()                                     # retained -= E, durable, BEFORE re-add
                self._at("after_index_punched")
                await asyncio.sleep(0.4)                                      # let peers drop the old connection
                self._readd_have = self.index.as_bool_list()
                try:
                    p = self._params(self._ti, use_resume=False)
                finally:
                    self._readd_have = None
                self.handle = self.session.add_torrent(p)
                self.handle.prioritize_pieces([PRIO_OFF] * pm.num_pieces)
                self.handle.resume()
                self._at("after_readd")
                mism = [i for i in range(pm.num_pieces) if self.handle.have_piece(i) != bool(self.index.retained[i])]
                if mism:                                                      # FAIL-SAFE: never keep a torrent whose have != disk
                    try:
                        self.session.remove_torrent(self.handle)
                    except Exception:
                        pass
                    raise StoreError(f"libtorrent have-state differs from the cache index for pieces {mism[:8]}: refusing to serve")
                self._at("before_commit")
                self.index.commit()
                with self._rlock:
                    self._have = bytearray(self.index.retained)
                self._unflushed.clear()
                self._applied.clear()
                for host, port in self.cfg.peers:
                    self.handle.connect_peer((host, port))
                self.cache_stats["evictions"] += 1
                self.cache_stats["pieces_evicted"] += len(E)
                self.cache_stats["last_txn_s"] = round(time.monotonic() - t0, 2)
                self._event("evicted", E)
                self._at("after_commit")
            except StoreError as e:
                self._fail(str(e))
                raise
            except Exception as e:                                            # not a simulated crash: stop serving, keep disk
                self._fail(f"eviction failed after the point of no return: {e!r}; the journal will complete it on restart")
                raise StoreError(str(e)) from e
            finally:
                self._restarting = False
                self._no_peer_since = None
        if self._full_demand is not None and not self._error:
            self.apply_demand(self._full_demand, force=())
        for p in E:
            self._event("lost", p)
        return True

    # ----------------------------------------------------------------------------------------- lifecycle / stats
    async def _restart(self, why: str) -> None:
        if self._evict_lock.locked():
            return
        await self._flush_durable()
        self._readd_have = self.index.as_bool_list() if self.index else None
        try:
            await super()._restart(why)
        finally:
            self._readd_have = None

    async def _wait_eviction_done(self) -> None:
        while self._evict_lock.locked():
            await asyncio.sleep(0.02)

    async def _save_resume(self) -> bool:
        return False                                                           # libtorrent resume data is never trusted

    def stats(self) -> dict:
        d = super().stats()
        if "total_download" in d:
            self._stat_cache = {k: d[k] for k in ("peers", "state", "total_download", "total_upload", "piece_length", "pieces_total") if k in d}
        else:                                                                  # torrent is being re-added: report the last known values
            d.update(self._stat_cache)
            d["total_download"] = max(d.get("total_download", 0), self._dl_base)
            d.setdefault("total_upload", 0)
            d.setdefault("peers", 0)
            d["pieces_have"] = self._have.count(1) if self._have else 0
        d.update(self.cache_stats)
        d.update(cache_limit=self.cfg.cache_limit_bytes, allocated_bytes=self._usage,
                 retained_pieces=0 if self.index is None else len(self.index.retained_set()),
                 unflushed_pieces=len(self._unflushed))
        return d

    async def close(self) -> None:
        self._closing = True                                                   # the cache loop starts no new eviction from here on
        if self._evict_lock.locked():
            # An eviction transaction is in flight (the cache loop runs it): let it reach its commit instead of cancelling it half way. Cancelling would leave the journal open
            # ("punched") after a clean exit; the next start would complete it (roll forward), but a clean exit should leave a clean journal. Bounded: a stuck eviction
            # (its own waits are <= 10 s) is cancelled as before after 20 s and recovery handles it.
            try:
                await asyncio.wait_for(self._wait_eviction_done(), 20)
            except asyncio.TimeoutError:
                log.warning("closing while an eviction is still running; the journal completes it at the next start")
        if self._cache_task:
            self._cache_task.cancel()
        try:
            await self._flush_durable()
        except Exception:
            log.exception("final flush failed")
        await super().close()

    async def abandon(self) -> None:
        """Tests: die like a crashed process (no flush, no journal completion)."""
        for t in (self._cache_task, self._tick_task, self._sampler_task):
            if t:
                t.cancel()
        self._pump_stop.set()
        if self.session is not None and self.handle is not None:
            try:
                self.session.remove_torrent(self.handle)
            except Exception:
                pass
        for fd in self._fds.values():
            try:
                os.close(fd)
            except OSError:
                pass
        self._fds.clear()
        if self._pump is not None:
            await asyncio.gather(self._pump, return_exceptions=True)
        self.session = None
