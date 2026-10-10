# SPDX-License-Identifier: GPL-3.0-or-later
"""PersistentFileStore: a PieceStore on top of one libtorrent session with ordinary persistent files.

libtorrent APIs used (all verified against 2.0.10 in spikes/s0_api.py):
  session(settings), session.add_torrent(add_torrent_params), session.remove_torrent, 
  session.pop_alerts (never wait_for_alert, see docs/KNOWN_ISSUES.md), parse_magnet_uri, read_resume_data, write_resume_data_buf, add_torrent_params.{ti,save_path,flags},
  torrent_handle.{prioritize_pieces, piece_priority, set_piece_deadline, reset_piece_deadline, have_piece, status,
  torrent_file, has_metadata, connect_peer, force_reannounce, force_dht_announce, resume, save_resume_data,
  need_save_resume_data, info_hashes},
  alerts: piece_finished, hash_failed, metadata_received, torrent_error, file_error, save_resume_data,
  save_resume_data_failed, torrent_checked, state_changed, alerts_dropped, fastresume_rejected, peer_ban.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from pathlib import Path
from typing import Iterable

import libtorrent as lt

from .config import Config
from .piecemap import PieceMap
from .store import Demand, Listener, PieceStore, PieceTimeout, PieceUnavailable, StoreError

log = logging.getLogger("kino_stream.store")

PRIO_DEADLINE, PRIO_PINNED, PRIO_WANTED, PRIO_OFF = 7, 6, 4, 0


def _alert_mask() -> int:
    c = lt.alert.category_t
    # NOT peer_notification / connect_notification: on a real swarm they produce thousands of alerts and the Python
    # binding crashed (SIGSEGV in __dynamic_cast while converting alerts; 1 of 3 runs, 0 of 3 without them).
    # Peer churn is derived from num_peers samples instead.
    return int(c.error_notification | c.status_notification | c.piece_progress_notification)


def session_settings(cfg: Config) -> dict:
    enc = {}
    if cfg.encryption == "forced":
        enc = {"out_enc_policy": lt.enc_policy.forced, "in_enc_policy": lt.enc_policy.forced, "allowed_enc_level": lt.enc_level.rc4}
    elif cfg.encryption == "disabled":
        enc = {"out_enc_policy": lt.enc_policy.disabled, "in_enc_policy": lt.enc_policy.disabled}
    return {**enc,
        "listen_interfaces": cfg.listen,
        "enable_dht": cfg.dht, "enable_lsd": cfg.lsd, "enable_upnp": cfg.upnp, "enable_natpmp": cfg.upnp,
        "min_reconnect_time": cfg.min_reconnect_time,
        # a peer that refused a few connection attempts (e.g. during an outage) stays a candidate: default 3 would
        # permanently drop a seeder after ~3 s of downtime, and manual connect_peer() does not reset the counter
        "max_failcount": 1000,
        "request_timeout": 15, "piece_timeout": 10,      # defaults (50 s / 20 s) make a lost block request cost a long stall
        # keep the swarm connected while nothing is wanted: avoids the ~1 s reconnect lag and the stall seen in Stage 1
        "close_redundant_connections": False,
        "alert_mask": _alert_mask(),                  # NOT all_categories: that overflowed the queue in the spikes
        "alert_queue_size": cfg.alert_queue_size,
        "upload_rate_limit": cfg.upload_limit, "download_rate_limit": cfg.download_limit,
        "ignore_limits_on_local_network": not cfg.limits_on_lan,
        "allow_multiple_connections_per_ip": True,
        "announce_to_all_trackers": False,
        "active_downloads": -1, "active_seeds": -1, "active_limit": -1, "active_checking": 4,
    }


class PersistentFileStore(PieceStore):
    """Pieces are written into ordinary files by libtorrent and stay there. Never loses a piece."""

    def __init__(self, cfg: Config, loop: asyncio.AbstractEventLoop):
        self.cfg = cfg
        self.loop = loop
        self.session: lt.session | None = None
        self.handle = None
        self.piece_map: PieceMap | None = None
        self.save_path = Path()
        self._have: bytearray = bytearray()
        self._waiters: dict[int, list[asyncio.Future]] = {}
        self._listeners: list[Listener] = []
        self._meta = asyncio.Event()
        self._saved: asyncio.Future | None = None
        self._pump_stop = threading.Event()
        self._pump: asyncio.Task | None = None
        self._applied: dict[int, tuple[int, int | None]] = {}   # piece -> (priority, deadline) currently set in libtorrent
        self._last_wake = 0.0
        self._last_progress = time.monotonic()
        self._tick_task: asyncio.Task | None = None
        self._fds: dict[int, int] = {}
        self._counters = {"alerts": 0, "alerts_dropped": 0, "hash_failed": 0, "pieces_finished": 0, "wakes": 0,
                          "file_errors": 0, "bans": 0, "reads": 0, "deadline_sets": 0, "deadline_resets": 0,
                          "obsolete_cancelled": 0, "forced_reasserts": 0, "peer_connects": 0, "peer_disconnects": 0, "restarts": 0}
        self._zero_peer_s = 0.0           # seconds with demand outstanding but no peer connected
        self._zero_peer_all_s = 0.0
        self._peers_max = 0
        self._sampler_task: asyncio.Task | None = None
        self._error: str | None = None
        self._select = None
        self._ti = None
        self._demand: Demand | None = None
        self.ever_demanded: set[int] = set()     # every piece the scheduler ever asked for (diagnostics)
        self._restarting = False
        self._no_peer_since: float | None = None
        self._last_restart = 0.0
        self._pay_mark = 0
        self._last_n = 0
        self._ever_downloaded = False
        self._pay_t = time.monotonic()
        self._dl_base = 0                       # bytes downloaded by earlier incarnations of the torrent handle
        self._ever_had_peer = False
        self._hinted_no_peers = False
        self._opened_at = time.monotonic()
        self._removed: asyncio.Future | None = None
        self._magnet_params = None
        self.selected_file: int | None = None
        self._infohash = ""
        self.history: list[tuple[float, str, object]] = []    # (t, event, payload) for diagnostics/tests

    # ----------------------------------------------------------------------------------- open
    @classmethod
    async def open(cls, cfg: Config, source, save_path, select=None) -> "PersistentFileStore":
        """source: magnet URI (str), path to a .torrent file, or a libtorrent torrent_info.
        select: file index, or callable(PieceMap) -> index, naming the one file that will be streamed. Only that file
        gets a real on-disk file; all other files stay at priority 0 (their pieces, if shared, go to the part-file)."""
        self = cls(cfg, asyncio.get_running_loop())
        self._select = select
        self.save_path = Path(save_path)
        self.save_path.mkdir(parents=True, exist_ok=True)
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        p = self._params(source)                         # may raise (e.g. bounded cache refuses an unmanaged directory)
        self.session = lt.session(session_settings(cfg))
        self._pump = asyncio.create_task(self._pump_alerts())
        self.handle = self.session.add_torrent(p)
        if self._from_magnet:                            # hints help metadata exchange; with metadata they wait for the first demand
            for host, port in cfg.peers:
                self.handle.connect_peer((host, port))
        self._tick_task = asyncio.create_task(self._ticker())
        self._sampler_task = asyncio.create_task(self._sampler())
        if self.handle.torrent_file() is not None:
            self._on_metadata()
        try:
            await asyncio.wait_for(self._meta.wait(), cfg.metadata_timeout)
        except asyncio.TimeoutError:
            await self.close()
            raise StoreError("no torrent metadata (no peers/trackers?)")
        except BaseException:                            # cancelled (user pressed Cancel) or anything else: never leak a session
            await asyncio.shield(self.close())
            raise
        return self

    def _params(self, source, use_resume: bool = True) -> lt.add_torrent_params:
        if isinstance(source, lt.torrent_info):
            p = lt.add_torrent_params(); p.ti = source
        elif isinstance(source, str) and source.startswith("magnet:"):
            p = lt.parse_magnet_uri(source)
        else:
            p = lt.add_torrent_params(); p.ti = lt.torrent_info(str(source))
        ih = str(p.ti.info_hash()) if p.ti else str(p.info_hashes.v1)
        self._infohash = ih
        rp = self.cfg.state_dir / f"{ih}.resume"
        if use_resume and self.USE_RESUME and rp.exists():
            try:
                q = lt.read_resume_data(rp.read_bytes())
                if p.ti and not q.ti:
                    q.ti = p.ti
                p = q
                log.info("resuming from %s", rp)
            except Exception as e:                           # corrupt resume file: start clean
                log.warning("ignoring bad resume data %s: %s", rp, e)
        p.save_path = str(self.save_path)
        if p.ti is not None:
            have = self._initial_have(p.ti)
            if have is not None:                         # bounded cache: the index, not libtorrent, says what we have
                p.have_pieces = have
                p.flags |= lt.torrent_flags.no_verify_files
        # Never auto-managed (the queue must not pause us).
        # NOTE (found in Stage 1): files whose *file* priority is 0 are written to a hidden ".<hash>.parts" part-file,
        # not to the real file, so we must not use default_dont_download when we already have the metadata.
        # With metadata: add paused, zero the *piece* priorities, then resume. Magnet: metadata needs a running
        # torrent, so start with default_dont_download and raise the file priorities when metadata arrives.
        if not self.cfg.web_seeds:                       # measure the swarm itself, not an HTTP mirror
            p.flags |= lt.torrent_flags.override_web_seeds
            p.url_seeds = []
            p.http_seeds = []
        self._from_magnet = p.ti is None
        if self._from_magnet:
            self._magnet_params = p        # trackers / peer hints to carry over when we re-add with full metadata
        # parse_magnet_uri() returns flags that include `paused`; with auto_managed cleared it would stay paused forever
        # (found while debugging the magnet path: the torrent never even connected).
        flags = p.flags & ~lt.torrent_flags.auto_managed
        if self._from_magnet:
            flags = (flags | lt.torrent_flags.default_dont_download) & ~lt.torrent_flags.paused
        else:
            flags |= lt.torrent_flags.paused
        p.flags = flags
        return p

    USE_RESUME = True                                  # bounded stores never trust libtorrent resume data for `have`

    def _initial_have(self, ti):
        """Hook: bitmap of pieces to start with, or None to let libtorrent decide (Stage 1)."""
        return None

    def _on_metadata(self) -> None:
        if self.piece_map is not None:
            return
        ti = self.handle.torrent_file()
        if self._from_magnet:
            # Raising file priorities of a running magnet torrent has lasting side effects on piece priorities
            # (measured: 79% instead of 44% of the file downloaded). Re-add with the metadata instead, exactly like
            # the .torrent path, so both paths behave identically.
            if not getattr(self, "_converting", False):
                self._converting = True
                asyncio.ensure_future(self._convert_magnet(ti))
            return
        self._ti = ti
        self.piece_map = PieceMap.from_torrent_info(ti)
        n = self.piece_map.num_pieces
        self._have = bytearray(n)
        sel = self._select(self.piece_map) if callable(self._select) else self._select
        self.selected_file = sel
        nf = len(self.piece_map.files)
        # file priority 0 = part-file; only the streamed file is written to a real file. Raising a file's priority
        # also raises its pieces, so the torrent stays paused (ti case) / only that file is affected (magnet case)
        # until the piece priorities are zeroed again right below.
        self.handle.prioritize_pieces([PRIO_OFF] * n)       # nothing is wanted until the scheduler asks
        self.handle.resume()
        self._reconcile()
        # Peer hints are connected when data is first wanted (wake()), not here: a manual peer added while the torrent has
        # nothing to download ('finished' state) was found to become a permanent non-candidate when we already hold pieces
        # (second launch with a populated cache: 0 peers for 25+ s).
        self._meta.set()

    async def _convert_magnet(self, ti) -> None:
        try:
            self._removed = self.loop.create_future()
            self.session.remove_torrent(self.handle)
            await asyncio.wait_for(self._removed, 10)
            mp = self._magnet_params
            self._from_magnet = False
            p = self._params(ti)
            p.trackers, p.tracker_tiers = mp.trackers, mp.tracker_tiers      # (peer hints come from cfg.peers via connect_peer)
            self._event("magnet_removed", None)
            # Re-adding in the same instant races the peers' teardown of the old connection (they see a second
            # connection with the same peer-id and refuse it; measured stalls of 60+ s). Give them a moment.
            await asyncio.sleep(0.4)
            self.handle = self.session.add_torrent(p)
            self._event("magnet_readded", None)
            self._on_metadata()
        except Exception as e:
            self._fail(f"magnet conversion failed: {e}")
            self._meta.set()

    async def _restart(self, why: str) -> None:
        """Escalation when the swarm is unreachable: libtorrent can keep a disconnected peer as a non-candidate forever
        (found in Stage 1: connect_peer/pause/resume/reannounce all fail). Remove and re-add the torrent with the exact
        have-bitmap: this reconnects reliably (~0.7 s) and is the same primitive Stage 2 eviction is built on."""
        if self._restarting or self.piece_map is None or self._ti is None:
            return
        self._restarting = True
        self._last_restart = time.monotonic()
        self._counters["restarts"] += 1
        log.warning("restarting torrent: %s", why)
        try:
            have = [bool(b) for b in self._have]
            self._dl_base += self.handle.status().total_payload_download
            self._removed = self.loop.create_future()
            self.session.remove_torrent(self.handle)
            await asyncio.wait_for(self._removed, 10)
            await asyncio.sleep(0.4)
            p = self._params(self._ti, use_resume=False)
            p.have_pieces = have
            p.flags |= lt.torrent_flags.no_verify_files
            self.handle = self.session.add_torrent(p)
            self.handle.prioritize_pieces([PRIO_OFF] * self.piece_map.num_pieces)
            self.handle.resume()
            self._applied.clear()
            for host, port in self.cfg.peers:
                self.handle.connect_peer((host, port))
            self._event("restart", why)
        except Exception as e:
            self._fail(f"restart failed: {e}")
            return
        finally:
            self._restarting = False
            self._no_peer_since = None
        if self._demand is not None:
            self.apply_demand(self._demand, force=self._demand.all_pieces())

    # ------------------------------------------------------------------------------- alerts
    async def _pump_alerts(self) -> None:
        """Alerts are polled from the event-loop thread with pop_alerts() only.
        ROOT CAUSE of the Stage 1 crashes (proven with diag/alert_stress.py): wait_for_alert() returns a raw pointer into the
        LIVE alert queue; libtorrent's other threads keep posting (and re-allocating/destroying) alerts while Python converts
        and uses that pointer -> use-after-free ("pure virtual method called", SIGABRT/SIGSEGV in __dynamic_cast).
        pop_alerts() swaps the queue and hands over memory nobody else touches. Alert objects are valid only until the next
        pop_alerts(), so they are converted to plain tuples immediately."""
        while not self._pump_stop.is_set():
            try:
                alerts = self.session.pop_alerts()
                batch = [r for r in (self._plain(a) for a in alerts) if r is not None]
            except Exception:
                return
            if alerts:
                self._dispatch(len(alerts), batch)
            await asyncio.sleep(0.05)

    @staticmethod
    def _plain(a):
        if isinstance(a, lt.piece_finished_alert):
            return ("piece", a.piece_index)
        if isinstance(a, lt.hash_failed_alert):
            return ("hash_failed", a.piece_index)
        if isinstance(a, lt.metadata_received_alert):
            return ("metadata", None)
        if isinstance(a, lt.alerts_dropped_alert):
            return ("dropped", a.message())
        if isinstance(a, lt.save_resume_data_alert):
            return ("resume", lt.write_resume_data_buf(a.params))     # copy NOW: params is a reference into the alert
        if isinstance(a, lt.save_resume_data_failed_alert):
            return ("resume", None)
        if isinstance(a, lt.file_error_alert):
            return ("file_error", a.message())
        if isinstance(a, lt.torrent_error_alert):
            return ("torrent_error", a.message())
        if isinstance(a, lt.peer_ban_alert):
            return ("ban", None)
        if isinstance(a, lt.torrent_removed_alert):
            return ("removed", None)
        if isinstance(a, lt.peer_connect_alert):
            return ("peer_connect", None)
        if isinstance(a, lt.peer_disconnected_alert):
            return ("peer_disconnect", None)
        if isinstance(a, lt.fastresume_rejected_alert):
            return ("resume_rejected", a.message())
        return None

    def _dispatch(self, n_alerts: int, batch) -> None:
        self._counters["alerts"] += n_alerts
        for kind, v in batch:
            if kind == "piece":
                self._counters["pieces_finished"] += 1
                self._mark_have(v)
            elif kind == "hash_failed":
                self._counters["hash_failed"] += 1
                self._event("hash_failed", v)
            elif kind == "metadata":
                self._event("metadata_received", None)
                self._on_metadata()
            elif kind == "dropped":
                self._counters["alerts_dropped"] += 1
                log.warning("libtorrent dropped alerts: %s", v)
                self._reconcile()                            # we may have missed piece_finished
            elif kind == "resume":
                if self._saved and not self._saved.done():
                    self._saved.set_result(v)
            elif kind == "file_error":
                self._counters["file_errors"] += 1
                self._fail(f"file error: {v}")
            elif kind == "torrent_error":
                self._fail(f"torrent error: {v}")
            elif kind == "ban":
                self._counters["bans"] += 1
            elif kind == "removed":
                if self._removed and not self._removed.done():
                    self._removed.set_result(None)
            elif kind == "peer_connect":
                self._counters["peer_connects"] += 1
            elif kind == "peer_disconnect":
                self._counters["peer_disconnects"] += 1
            elif kind == "resume_rejected":
                log.warning("resume data rejected: %s", v)

    def _fail(self, msg: str) -> None:
        self._error = msg
        log.error(msg)
        self._event("error", msg)
        for fs in self._waiters.values():
            for f in fs:
                if not f.done():
                    f.set_exception(StoreError(msg))
        self._waiters.clear()

    def _event(self, name: str, payload) -> None:
        self.history.append((time.monotonic(), name, payload))
        for cb in list(self._listeners):
            try:
                cb(name, payload)
            except Exception:
                log.exception("listener failed")

    def _mark_have(self, piece: int) -> None:
        if self.piece_map is None or not 0 <= piece < len(self._have):     # alert from the pre-metadata (magnet) incarnation
            return
        if not self._have[piece]:
            self._have[piece] = 1
            self._last_progress = time.monotonic()
            for f in self._waiters.pop(piece, []):
                if not f.done():
                    f.set_result(None)
            self._applied.pop(piece, None)
            self._event("have", piece)

    def _reconcile(self) -> None:
        """Bring the local bitmap in line with libtorrent (start-up, resume, dropped alerts)."""
        bits = self.handle.status(lt.torrent_handle.query_pieces).pieces
        for i in range(self.piece_map.num_pieces):
            if i < len(bits) and bits[i]:
                self._mark_have(i)

    # --------------------------------------------------------------------------- PieceStore
    def have(self, piece: int) -> bool:
        return bool(self._have[piece])

    def add_listener(self, cb: Listener) -> None:
        self._listeners.append(cb)

    async def wait_have(self, pieces: Iterable[int], timeout: float) -> None:
        if self._error:
            raise StoreError(self._error)
        futs = []
        for p in set(pieces):
            if self._have[p]:
                continue
            f = self.loop.create_future()
            self._waiters.setdefault(p, []).append(f)
            futs.append((p, f))
        if not futs:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*(f for _, f in futs)), timeout)
        except asyncio.TimeoutError:
            raise PieceTimeout([p for p, f in futs if not f.done()]) from None
        finally:
            for p, f in futs:
                if not f.done():
                    f.cancel()
                lst = self._waiters.get(p)
                if lst and f in lst:
                    lst.remove(f)
                    if not lst:
                        self._waiters.pop(p, None)

    def read(self, file_index: int, offset: int, length: int) -> bytes:
        pm = self.piece_map
        need = pm.range_pieces(file_index, offset, offset + length - 1)
        gone = [p for p in need if not (self._have[p] and self.handle.have_piece(p))]   # libtorrent has the last word
        if gone:
            raise PieceUnavailable(gone)
        fd = self._fd(file_index)
        out = bytearray()
        while len(out) < length:
            chunk = os.pread(fd, length - len(out), offset + len(out))
            if not chunk:
                raise PieceUnavailable(list(need))           # file shorter than expected: never pad with zeros
            out += chunk
        self._counters["reads"] += 1
        return bytes(out)

    def _fd(self, file_index: int) -> int:
        fd = self._fds.get(file_index)
        if fd is None:
            fd = os.open(self.save_path / self.piece_map.files[file_index].path, os.O_RDONLY)
            self._fds[file_index] = fd
        return fd

    def apply_demand(self, demand: Demand, force: Iterable[int] = ()) -> None:
        self._demand = demand
        self.ever_demanded |= demand.all_pieces()
        if self._error or self.piece_map is None or self._restarting:
            return
        h = self.handle
        force = set(force)
        target: dict[int, tuple[int, int | None]] = {}
        for p in demand.wanted:
            target[p] = (PRIO_WANTED, None)
        for p in demand.pinned:
            target[p] = (PRIO_PINNED, None)
        for p, dl in demand.deadlines.items():
            target[p] = (PRIO_DEADLINE, dl)
        target = {p: v for p, v in target.items() if not self._have[p]}
        for p in list(self._applied):                        # no longer wanted: cancel deadline, priority 0
            if p not in target:
                if self._applied[p][1] is not None:
                    h.reset_piece_deadline(p)
                    self._counters["deadline_resets"] += 1
                h.piece_priority(p, PRIO_OFF)
                self._counters["obsolete_cancelled"] += 1
                del self._applied[p]
        for p, (prio, dl) in target.items():
            cur = self._applied.get(p)
            if cur == (prio, dl) and p not in force:
                continue
            if cur and cur[1] is not None and dl is None:
                h.reset_piece_deadline(p)
                self._counters["deadline_resets"] += 1
            if p in force and cur is not None:
                # A forced re-assert means the piece stalled: dropping the priority to 0 first makes libtorrent cancel
                # the outstanding (possibly lost) block requests, so the next assignment really re-requests them
                # instead of waiting out request_timeout (a 54 s seek was seen once with the default 50 s).
                h.reset_piece_deadline(p)
                h.piece_priority(p, PRIO_OFF)
                self._counters["forced_reasserts"] += 1
            h.piece_priority(p, prio)
            if dl is not None:
                h.set_piece_deadline(p, dl)
                self._counters["deadline_sets"] += 1
            self._applied[p] = (prio, dl)
        if target:
            self._maybe_wake()

    def applied(self) -> dict[int, tuple[int, int | None]]:
        """Snapshot of what is currently set in libtorrent (piece -> (priority, deadline)). For tests/diagnostics."""
        return dict(self._applied)

    def _maybe_wake(self) -> None:
        if self._restarting:
            return
        st = self.handle.status()
        if st.num_peers == 0 or st.state in (lt.torrent_status.finished, lt.torrent_status.seeding):
            self.wake("demand while idle")

    def wake(self, reason: str = "") -> None:
        if self._restarting:
            return
        now = time.monotonic()
        if now - self._last_wake < 0.5:
            return
        self._last_wake = now
        self._counters["wakes"] += 1
        h = self.handle
        try:
            h.resume()
            for host, port in self.cfg.peers:
                h.connect_peer((host, port))
            h.force_reannounce()
            if self.cfg.dht:
                h.force_dht_announce()
        except Exception:
            log.exception("wake failed")
        self._event("wake", reason)

    async def _ticker(self) -> None:
        """Keeps demanded pieces moving: re-wakes the torrent when nothing arrives; periodic resume data."""
        last_resume = time.monotonic()
        while True:
            await asyncio.sleep(self.cfg.wake_interval)
            try:
                if self.piece_map is None or self._restarting:
                    continue
                if self._applied and time.monotonic() - self._last_progress > self.cfg.wake_interval * 2:
                    self.wake("no progress")
                if (not self._ever_had_peer and not self._hinted_no_peers
                        and time.monotonic() - self._opened_at > self.cfg.restart_after_cold):
                    self._hinted_no_peers = True
                    log.warning("no peer connected after %.0f s: DHT/trackers may be blocked on this network - try "
                                "`kino-stream doctor --network`, a .torrent file with --peer hints, or --encryption forced",
                                self.cfg.restart_after_cold)
                if self._waiters:                            # belt and braces: never rely on alerts alone
                    self._reconcile()
                if time.monotonic() - last_resume > self.cfg.resume_interval:
                    last_resume = time.monotonic()
                    if self.handle.need_save_resume_data():
                        await self._save_resume()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ticker iteration failed")

    async def _sampler(self) -> None:
        """Peer availability bookkeeping: time with no connected peer (while something is wanted, and in total)."""
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.25)
            now = time.monotonic()
            if self.handle is None or self.piece_map is None:
                last = now
                continue
            if self._restarting:
                last = now
                continue
            stt = self.handle.status()
            n = stt.num_peers
            if n > self._last_n:                       # net changes between samples: a lower bound of real churn
                self._counters["peer_connects"] += n - self._last_n
            elif n < self._last_n:
                self._counters["peer_disconnects"] += self._last_n - n
            self._last_n = n
            self._peers_max = max(self._peers_max, n)
            # connected but silent: a stuck connection never shows up as 'no peers', so watch payload progress too
            pay = stt.total_payload_download
            self._ever_downloaded = self._ever_downloaded or pay > 0 or self._dl_base > 0
            if self._payload_stalled(pay, n, now):
                asyncio.ensure_future(self._restart(f"connected to {n} peers but no payload for {self._stuck_limit():.0f}s"))
            self._ever_had_peer = self._ever_had_peer or n > 0
            if n == 0:
                self._zero_peer_all_s += now - last
                if self._applied:
                    self._zero_peer_s += now - last
                    if self._no_peer_since is None:
                        self._no_peer_since = now
                    elif (now - self._no_peer_since >= (self.cfg.restart_after if self._ever_had_peer else self.cfg.restart_after_cold)
                          and now - self._last_restart >= 15):
                        asyncio.ensure_future(self._restart("no peers while data is wanted"))
            else:
                self._no_peer_since = None
            last = now

    def _payload_stalled(self, pay: int, n: int, now: float) -> bool:
        """Progress bookkeeping for the sampler: True when `n` connected peers delivered no payload for _stuck_limit() seconds while data is wanted
        (the caller then re-adds the torrent). `pay` is the payload counter of the *current* libtorrent handle."""
        if pay < self._pay_mark:
            # A new handle (restart or eviction re-add) counts payload from zero. Without this rebase the old high-water mark made healthy downloading
            # look like "no payload" until the new handle had re-downloaded as much as the old one, and the torrent was restarted again every stuck_after
            # seconds. The new handle gets a fresh observation window; the thresholds themselves are unchanged.
            self._pay_mark, self._pay_t = pay, now
        if pay - self._pay_mark >= 1000 * max(now - self._pay_t, 0.25) or not self._applied:
            self._pay_mark, self._pay_t = pay, now
            return False
        if n > 0 and now - self._pay_t >= self._stuck_limit() and now - self._last_restart >= 15:
            self._pay_t = now
            return True
        return False

    def _stuck_limit(self) -> float:
        """Seconds without payload (while peers are connected and data is wanted) before the torrent is re-added: the long limit once anything
        has ever been downloaded, the cold-start limit before that. The restart message reports this actual value."""
        return self.cfg.stuck_after if self._ever_downloaded else self.cfg.restart_after_cold

    def stats(self) -> dict:
        d = dict(self._counters)
        d.update(zero_peer_s=round(self._zero_peer_s, 2), zero_peer_all_s=round(self._zero_peer_all_s, 2),
                 peers_max=self._peers_max)
        if self.handle is not None and self.piece_map is not None and not self._restarting:
            st = self.handle.status()
            d.update(peers=st.num_peers, state=str(st.state), total_download=self._dl_base + st.total_payload_download,
                     total_upload=st.total_payload_upload, piece_length=self.piece_map.piece_length,
                     pieces_have=sum(self._have), pieces_total=self.piece_map.num_pieces,
                     applied=len(self._applied))
        d["error"] = self._error
        return d

    # --------------------------------------------------------------------------- resume/close
    async def _save_resume(self) -> bool:
        self._saved = self.loop.create_future()
        self.handle.save_resume_data(lt.save_resume_flags_t.flush_disk_cache | lt.save_resume_flags_t.save_info_dict)
        try:
            params = await asyncio.wait_for(self._saved, 10)
        except asyncio.TimeoutError:
            return False
        if params is None:
            return False
        (self.cfg.state_dir / f"{self._infohash}.resume").write_bytes(params)
        return True

    async def close(self) -> None:
        for t in (self._tick_task, self._sampler_task):
            if t:
                t.cancel()
        if self.handle is not None and self.piece_map is not None and self._error is None:
            try:
                await self._save_resume()
            except Exception:
                log.exception("saving resume data failed")
        self._pump_stop.set()
        for fs in self._waiters.values():
            for f in fs:
                if not f.done():
                    f.cancel()
        self._waiters.clear()
        if self.session is not None and self.handle is not None:
            try:
                self.session.remove_torrent(self.handle, lt.session.delete_files if not self.cfg.keep_data else 0)
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
