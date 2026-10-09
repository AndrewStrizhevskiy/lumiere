"""EngineService: the one object a user interface talks to. No Qt/GTK imports; thread-safe from the outside.

* It owns a dedicated thread running an asyncio loop. EVERY libtorrent call happens on that thread (the Python binding is not safe to
  poke from several threads - see docs/KNOWN_ISSUES.md), the UI thread only ever calls the methods below and receives callbacks.
* The UI never manages torrents or the cache: it passes a torrent file / magnet link, plays `MediaInfo.url` in its own player, feeds
  the player state back with `update_player()`, and renders `snapshot()` / the events it is called with.
* Callbacks (`subscribe`) run on the engine thread and must only hand data over (e.g. emit a Qt signal).

    svc = EngineService(Settings.load()); svc.start()
    media = svc.open("movie.torrent").result()          # concurrent.futures.Future
    svc.update_player(PlayerState(...))                 # from the UI's player, ~4x per second
    svc.close_media()                                   # applies the "when I close a video" setting
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import events as ev
from .caches import MARKER, NotManaged, delete_managed_cache, prepare_cache_dir
from .config import MiB
from .events import EngineEvent
from .punch import allocated_bytes
from .scheduler import PlayerState
from .session import StreamSession
from .settings import Settings, state_dir
from .store import CacheDirNotManagedError, CacheTooSmallError, CacheUnsupportedError, StoreError

log = logging.getLogger("kino_stream.service")


class EngineError(Exception):
    """Failure with a stable machine-readable code; the UI turns it into a human explanation."""

    def __init__(self, code: str, message: str = "", detail: dict | None = None):
        super().__init__(message or code)
        self.code, self.detail = code, detail or {}


@dataclass
class OpenOptions:
    file_index: int | None = None
    peers: list = field(default_factory=list)            # [(host, port)] hints
    temporary: bool = False                              # explicit opt-in: no cache limit, deleted on close
    title: str | None = None
    engine_overrides: dict = field(default_factory=dict)  # Config attributes (tests / advanced use)


@dataclass
class MediaInfo:
    url: str
    title: str
    infohash: str
    file_index: int
    file_size: int
    cache_dir: str
    bounded: bool
    cache_limit: int
    piece_length: int
    pieces_total: int
    temporary: bool = False
    torrent_name: str = ""


def _infohash_of(source: str) -> tuple[str, str]:
    """-> (infohash hex, display name guess). Runs on the engine thread (libtorrent)."""
    import libtorrent as lt
    if isinstance(source, str) and source.startswith("magnet:"):
        p = lt.parse_magnet_uri(source)
        return str(p.info_hashes.v1), (p.name or "")
    try:
        ti = lt.torrent_info(str(source))
    except Exception as e:
        raise EngineError(ev.OPEN_FAILED, f"cannot read {source}: {e}")
    return str(ti.info_hash()), ti.name()


class EngineService:
    STATUS_INTERVAL = 0.5
    NO_PEERS_AFTER = 20.0          # seconds since opening without any connected source
    NET_LOST_AFTER = 3.0           # seconds without sources, after having had some, while data is wanted
    SLOW_STALL_SECONDS = 8.0       # accumulated buffering time (decaying over a minute) that counts as a slow connection

    def __init__(self, settings: Settings | None = None, state_directory: Path | None = None):
        self.settings = (settings or Settings()).normalized()
        self.state_dir = Path(state_directory) if state_directory else state_dir()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.thread_ident: int | None = None
        self._subs: list[Callable[[str, object], None]] = []
        self._snap: dict = {"phase": "idle"}
        self._session: StreamSession | None = None
        self._media: MediaInfo | None = None
        self._open_task: asyncio.Task | None = None
        self._status_task: asyncio.Task | None = None
        self._player: PlayerState | None = None
        self._reset_detectors()

    # ------------------------------------------------------------------------------------------ thread plumbing
    def start(self) -> None:
        if self.thread:
            return
        ready = threading.Event()

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.thread_ident = threading.get_ident()
            ready.set()
            try:
                self.loop.run_forever()
            finally:
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                self.loop.close()
        self.thread = threading.Thread(target=run, name="kino-engine", daemon=True)
        self.thread.start()
        ready.wait(5)

    def _submit(self, coro) -> concurrent.futures.Future:
        if self.loop is None:
            raise RuntimeError("EngineService.start() was not called")
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def subscribe(self, cb: Callable[[str, object], None]) -> None:
        """cb(kind, payload) with kind in {"status": dict, "event": EngineEvent, "opened": MediaInfo, "closed": None}."""
        self._subs.append(cb)

    def unsubscribe(self, cb) -> None:
        if cb in self._subs:
            self._subs.remove(cb)

    def _emit(self, kind: str, payload) -> None:
        for cb in list(self._subs):
            try:
                cb(kind, payload)
            except Exception:
                log.exception("subscriber failed")

    def _event(self, code: str, level: str = ev.INFO, **detail) -> None:
        self._emit("event", EngineEvent(code, level, detail))

    def snapshot(self) -> dict:
        return dict(self._snap)

    # ------------------------------------------------------------------------------------------------- public API
    def update_settings(self, settings: Settings) -> None:
        """Applies to the next opened video (a running stream keeps the values it started with)."""
        self.settings = settings.normalized()

    def open(self, source: str, options: OpenOptions | None = None) -> concurrent.futures.Future:
        """Start streaming `source` (a .torrent path or a magnet link). Future result: MediaInfo, or EngineError."""
        fut = self._submit(self._open(str(source), options or OpenOptions()))
        return fut

    def cancel_open(self) -> None:
        if self.loop and self._open_task:
            self.loop.call_soon_threadsafe(self._open_task.cancel)

    def close_media(self, cleanup: str | None = None) -> concurrent.futures.Future:
        """Stop streaming. `cleanup`: "keep" | "delete" | None (= the user's setting). Temporary mode always deletes."""
        return self._submit(self._close_media(cleanup))

    def update_player(self, ps: PlayerState) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(self._on_player, ps)

    def report_player_event(self, name: str, detail: dict | None = None) -> None:
        """For things only the player knows, e.g. ("file-error", {"reason": "unrecognized file format"})."""
        if self.loop:
            self.loop.call_soon_threadsafe(self._on_player_event, name, detail or {})

    def network_check(self) -> concurrent.futures.Future:
        """Read-only probes (DHT, UDP trackers, DNS over UDP, exit address) with confirmed/observed/hypothesis verdicts."""
        from .doctor import network_report
        return asyncio.run_coroutine_threadsafe(self._in_thread(network_report), self.loop)

    async def _in_thread(self, fn):
        return await asyncio.get_running_loop().run_in_executor(None, fn)

    def shutdown(self, timeout: float = 15.0) -> None:
        if not self.loop:
            return
        try:
            self._submit(self._close_media(None)).result(timeout)
        except Exception:
            log.exception("closing media at shutdown failed")
        self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout)
        self.loop = None
        self.thread = None

    # ---------------------------------------------------------------------------------------- engine-thread logic
    def _reset_detectors(self) -> None:
        self._opened_at = 0.0
        self._ever_peer = False
        self._zero_since: float | None = None
        self._net_lost = False
        self._last_no_peers = 0.0
        self._last_full = 0.0
        self._last_slow = 0.0
        self._last_evictions = 0
        self._stall_acc = 0.0
        self._stall_t = 0.0
        self._prev_dl = 0
        self._prev_t = 0.0
        self._rate = 0.0
        self._alloc = 0
        self._alloc_t = 0.0

    async def _open(self, source: str, opts: OpenOptions) -> MediaInfo:
        self._open_task = asyncio.current_task()
        try:
            await self._close_media(None)
            self._snap = {"phase": "opening", "message_code": "OPENING"}
            self._emit("status", self.snapshot())
            infohash, name = _infohash_of(source)
            root = self.settings.cache_root_path
            try:
                cache_dir = prepare_cache_dir(root, infohash, opts.temporary)
            except CacheDirNotManagedError as e:
                raise EngineError(ev.CACHE_DIR_NOT_MANAGED, str(e))
            cfg = self.settings.to_config(temporary=opts.temporary)
            cfg.state_dir = self.state_dir
            cfg.peers = list(opts.peers)
            for k, v in opts.engine_overrides.items():
                setattr(cfg, k, v)
            try:
                sess = await StreamSession.open(cfg, source, cache_dir, opts.file_index)
            except CacheUnsupportedError as e:
                raise EngineError(ev.CACHE_UNSUPPORTED_FS, str(e))
            except CacheTooSmallError as e:
                raise EngineError(ev.CACHE_TOO_SMALL, str(e))
            except CacheDirNotManagedError as e:
                raise EngineError(ev.CACHE_DIR_NOT_MANAGED, str(e))
            except StoreError as e:
                raise EngineError(ev.OPEN_FAILED, str(e))
            sess.sched.expect_player = True
            pm = sess.store.piece_map
            f = pm.files[sess.file_index]
            self._session = sess
            self._media = MediaInfo(url=sess.url, title=opts.title or Path(f.path).stem or name, infohash=infohash,
                                    file_index=sess.file_index, file_size=f.size, cache_dir=str(cache_dir),
                                    bounded=bool(cfg.cache_limit_bytes), cache_limit=cfg.cache_limit_bytes,
                                    piece_length=pm.piece_length, pieces_total=pm.num_pieces, temporary=opts.temporary,
                                    torrent_name=name)
            self._reset_detectors()
            self._opened_at = time.monotonic()
            self._status_task = asyncio.create_task(self._status_loop())
            self._emit("opened", self._media)
            self._event(ev.READY)
            return self._media
        except asyncio.CancelledError:
            self._snap = {"phase": "idle"}
            self._emit("status", self.snapshot())
            raise
        except EngineError as e:
            self._snap = {"phase": "idle", "error": e.code}
            self._event(e.code, ev.ERROR, message=str(e))
            raise
        finally:
            self._open_task = None

    async def _close_media(self, cleanup: str | None) -> None:
        if self._status_task:
            self._status_task.cancel()
            self._status_task = None
        sess, media = self._session, self._media
        self._session = self._media = None
        if sess is None:
            return
        try:
            await sess.close()
        finally:
            policy = cleanup or self.settings.on_close
            if media and (media.temporary or policy == "delete"):
                try:
                    freed = delete_managed_cache(self.settings.cache_root_path, Path(media.cache_dir), self.state_dir)
                    log.info("deleted cache %s (%.1f MiB)", media.cache_dir, freed / MiB)
                except NotManaged as e:
                    log.error("%s", e)
            self._snap = {"phase": "idle"}
            self._emit("closed", None)

    def _on_player(self, ps: PlayerState) -> None:
        self._player = ps
        if self._session:
            self._session.sched.update_player(ps)

    def _on_player_event(self, name: str, detail: dict) -> None:
        reason = str(detail.get("reason", "")).lower()
        if name == "file-error" and any(k in reason for k in ("unrecognized", "format", "loading failed", "unsupported", "no video")):
            self._event(ev.UNSUPPORTED_FILE, ev.ERROR, **detail)
        elif name == "file-error":
            self._event(ev.PLAYER_ERROR, ev.ERROR, **detail)

    # ---------------------------------------------------------------------------------------------- status loop
    async def _status_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.STATUS_INTERVAL)
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("status tick failed")
        except asyncio.CancelledError:
            pass

    def availability(self, bins: int = 200) -> list[float]:
        """Fraction of each 1/bins slice of the file that is on disk (approximate: pieces, not video time)."""
        sess = self._session
        if not sess:
            return []
        store, pm, fi = sess.store, sess.store.piece_map, sess.file_index
        f = pm.files[fi]
        p0 = f.start // pm.piece_length
        p1 = (f.start + f.size - 1) // pm.piece_length
        n = p1 - p0 + 1
        have = getattr(store, "_have", None)
        out = []
        for i in range(bins):
            a, b = p0 + i * n // bins, max(p0 + (i + 1) * n // bins, p0 + i * n // bins + 1)
            if have is not None:
                c = have[a:b].count(1)
            else:
                c = sum(1 for p in range(a, b) if store.have(p))
            out.append(round(c / (b - a), 2))
        return out

    async def _tick(self) -> None:
        sess, media = self._session, self._media
        if sess is None or media is None:
            return
        now = time.monotonic()
        st = sess.store.stats()
        peers = int(st.get("peers") or 0)
        dl = int(st.get("total_download") or 0)
        if self._prev_t:
            inst = max(0, dl - self._prev_dl) / max(now - self._prev_t, 0.01)
            self._rate = 0.7 * self._rate + 0.3 * inst
        self._prev_dl, self._prev_t = dl, now
        if media.bounded and now - self._alloc_t > 1.0:
            self._alloc = await asyncio.get_running_loop().run_in_executor(None, allocated_bytes, Path(media.cache_dir))
            self._alloc_t = now
        elif not media.bounded and now - self._alloc_t > 2.0:
            self._alloc = await asyncio.get_running_loop().run_in_executor(None, allocated_bytes, Path(media.cache_dir))
            self._alloc_t = now
        pm = sess.store.piece_map
        head = sess.sched.head_byte()
        f = pm.files[sess.file_index]
        have = getattr(sess.store, "_have", None)
        ahead = 0
        if have is not None:                                   # contiguous bytes on disk after the playhead
            p = (f.start + head) // pm.piece_length
            while p < len(have) and have[p] and ahead < 200_000_000_000:
                p += 1
                ahead += pm.piece_length
                if ahead > 4_000_000_000:
                    break
            ahead = max(0, ahead - (f.start + head) % pm.piece_length)
        bps = sess.sched.bytes_per_s()
        ps = self._player
        phase = "playing"
        if ps is None:
            phase = "starting"
        elif ps.paused_for_cache:
            phase = "buffering"
        elif ps.paused:
            phase = "paused"
        snap = {"phase": phase, "title": media.title, "infohash": media.infohash, "file_size": media.file_size,
                "peers": peers, "seeds": int(st.get("seeds") or 0), "down_Bps": int(self._rate), "up_Bps": 0,
                "pieces_have": int(st.get("pieces_have") or 0), "pieces_total": media.pieces_total,
                "cache_used": int(self._alloc), "cache_limit": media.cache_limit, "bounded": media.bounded,
                "evictions": int(st.get("evictions") or 0), "ahead_bytes": int(ahead),
                "ahead_seconds": round(ahead / bps, 1) if bps else None, "head_byte": int(head),
                "window_bytes": int(sess.sched.window_bytes()), "bitrate_Bps": int(bps),
                "restarts": int(st.get("restarts") or 0), "store_error": st.get("error"),
                "http_mismatches": sess.server.stats["mismatches"], "temporary": media.temporary,
                "ever_connected": self._ever_peer}
        self._snap = snap
        self._detect(now, st, peers, ps, media, sess)
        self._emit("status", snap)

    def _detect(self, now, st, peers, ps, media, sess) -> None:
        wanted = bool(getattr(sess.store, "_applied", None))
        if peers > 0:
            self._ever_peer = True
            self._zero_since = None
            if self._net_lost:
                self._net_lost = False
                self._event(ev.NETWORK_RESTORED)
        else:
            if self._zero_since is None:
                self._zero_since = now
            if self._ever_peer and not self._net_lost and wanted and now - self._zero_since >= self.NET_LOST_AFTER:
                self._net_lost = True
                self._event(ev.NETWORK_LOST, ev.WARNING)
            if not self._ever_peer and now - self._opened_at >= self.NO_PEERS_AFTER and now - self._last_no_peers >= 60.0:
                self._last_no_peers = now
                self._event(ev.NO_PEERS, ev.WARNING, seconds=int(now - self._opened_at))
        evictions = int(st.get("evictions") or 0)
        pressure = bool(getattr(sess.store, "truncated", 0))
        if media.bounded and (evictions > self._last_evictions or pressure) and now - self._last_full >= 15.0:
            self._last_full = now
            self._event(ev.CACHE_FULL, ev.INFO, evictions=evictions)
        self._last_evictions = evictions
        if ps is not None:                                      # slow connection: waiting for data for long, rate below bitrate
            dt = now - self._stall_t if self._stall_t else 0.0
            self._stall_t = now
            self._stall_acc = max(0.0, self._stall_acc * (1 - dt / 60.0)) + (dt if ps.paused_for_cache else 0.0)
            if (self._stall_acc >= self.SLOW_STALL_SECONDS and self._rate < sess.sched.bytes_per_s() and now - self._last_slow >= 60.0):
                self._last_slow = now
                self._stall_acc = 0.0
                self._event(ev.SLOW_CONNECTION, ev.WARNING, rate=int(self._rate), bitrate=int(sess.sched.bytes_per_s()))
        if st.get("error") and not getattr(self, "_reported_store_error", False):
            self._reported_store_error = True
            self._event(ev.STORE_FAILED, ev.ERROR, message=str(st.get("error")))
