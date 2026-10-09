"""Managed cache directories: one per torrent under a cache root, each marked so that only directories this program
created can ever be removed. Nothing is deleted unless the user's settings or an explicit action ask for it."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .punch import allocated_bytes
from .store import CacheDirNotManagedError

MARKER = ".kino-stream-managed"


class NotManaged(Exception):
    pass


def cache_dir_for(root: Path, infohash: str, temporary: bool = False) -> Path:
    return Path(root) / (f"tmp-{infohash}" if temporary else infohash)


def prepare_cache_dir(root: Path, infohash: str, temporary: bool = False) -> Path:
    """Create (or reuse) the managed directory of a torrent. A pre-existing non-empty directory without our marker is foreign:
    it is refused, never adopted."""
    d = cache_dir_for(root, infohash, temporary)
    marker = d / MARKER
    if d.exists() and not marker.exists() and any(d.iterdir()):
        raise CacheDirNotManagedError(f"{d} already exists and was not created by Kino Stream: refusing to use or touch it.")
    d.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps({"infohash": infohash, "temporary": temporary, "created": time.time()}))
    return d


def read_marker(d: Path) -> dict | None:
    try:
        return json.loads((Path(d) / MARKER).read_text())
    except Exception:
        return None


def delete_managed_cache(root: Path, d: Path, state_dir: Path | None = None) -> int:
    """Remove a managed cache directory (and its index/resume files). Refuses anything that is not a direct child of `root`
    carrying our marker. Returns the bytes released."""
    root_r, d_r = Path(root).resolve(), Path(d).resolve()
    m = read_marker(d_r)
    if d_r.parent != root_r or m is None or not str(m.get("infohash", "")):
        raise NotManaged(f"{d} is not a Kino Stream cache directory: not touching it")
    freed = allocated_bytes(d_r)
    shutil.rmtree(d_r)
    if state_dir:
        for suffix in (".cache.json", ".cache.json.tmp", ".resume"):
            try:
                (Path(state_dir) / f"{m['infohash']}{suffix}").unlink()
            except FileNotFoundError:
                pass
    return freed


def list_caches(root: Path) -> list[dict]:
    out = []
    root = Path(root)
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        m = read_marker(d) if d.is_dir() else None
        if m:
            out.append({"path": str(d), "infohash": m.get("infohash"), "temporary": bool(m.get("temporary")), "bytes": allocated_bytes(d)})
    return out
