# SPDX-License-Identifier: GPL-3.0-or-later
"""Test environment: generated legal media, a local throttled seeder, tracker-less leecher config, raw HTTP client."""
from __future__ import annotations

import asyncio
import hashlib
import os
import random
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import libtorrent as lt

from lumiere.config import Config, KiB, MiB
from lumiere.piecemap import PieceMap
from lumiere.store import Demand, PieceStore, PieceTimeout, PieceUnavailable

CACHE = Path(__file__).parent / ".cache" / "media"
PIECE_LENGTH = 64 * KiB


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------------------------------- media
def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def media() -> dict[str, Path]:
    """Three ~16 MB, 120 s test videos generated with ffmpeg from synthetic sources (our own, no third-party content):
    moov at start, moov at end, MKV (Cues at the end)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    base = CACHE / "base.mp4"
    if not base.exists():
        _ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
                 "-t", "120", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "900k", "-maxrate", "2M",
                 "-bufsize", "2M", "-g", "50", "-c:a", "aac", "-b:a", "96k", str(base) + ".tmp.mp4"])
        os.replace(str(base) + ".tmp.mp4", base)
    out = {"moov_end": CACHE / "moov_end.mp4", "moov_front": CACHE / "moov_front.mp4", "mkv_cues_end": CACHE / "cues_end.mkv"}
    if not out["moov_end"].exists():
        shutil.copy(base, out["moov_end"])
    if not out["moov_front"].exists():
        _ffmpeg(["-i", str(base), "-c", "copy", "-movflags", "+faststart", str(out["moov_front"]) + ".tmp.mp4"])
        os.replace(str(out["moov_front"]) + ".tmp.mp4", out["moov_front"])
    if not out["mkv_cues_end"].exists():
        _ffmpeg(["-i", str(base), "-c", "copy", str(out["mkv_cues_end"]) + ".tmp.mkv"])
        os.replace(str(out["mkv_cues_end"]) + ".tmp.mkv", out["mkv_cues_end"])
    return out


def random_file(path: Path, size: int, seed: int = 7) -> Path:
    r = random.Random(seed)
    with open(path, "wb") as f:
        left = size
        while left:
            n = min(MiB, left)
            f.write(r.randbytes(n)); left -= n
    return path


def sha(path: Path, a: int = 0, n: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        f.seek(a)
        left = n
        while left is None or left > 0:
            c = f.read(MiB if left is None else min(MiB, left))
            if not c:
                break
            h.update(c)
            left = None if left is None else left - len(c)
    return h.hexdigest()


# ------------------------------------------------------------------------------------ swarm
class Seeder:
    """A libtorrent session seeding `root` (a file or a directory) on 127.0.0.1, upload-throttled."""

    def __init__(self, root: Path, upload_limit: int = 0, piece_length: int = PIECE_LENGTH, hybrid: bool = False,
                 seed_mode: bool = True, ti=None, data_parent: Path | None = None, trust_data: bool = False):
        """`ti` + `data_parent` let several seeders share one torrent while holding different data (e.g. a corrupted copy)."""
        self.root = Path(root)
        if ti is None:
            fs = lt.file_storage()
            lt.add_files(fs, str(self.root))
            ct = lt.create_torrent(fs, piece_length, flags=0 if hybrid else lt.create_torrent.v1_only)
            lt.set_piece_hashes(ct, str(self.root.parent))
            ti = lt.torrent_info(lt.bencode(ct.generate()))
        self.ti = ti
        self.port = free_port()
        self.session = lt.session({
            "listen_interfaces": f"127.0.0.1:{self.port}", "enable_dht": False, "enable_lsd": False,
            "enable_upnp": False, "enable_natpmp": False, "ignore_limits_on_local_network": False,
            "upload_rate_limit": upload_limit, "allow_multiple_connections_per_ip": True,
            "alert_mask": int(lt.alert.category_t.status_notification)})
        p = lt.add_torrent_params()
        p.ti = self.ti
        p.save_path = str(data_parent or self.root.parent)
        if trust_data:            # claim every piece without verifying it (seed_mode would verify before uploading)
            p.have_pieces = [True] * ti.num_pieces()
            p.flags |= lt.torrent_flags.no_verify_files
        elif seed_mode:
            p.flags |= lt.torrent_flags.seed_mode
        self.handle = self.session.add_torrent(p)
        # Listen sockets open asynchronously; a leech that dials in during the first moments can sit in a 15 s uTP
        # retry. Wait until both TCP and uTP listeners are up (a test-environment artefact, found via the magnet test).
        n_listen = 0
        end = time.time() + 5
        while time.time() < end and n_listen < 2:
            time.sleep(0.1)                  # NEVER wait_for_alert(): it hands out a pointer into the live alert queue (crashes)
            n_listen += sum(isinstance(a, lt.listen_succeeded_alert) for a in self.session.pop_alerts())   # use alerts before the next pop
        time.sleep(1.0)       # empirically needed: a leech dialling within ~1 s of the seeder's start can stall for 15 s

    def set_upload_limit(self, bps: int) -> None:
        self.session.apply_settings({"upload_rate_limit": bps})

    def pause(self) -> None:
        self.handle.pause()

    def resume(self) -> None:
        self.handle.resume()

    @property
    def uploaded(self) -> int:
        return self.handle.status().total_payload_upload

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self.session.remove_torrent(self.handle)


def leech_config(tmp: Path, seeder, **over) -> Config:
    seeders = seeder if isinstance(seeder, (list, tuple)) else [seeder]
    cfg = Config(
        listen=f"127.0.0.1:{free_port()}", dht=False, lsd=False, upnp=False, peers=[("127.0.0.1", s.port) for s in seeders],
        state_dir=tmp / "state", limits_on_lan=True, metadata_timeout=20.0, wake_interval=1.0)
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


# ------------------------------------------------------------------------------ HTTP client
async def http_range(url_port: int, path: str, rng: str | None, read: int | None = None, *,
                     close_after_read: bool = True, host_header: str | None = None, chunk: int = 64 * KiB,
                     deadline_s: float = 120.0):
    """Minimal client. Returns (status, headers, body_bytes, first_byte_seconds, elapsed). Reads `read` body bytes
    (all of Content-Length if None) and then closes the socket (like mpv does)."""
    t0 = time.monotonic()
    reader, writer = await asyncio.open_connection("127.0.0.1", url_port)
    host = host_header or f"127.0.0.1:{url_port}"
    req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\n" + (f"Range: {rng}\r\n" if rng else "") + "Connection: keep-alive\r\n\r\n"
    writer.write(req.encode())
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    hdrs = {k.strip().lower(): v.strip() for k, v in (l.split(":", 1) for l in lines[1:] if ":" in l)}
    total = int(hdrs.get("content-length", "0"))
    want = total if read is None else min(read, total)
    body = bytearray()
    first = None
    while len(body) < want:
        c = await asyncio.wait_for(reader.read(min(chunk, want - len(body))), deadline_s)
        if not c:
            break
        if first is None:
            first = time.monotonic() - t0
        body += c
    if close_after_read:
        writer.close()
    return status, hdrs, bytes(body), first, time.monotonic() - t0


async def eventually(cond, timeout: float, step: float = 0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(step)
    return cond()


# --------------------------------------------------------------------------------- fake store
class FakeStore(PieceStore):
    """In-memory store for scheduler/HTTP unit tests. Records the demand it was given. Pieces appear on command."""

    def __init__(self, files: list[tuple[str, bytes]], piece_length: int = 1000):
        from lumiere.piecemap import FileSpan
        off, spans, blobs = 0, [], []
        for i, (name, data) in enumerate(files):
            spans.append(FileSpan(i, off, len(data), name)); blobs.append(data); off += len(data)
        self.blob = b"".join(blobs)
        self.piece_map = PieceMap(piece_length, off, spans)
        self._have = [False] * self.piece_map.num_pieces
        self._futs: dict[int, list[asyncio.Future]] = {}
        self.demand = Demand()
        self.demand_log: list[Demand] = []
        self.wakes: list[str] = []
        self.forced: list[set] = []
        self.listeners = []

    def give(self, *pieces: int) -> None:
        for p in pieces:
            self._have[p] = True
            for f in self._futs.pop(p, []):
                if not f.done():
                    f.set_result(None)

    def give_all(self) -> None:
        self.give(*range(self.piece_map.num_pieces))

    def lose(self, piece: int) -> None:
        self._have[piece] = False
        for cb in self.listeners:
            cb("lost", piece)

    def have(self, piece): return self._have[piece]

    async def wait_have(self, pieces, timeout):
        fs = []
        for p in set(pieces):
            if not self._have[p]:
                f = asyncio.get_running_loop().create_future()
                self._futs.setdefault(p, []).append(f); fs.append((p, f))
        if not fs:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*(f for _, f in fs)), timeout)
        except asyncio.TimeoutError:
            raise PieceTimeout([p for p, f in fs if not f.done()]) from None

    def read(self, file_index, offset, length):
        f = self.piece_map.files[file_index]
        need = list(self.piece_map.range_pieces(file_index, offset, offset + length - 1))
        gone = [p for p in need if not self._have[p]]
        if gone:
            raise PieceUnavailable(gone)
        return self.blob[f.start + offset:f.start + offset + length]

    def apply_demand(self, demand, force=()):
        self.demand = demand
        self.demand_log.append(demand)
        self.forced.append(set(force))

    def wake(self, reason=""): self.wakes.append(reason)
    def add_listener(self, cb): self.listeners.append(cb)
    def stats(self): return {}
    async def close(self): pass


# ------------------------------------------------------------------------------- utilities
def disk_usage(path: Path) -> int:
    """Bytes actually allocated on disk (st_blocks), part-files and hidden files included."""
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_blocks * 512
        except OSError:
            pass
    return total


METRICS_FILE = Path(__file__).parent / ".cache" / "metrics.json"


def record(name: str, value) -> None:
    import json
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        d = json.loads(METRICS_FILE.read_text())
    except Exception:
        d = {}
    d[name] = value
    METRICS_FILE.write_text(json.dumps(d, indent=1, sort_keys=True))


async def open_stream(tmp: Path, seeder, source_file: Path | None = None, file_index: int | None = None, **over):
    from lumiere.session import StreamSession
    cfg = leech_config(tmp, seeder, verify_source=source_file, **over)
    first = seeder[0] if isinstance(seeder, (list, tuple)) else seeder
    return await StreamSession.open(cfg, first.ti, tmp / "dl", file_index)
