# SPDX-License-Identifier: GPL-3.0-or-later
"""kino-stream: watch a torrent while it downloads, optionally with a hard-bounded disk cache.

    python3 -m kino_stream play file.torrent --save-path DIR --cache-limit-gb 3
    python3 -m kino_stream doctor [--save-path DIR] [--network]
"""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
import json
import logging
import signal
import sys
import time
from pathlib import Path

from .config import Config, MiB
from .punch import allocated_bytes
from .session import StreamSession

log = logging.getLogger("kino_stream")


def build_config(a) -> Config:
    cfg = Config(readahead_s=a.readahead_s, min_readahead_bytes=int(a.min_readahead_mib * MiB))
    cfg.encryption = a.encryption
    limit = int(a.cache_limit_gb * (1 << 30)) if a.cache_limit_gb else int((a.cache_limit_mb or 0) * MiB)
    if limit:
        cfg.cache_limit_bytes = limit
        if a.cache_back_mb:
            cfg.cache_back_bytes = int(a.cache_back_mb * MiB)
    if a.peer:
        cfg.peers = [(h, int(p)) for h, _, p in (x.partition(":") for x in a.peer)]
    if a.no_dht:
        cfg.dht = cfg.lsd = False
    if a.listen:
        cfg.listen = a.listen
    if a.state_dir:
        cfg.state_dir = Path(a.state_dir).expanduser()
    if a.verify_source:
        cfg.verify_source = Path(a.verify_source)
    if a.mpv_cache_mb:
        cfg.mpv_cache_bytes = int(a.mpv_cache_mb * MiB)
    cfg.upnp = False                         # never ask the router to open ports
    return cfg


async def amain(a) -> int:
    cfg = build_config(a)
    save = Path(a.save_path).expanduser()
    s = await StreamSession.open(cfg, a.source, save, a.file)
    f = s.store.piece_map.files[s.file_index]
    print(f"file [{s.file_index}] {f.path} ({f.size / MiB:.1f} MiB), URL: {s.url}", flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    t0 = time.monotonic()
    reason = "stopped"

    async def status():
        while True:
            await asyncio.sleep(a.status_interval)
            st = s.store.stats()
            log.info("peers=%s rate=%s pieces=%s/%s allocated=%.1f MiB%s evictions=%s head=%s %s",
                     st.get("peers"), "", st.get("pieces_have"), st.get("pieces_total"), allocated_bytes(save) / MiB,
                     f"/{cfg.cache_limit_bytes / MiB:.0f}" if cfg.cache_limit_bytes else "", st.get("evictions", "-"),
                     s.sched.head_byte(), "(waiting for peers: run `doctor --network`)" if not st.get("peers") else "")
    st_task = asyncio.create_task(status()) if a.status_interval > 0 else None
    mpv = None
    try:
        if not a.no_mpv:
            mpv = await s.play(headless=a.headless, extra_args=a.mpv_arg, use_user_config=not a.headless,
                               ipc_path=a.ipc_socket)
        waiters = [asyncio.create_task(stop.wait())]
        if mpv is not None:
            waiters.append(asyncio.create_task(mpv.proc.wait()))
        if a.quit_after:
            waiters.append(asyncio.create_task(asyncio.sleep(a.quit_after)))
        done, pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
        reason = "mpv exited" if mpv is not None and mpv.proc.returncode is not None else ("quit-after" if a.quit_after and not stop.is_set() else "signal")
    finally:
        if st_task:
            st_task.cancel()
        st = s.store.stats()
        summary = {"reason": reason, "seconds": round(time.monotonic() - t0, 1), "allocated_bytes": allocated_bytes(save),
                   "cache_limit": cfg.cache_limit_bytes, "pieces_have": st.get("pieces_have"), "pieces_total": st.get("pieces_total"),
                   "evictions": st.get("evictions"), "pieces_evicted": st.get("pieces_evicted"), "http_mismatches": s.server.stats["mismatches"],
                   "http_bytes": s.server.stats["bytes_sent"], "http_aborted": s.server.stats["aborted"], "hash_failed": st.get("hash_failed"),
                   "restarts": st.get("restarts"), "store_error": st.get("error"),
                   "mpv_rebuffers": None if mpv is None else mpv.rebuffers, "seeks": s.sched.counters["seeks"]}
        await s.close()
        print("SUMMARY " + json.dumps(summary), flush=True)
    return 1 if summary["store_error"] or summary["http_mismatches"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="kino-stream", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from . import __version__
    ap.add_argument("--version", action="version", version=f"kino-stream {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play", help="stream a torrent into mpv")
    p.add_argument("source", help=".torrent file (recommended) or magnet link")
    p.add_argument("--file", type=int, help="file index inside the torrent (default: largest video)")
    p.add_argument("--save-path", default="~/.cache/kino-stream", help="cache directory; with a cache limit it must be dedicated to this torrent")
    p.add_argument("--cache-limit-gb", type=float, default=0.0,
                   help="HARD limit for the on-disk cache (allocated blocks); 0 = unbounded. Needs a filesystem with hole punching")
    p.add_argument("--cache-limit-mb", type=float, default=0.0, help="same, in MiB (for tests)")
    p.add_argument("--cache-back-mb", type=float, default=0.0, help="keep this much behind the playback position for backward seeks (default 5%% of the limit)")
    p.add_argument("--peer", action="append", help="host:port peer hint (repeatable; useful when DHT/trackers are blocked)")
    p.add_argument("--encryption", choices=["default", "forced", "disabled"], default="default",
                   help="BitTorrent protocol encryption (some networks treat plain BitTorrent differently)")
    p.add_argument("--readahead-s", type=float, default=120.0)
    p.add_argument("--min-readahead-mib", type=float, default=32.0)
    p.add_argument("--mpv-cache-mb", type=float, default=0.0, help="mpv demuxer cache (default 16); the cache limit must leave room for it")
    p.add_argument("--no-mpv", action="store_true", help="only serve the HTTP URL")
    p.add_argument("--headless", action="store_true", help="mpv without video/audio output and without your mpv.conf (automation)")
    p.add_argument("--mpv-arg", action="append", default=[], help="extra argument for mpv (repeatable)")
    p.add_argument("--ipc-socket", help="path of mpv's JSON IPC socket (default: $XDG_RUNTIME_DIR/kino-stream-<pid>.sock)")
    p.add_argument("--quit-after", type=float, default=0.0, help="exit after N seconds (automation)")
    p.add_argument("--status-interval", type=float, default=10.0, help="log a status line every N seconds (0 = off)")
    p.add_argument("--no-dht", action="store_true", help="disable DHT and local peer discovery")
    p.add_argument("--listen", help="libtorrent listen interfaces, e.g. 127.0.0.1:6881")
    p.add_argument("--state-dir", help="where the cache index/journal live (default ~/.local/state/kino-stream)")
    p.add_argument("--verify-source", help="(tests) original file; every served chunk is compared with it")
    d = sub.add_parser("doctor", help="read-only environment and network diagnostics")
    d.add_argument("--save-path", default="~/.cache/kino-stream")
    d.add_argument("--network", action="store_true", help="also probe DHT / UDP trackers / DNS-over-UDP / exit IP (contacts public hosts)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if a.cmd == "doctor":
        from .doctor import run_doctor
        return run_doctor(Path(a.save_path), a.network)
    crash = Path.home() / ".local" / "state" / "kino-stream"
    crash.mkdir(parents=True, exist_ok=True)
    faulthandler.enable(open(crash / "crash.log", "a"), all_threads=True)   # a native crash leaves a Python stack here
    try:
        return asyncio.run(amain(a))
    except KeyboardInterrupt:
        return 130
    except Exception as e:                                                  # clear one-line errors for the expected failures
        from .store import StoreError
        if isinstance(e, (StoreError, ValueError)):
            print(f"error: {e}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
