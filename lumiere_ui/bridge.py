# SPDX-License-Identifier: GPL-3.0-or-later
"""Qt side of the engine connection: owns the EngineService, turns its thread callbacks into Qt signals, keeps settings and history.
This is the ONLY module of the UI that knows the engine exists, and it never touches torrents or the cache itself."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from lumiere import events as ev
from lumiere.recent import RecentItems
from lumiere.scheduler import PlayerState
from lumiere.service import EngineError, EngineService, MediaInfo, OpenOptions
from lumiere.settings import Settings


class EngineBridge(QObject):
    status = pyqtSignal(dict)
    event = pyqtSignal(object)                 # EngineEvent
    opened = pyqtSignal(object)                # MediaInfo
    openFailed = pyqtSignal(str, str)          # code, technical detail
    closed = pyqtSignal()
    ready = pyqtSignal(dict)                   # readiness() result
    networkChecked = pyqtSignal(dict)
    availability = pyqtSignal(list)            # per-slice fractions of the file that are on disk
    settingsChanged = pyqtSignal(object)

    def __init__(self, settings: Settings | None = None, state_dir: Path | None = None, recent: RecentItems | None = None, parent=None):
        super().__init__(parent)
        self.settings = (settings or Settings.load()).normalized()
        self.recent = recent or RecentItems()
        self.service = EngineService(self.settings, state_directory=state_dir)
        self.service.subscribe(self._from_engine)
        self.service.start()
        self.media: MediaInfo | None = None
        self.source: str = ""

    # engine thread -> Qt signals (queued automatically across threads)
    def _from_engine(self, kind: str, payload) -> None:
        if kind == "status":
            self.status.emit(payload)
        elif kind == "event":
            self.event.emit(payload)
        elif kind == "opened":
            self.media = payload
            self.recent.touch(payload.infohash, payload.title, self.source, payload.file_size)
            self.opened.emit(payload)
        elif kind == "closed":
            self.media = None
            self.closed.emit()

    # --------------------------------------------------------------------------------------------------- commands
    def open_source(self, source: str, temporary: bool = False, title: str | None = None, overrides: dict | None = None, peers: list | None = None) -> None:
        self.source = source
        opts = OpenOptions(temporary=temporary, title=title, engine_overrides=overrides or {}, peers=peers or [])
        fut = self.service.open(source, opts)

        def done(f):
            try:
                f.result()
            except EngineError as e:
                self.openFailed.emit(e.code, str(e))
            except Exception as e:                      # cancelled or unexpected
                if type(e).__name__ != "CancelledError":
                    self.openFailed.emit(ev.OPEN_FAILED, f"{type(e).__name__}: {e}")
        fut.add_done_callback(done)

    def cancel_open(self) -> None:
        self.service.cancel_open()

    def close_media(self) -> None:
        if self.media:
            self.recent  # position is saved by the player screen before this
        self.service.close_media()

    def feed_player(self, ps: PlayerState) -> None:
        self.service.update_player(ps)

    def player_event(self, name: str, detail: dict) -> None:
        self.service.report_player_event(name, detail)

    def request_availability(self, bins: int = 240) -> None:
        f = self.service.availability_async(bins)
        f.add_done_callback(lambda fu: None if fu.cancelled() else self.availability.emit(fu.result() if not fu.exception() else []))

    def save_position(self, infohash: str, pos: float, dur: float) -> None:
        self.recent.update_position(infohash, pos, dur)

    def mpv_limits(self, temporary: bool) -> tuple[int, int]:
        c = self.settings.to_config(temporary)
        return c.mpv_cache_bytes, c.mpv_back_bytes

    def check_ready(self) -> None:
        f = self.service.check_ready()
        f.add_done_callback(lambda fu: None if fu.cancelled() else self.ready.emit(fu.result() if not fu.exception() else {"ok": False, "problems": ["CACHE_DIR_UNUSABLE"], "free_bytes": 0}))

    def network_check(self) -> None:
        f = self.service.network_check()
        f.add_done_callback(lambda fu: None if fu.cancelled() else self.networkChecked.emit(fu.result() if not fu.exception() else {"error": str(fu.exception())}))

    def delete_cache(self, infohash: str) -> int:
        """Explicitly requested deletion of one managed cache. Refuses the video that is open. Returns bytes freed (0 if refused)."""
        from lumiere.caches import NotManaged, delete_managed_cache, list_caches
        if self.media and self.media.infohash == infohash:
            return 0
        root = self.settings.cache_root_path
        for c in list_caches(root):
            if c["infohash"] == infohash:
                try:
                    return delete_managed_cache(root, Path(c["path"]), self.service.state_dir)
                except NotManaged:
                    return 0
        return 0

    def apply_settings(self, s: Settings) -> None:
        self.settings = s.normalized()
        self.settings.save()
        self.service.update_settings(self.settings)
        self.settingsChanged.emit(self.settings)

    def shutdown(self) -> None:
        self.service.shutdown()
