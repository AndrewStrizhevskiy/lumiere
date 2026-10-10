# SPDX-License-Identifier: GPL-3.0-or-later
"""Demand-driven HTTP/1.1 Range server (asyncio, stdlib only).

Contract:
  * bytes are only ever sent after the pieces covering them are present in the store (verified by the store's
    own read()); missing data is waited for, never zero-filled, never truncated-and-called-complete;
  * `Range: bytes=N-` is honoured as a request, but the connection is *gated* by the scheduler: it streams only
    as far as head + window and is released as the head moves. It does not turn into "download until EOF";
  * a client that goes away cancels its wait and its demand immediately;
  * if a piece does not arrive within hard_timeout the connection is aborted (the client sees a short body and
    can reconnect), instead of completing it with garbage.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import re
import socket
import time
from pathlib import Path
from urllib.parse import unquote

from .config import Config
from .scheduler import Conn, Scheduler
from .store import PieceStore, PieceTimeout, PieceUnavailable, StoreError

log = logging.getLogger("lumiere.http")
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeError(Exception):
    pass


def parse_range(header: str | None, size: int) -> tuple[int, int, bool]:
    """-> (first, last_inclusive, is_partial). Raises RangeError for unsatisfiable/unsupported ranges."""
    if not header:
        return 0, size - 1, False
    m = _RANGE.match(header.strip().lower().replace(" ", ""))
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise RangeError("unsupported")                       # multi-range and garbage: 416
    a, b = m.group(1), m.group(2)
    if a == "":                                                # suffix: last N bytes
        n = int(b)
        if n == 0:
            raise RangeError("empty suffix")
        return max(0, size - n), size - 1, True
    first = int(a)
    last = size - 1 if b == "" else min(int(b), size - 1)
    if first >= size or last < first:
        raise RangeError("unsatisfiable")
    return first, last, True


class StreamServer:
    def __init__(self, cfg: Config, store: PieceStore, sched: Scheduler, file_index: int, token: str):
        self.cfg, self.store, self.sched, self.file_index, self.token = cfg, store, sched, file_index, token
        self.f = store.piece_map.files[file_index]
        self.name = Path(self.f.path).name
        self.mime = mimetypes.guess_type(self.name)[0] or "application/octet-stream"
        self.port = 0
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task] = set()
        self._verify_fd = open(cfg.verify_source, "rb") if cfg.verify_source else None
        self.stats = {"requests": 0, "bytes_sent": 0, "piece_waits": 0, "wait_seconds": 0.0, "stalls": 0,
                      "aborted": 0, "mismatches": 0, "disconnects": 0, "first_byte_s": []}

    @property
    def path(self) -> str:
        return f"/{self.token}/{self.name}"

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.path}"

    async def start(self, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._client, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        if self._server:
            self._server.close()
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._verify_fd:
            self._verify_fd.close()

    # ---------------------------------------------------------------------------------- plumbing
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        sock = writer.get_extra_info("socket")
        if sock is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.cfg.sndbuf)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
        try:
            while await self._one_request(reader, writer):
                pass
        except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            log.exception("http handler crashed")
        finally:
            self._tasks.discard(task)
            try:
                writer.close()
            except Exception:
                pass

    async def _one_request(self, reader, writer) -> bool:
        try:
            raw = await reader.readuntil(b"\r\n\r\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return False
        lines = raw.decode("latin-1").split("\r\n")
        try:
            method, target, _ = lines[0].split(" ", 2)
        except ValueError:
            return await self._simple(writer, 400, "bad request")
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        t0 = time.monotonic()
        self.stats["requests"] += 1
        if method not in ("GET", "HEAD"):
            return await self._simple(writer, 405, "method not allowed", {"Allow": "GET, HEAD"})
        host = headers.get("host", "").lower()
        if host not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return await self._simple(writer, 403, "bad host")      # DNS-rebinding guard
        if unquote(target.split("?", 1)[0]) != self.path:
            return await self._simple(writer, 404, "not found")
        size = self.f.size
        try:
            first, last, partial = parse_range(headers.get("range"), size)
        except RangeError:
            return await self._simple(writer, 416, "range not satisfiable", {"Content-Range": f"bytes */{size}"})
        hdr = [f"HTTP/1.1 {206 if partial else 200} {'Partial Content' if partial else 'OK'}",
               f"Content-Type: {self.mime}", "Accept-Ranges: bytes", f"Content-Length: {last - first + 1}",
               "Cache-Control: no-store", "Connection: keep-alive"]
        if partial:
            hdr.append(f"Content-Range: bytes {first}-{last}/{size}")
        writer.write(("\r\n".join(hdr) + "\r\n\r\n").encode())
        if method == "HEAD":
            await writer.drain()
            return True
        return await self._body(reader, writer, first, last, t0)

    async def _simple(self, writer, code, text, extra=None) -> bool:
        body = text.encode()
        h = [f"HTTP/1.1 {code} {text.title()}", f"Content-Length: {len(body)}", "Connection: close"]
        h += [f"{k}: {v}" for k, v in (extra or {}).items()]
        writer.write(("\r\n".join(h) + "\r\n\r\n").encode() + body)
        await writer.drain()
        return False

    # -------------------------------------------------------------------------------------- body
    async def _body(self, reader, writer, first, last, t0) -> bool:
        sched, store = self.sched, self.store
        conn = sched.open_connection(first, last)

        def alive() -> bool:
            return not (reader.at_eof() or writer.transport.is_closing())

        pos = first
        first_byte = True
        try:
            while pos <= last:
                if not alive():
                    self.stats["disconnects"] += 1
                    return False
                n = min(self.cfg.chunk_bytes, last + 1 - pos)
                if not await sched.permit(conn, pos + n, alive):
                    self.stats["disconnects"] += 1
                    return False
                data = await self._get(conn, pos, n, alive)
                if data is None:
                    self.stats["disconnects"] += 1
                    return False
                if self._verify_fd is not None:
                    self._verify_fd.seek(pos)                       # verify_source is the original *file*
                    if self._verify_fd.read(len(data)) != data:
                        self.stats["mismatches"] += 1
                        log.error("MISMATCH at %d+%d", pos, len(data))
                writer.write(data)
                await writer.drain()
                pos += len(data)
                self.stats["bytes_sent"] += len(data)
                sched.advance(conn, pos)
                if first_byte:
                    first_byte = False
                    self.stats["first_byte_s"].append(time.monotonic() - t0)
            return True
        except (ConnectionError, asyncio.IncompleteReadError):
            self.stats["disconnects"] += 1
            return False
        except _Abort as e:
            log.error("aborting connection: %s", e)
            self.stats["aborted"] += 1
            writer.transport.abort()
            return False
        finally:
            sched.close_connection(conn)

    async def _get(self, conn: Conn, pos: int, n: int, alive) -> bytes | None:
        """Wait for the pieces of [pos, pos+n) and read them. None = client went away."""
        pm = self.store.piece_map
        started = time.monotonic()
        waited = False
        last_stall = started
        while True:
            need = list(pm.range_pieces(self.file_index, pos, pos + n - 1))
            missing = self.store.missing(need)
            if missing:
                waited = True
                slice_s = 0.25
                try:
                    await self.store.wait_have(missing, slice_s)
                except PieceTimeout:
                    pass
                except StoreError as e:
                    raise _Abort(str(e))
                if not alive() or conn.closed:
                    return None
                now = time.monotonic()
                if now - started > self.cfg.hard_timeout:
                    raise _Abort(f"pieces {missing[:4]} not available after {now - started:.0f}s")
                if now - last_stall > self.cfg.piece_timeout:
                    last_stall = now
                    self.stats["stalls"] += 1
                    self.sched.note_stall(missing)
                continue
            try:
                data = await asyncio.to_thread(self.store.read, self.file_index, pos, n)
            except PieceUnavailable:                       # lost between have() and read(), or not yet readable from the file: wait a moment and ask again
                if time.monotonic() - started > self.cfg.hard_timeout:
                    raise _Abort("data of a completed piece never became readable")
                if not alive() or conn.closed:
                    return None
                await asyncio.sleep(0.02)
                continue
            if waited:
                self.stats["piece_waits"] += 1
                self.stats["wait_seconds"] += time.monotonic() - started
            return data


class _Abort(Exception):
    pass
