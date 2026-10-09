# SPDX-License-Identifier: GPL-3.0-or-later
"""Managed cache directories: one per torrent under a cache root, each marked so that only directories this program
created can ever be removed. Nothing is deleted unless the user's settings or an explicit action ask for it."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from .punch import allocated_bytes
from .store import CacheDirNotManagedError

MARKER = ".kino-stream-managed"


class NotManaged(Exception):
    pass


_HASH = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def valid_infohash(h: object) -> bool:
    """Only plain lowercase hex (v1: 40, v2: 64 chars). Anything else - separators, dots, spaces - can never reach a path."""
    return isinstance(h, str) and bool(_HASH.match(h))


def cache_dir_for(root: Path, infohash: str, temporary: bool = False) -> Path:
    return Path(root) / (f"tmp-{infohash}" if temporary else infohash)


def prepare_cache_dir(root: Path, infohash: str, temporary: bool = False) -> Path:
    """Create (or reuse) the managed directory of a torrent. A pre-existing non-empty directory without our marker is foreign:
    it is refused, never adopted."""
    if not valid_infohash(infohash):
        raise CacheDirNotManagedError(f"refusing to create a cache directory for the invalid info-hash {infohash!r}")
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
    that carries our marker AND is named after the info-hash recorded in that marker (a marker is just a file: its content is
    treated as untrusted, validated as plain hex, and never used to build a path unless it matches the directory name).
    Returns the bytes released."""
    root_r, d_r = Path(root).resolve(), Path(d).resolve()
    m = read_marker(d_r)
    ih = None if m is None else m.get("infohash")
    if d_r.parent != root_r or not valid_infohash(ih) or d_r.name not in (ih, f"tmp-{ih}") or d_r.is_symlink():
        raise NotManaged(f"{d} is not a Kino Stream cache directory: not touching it")
    freed = allocated_bytes(d_r)
    shutil.rmtree(d_r)
    if state_dir:
        sd = Path(state_dir).resolve()
        for suffix in (".cache.json", ".cache.json.tmp", ".resume"):
            f = (sd / f"{ih}{suffix}")
            if f.resolve().parent == sd:                    # belt and braces: the file must be directly inside the state directory
                try:
                    f.unlink()
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
        if m and valid_infohash(m.get("infohash")):
            out.append({"path": str(d), "infohash": m.get("infohash"), "temporary": bool(m.get("temporary")), "bytes": allocated_bytes(d)})
    return out
