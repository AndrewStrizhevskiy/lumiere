"""mpv launcher + JSON IPC client. IPC is the authoritative source of playback state."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from .config import Config, MiB
from .scheduler import PlayerState

_PROPS = ("time-pos", "duration", "paused-for-cache", "pause", "seeking", "cache-speed", "demuxer-cache-state",
          "demuxer-cache-time", "core-idle")


class MpvError(Exception):
    pass


class Mpv:
    def __init__(self, cfg: Config, url: str, ipc_path: Path, title: str = "", headless: bool = False,
                 extra_args: list[str] | None = None, use_user_config: bool = True):
        self.cfg, self.url, self.ipc_path, self.title = cfg, url, Path(ipc_path), title
        self.headless, self.extra, self.use_user_config = headless, extra_args or [], use_user_config
        self.proc: asyncio.subprocess.Process | None = None
        self._r: asyncio.StreamReader | None = None
        self._w: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._rid = 0
        self.events: list[tuple[float, str, dict]] = []
        self.state: PlayerState | None = None
        self.samples: list[tuple[float, float | None]] = []     # (monotonic, time-pos)
        self.on_state = None
        self.started_at = 0.0
        self.rebuffers = 0              # paused-for-cache episodes after playback first started
        self.rebuffer_s = 0.0
        self.initial_buffer_s = 0.0
        self._playing_seen = False
        self._pfc_since: float | None = None

    def argv(self) -> list[str]:
        a = ["mpv"]
        if not self.use_user_config:
            a.append("--no-config")
        a += [f"--input-ipc-server={self.ipc_path}",
              # bound mpv's own buffering: otherwise it slurps ~150 MiB ahead on its own
              f"--demuxer-max-bytes={self.cfg.mpv_cache_bytes // MiB}MiB",
              f"--demuxer-max-back-bytes={self.cfg.mpv_back_bytes // MiB}MiB",
              "--cache=yes", "--cache-pause=yes", "--cache-pause-initial=no",
              f"--network-timeout={self.cfg.mpv_network_timeout}", "--idle=no", "--keep-open=no"]
        if self.headless:
            a += ["--vo=null", "--ao=null", "--really-quiet"]
        if self.title:
            a.append(f"--force-media-title={self.title}")
        return a + self.extra + ["--", self.url]

    async def start(self) -> None:
        if shutil.which("mpv") is None:
            raise MpvError("mpv not installed")
        self.ipc_path.parent.mkdir(parents=True, exist_ok=True)
        if self.ipc_path.exists():
            self.ipc_path.unlink()
        self.started_at = time.monotonic()
        self.proc = await asyncio.create_subprocess_exec(*self.argv(), stdout=asyncio.subprocess.DEVNULL,
                                                         stderr=asyncio.subprocess.DEVNULL)
        for _ in range(100):
            if self.ipc_path.exists():
                try:
                    self._r, self._w = await asyncio.open_unix_connection(str(self.ipc_path))
                    break
                except OSError:
                    pass
            if self.proc.returncode is not None:
                raise MpvError(f"mpv exited early with {self.proc.returncode}")
            await asyncio.sleep(0.1)
        else:
            raise MpvError("mpv IPC socket never appeared")
        self._reader_task = asyncio.create_task(self._read())
        self._poll_task = asyncio.create_task(self._poll())

    async def _read(self) -> None:
        try:
            while True:
                line = await self._r.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "event" in msg:
                    self.events.append((time.monotonic(), msg["event"], msg))
                elif "request_id" in msg:
                    f = self._pending.pop(msg["request_id"], None)
                    if f and not f.done():
                        f.set_result(msg)
        finally:
            for f in self._pending.values():
                if not f.done():
                    f.set_exception(MpvError("mpv closed the IPC socket"))

    async def command(self, *args, timeout: float = 5.0):
        self._rid += 1
        rid = self._rid
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._w.write((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
        await self._w.drain()
        msg = await asyncio.wait_for(fut, timeout)
        if msg.get("error") != "success":
            raise MpvError(msg.get("error", "?"))
        return msg.get("data")

    async def get(self, prop: str, default=None):
        try:
            return await self.command("get_property", prop)
        except MpvError:
            return default

    async def seek(self, t: float, mode: str = "absolute") -> None:
        await self.command("seek", t, mode)

    async def _poll(self) -> None:
        try:
            while True:
                s = PlayerState(ts=time.monotonic())
                s.time_pos = await self.get("time-pos")
                s.duration = await self.get("duration")
                s.paused = bool(await self.get("pause", False))
                s.paused_for_cache = bool(await self.get("paused-for-cache", False))
                s.seeking = bool(await self.get("seeking", False))
                s.cache_speed = await self.get("cache-speed")
                dcs = await self.get("demuxer-cache-state") or {}
                s.fw_bytes = dcs.get("fw-bytes")
                s.ts = time.monotonic()
                self._track_rebuffer(s)
                self.state = s
                self.samples.append((s.ts, s.time_pos))
                if self.on_state:
                    self.on_state(s)
                await asyncio.sleep(self.cfg.poll_interval)
        except (MpvError, ConnectionError, asyncio.CancelledError, asyncio.TimeoutError):
            return

    def _track_rebuffer(self, s: PlayerState) -> None:
        if s.time_pos is not None and s.time_pos > 0.1 and not s.paused_for_cache:
            self._playing_seen = True
        if s.paused_for_cache and self._pfc_since is None:
            self._pfc_since = s.ts
            if self._playing_seen:
                self.rebuffers += 1
        elif not s.paused_for_cache and self._pfc_since is not None:
            dur = s.ts - self._pfc_since
            if self._playing_seen:
                self.rebuffer_s += dur
            else:
                self.initial_buffer_s += dur
            self._pfc_since = None

    def event_times(self, name: str) -> list[float]:
        return [t for t, e, _ in self.events if e == name]

    async def wait_playing(self, min_pos: float = 0.5, timeout: float = 60.0) -> float:
        """Seconds since start until time-pos passes min_pos."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.state
            if s and s.time_pos is not None and s.time_pos >= min_pos:
                return s.ts - self.started_at
            if self.proc.returncode is not None:
                raise MpvError(f"mpv exited ({self.proc.returncode}) before playing")
            await asyncio.sleep(0.05)
        raise MpvError("timeout waiting for playback")

    async def wait_pos(self, at_least: float, timeout: float = 60.0) -> float:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = self.state
            if s and s.time_pos is not None and s.time_pos >= at_least:
                return time.monotonic()
            await asyncio.sleep(0.05)
        raise MpvError(f"timeout waiting for time-pos >= {at_least} (last {self.state and self.state.time_pos})")

    async def stop(self) -> None:
        for t in (self._poll_task, self._reader_task):
            if t:
                t.cancel()
        if self.proc and self.proc.returncode is None:
            try:
                await self.command("quit", timeout=1)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        if self._w:
            self._w.close()
        if self.ipc_path.exists():
            self.ipc_path.unlink(missing_ok=True)
