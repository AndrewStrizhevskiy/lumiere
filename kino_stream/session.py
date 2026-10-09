# SPDX-License-Identifier: GPL-3.0-or-later
"""StreamSession: wires store -> scheduler -> HTTP server (-> mpv). One torrent, one selected video file."""
from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

from .config import Config
from .httpd import StreamServer
from .bounded_store import BoundedSparseStore
from .lt_store import PersistentFileStore
from .mpvctl import Mpv
from .scheduler import Scheduler
from .store import PieceStore

VIDEO_EXT = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".ts", ".m2ts", ".wmv", ".webm"}


def pick_video_file(piece_map) -> int:
    vids = [f for f in piece_map.files if Path(f.path).suffix.lower() in VIDEO_EXT]
    pool = vids or piece_map.files
    return max(pool, key=lambda f: f.size).index


class StreamSession:
    def __init__(self, cfg: Config, store: PieceStore, file_index: int):
        self.cfg, self.store, self.file_index = cfg, store, file_index
        self.sched = Scheduler(cfg, store, file_index)
        self.server = StreamServer(cfg, store, self.sched, file_index, secrets.token_urlsafe(12))
        self.mpv: Mpv | None = None
        self._sched_task: asyncio.Task | None = None

    @classmethod
    async def open(cls, cfg: Config, source, save_path, file_index: int | None = None,
                   store: PieceStore | None = None) -> "StreamSession":
        if store is None:
            cls_ = BoundedSparseStore if cfg.cache_limit_bytes else PersistentFileStore
            store = await cls_.open(cfg, source, save_path, select=pick_video_file if file_index is None else file_index)
        fi = pick_video_file(store.piece_map) if file_index is None else file_index
        try:
            self = cls(cfg, store, fi)                    # may raise (e.g. cache limit too small for the window)
            await self.server.start()
        except BaseException:
            await asyncio.shield(store.close())           # never leak an open torrent session when construction fails
            raise
        self._sched_task = asyncio.create_task(self.sched.run())
        return self

    @property
    def url(self) -> str:
        return self.server.url()

    async def play(self, headless: bool = False, extra_args: list[str] | None = None, use_user_config: bool = True,
                   ipc_path: str | None = None) -> Mpv:
        rt = Path(ipc_path) if ipc_path else Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / f"kino-stream-{os.getpid()}.sock"
        self.mpv = Mpv(self.cfg, self.url, rt, title=Path(self.store.piece_map.files[self.file_index].path).name,
                       headless=headless, extra_args=extra_args, use_user_config=use_user_config)
        self.mpv.on_state = self.sched.update_player
        self.sched.expect_player = True
        await self.mpv.start()
        return self.mpv

    async def close(self) -> None:
        if self.mpv:
            await self.mpv.stop()
        if self._sched_task:
            self._sched_task.cancel()
        await self.server.close()
        await self.store.close()
