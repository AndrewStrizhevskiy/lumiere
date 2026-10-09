"""Reduced-motion preference. Qt 6.4 has no API for it, so: KINO_REDUCE_MOTION=1/0 overrides; otherwise GNOME's
org.gnome.desktop.interface enable-animations is read (read-only, once). Anything unknown means animations stay on."""
from __future__ import annotations

import os
import shutil
import subprocess

_cache: bool | None = None


def reduced_motion(refresh: bool = False) -> bool:
    global _cache
    env = os.environ.get("KINO_REDUCE_MOTION")
    if env in ("0", "1"):
        return env == "1"
    if _cache is not None and not refresh:
        return _cache
    val = False
    if shutil.which("gsettings"):
        try:
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"], capture_output=True, text=True, timeout=2).stdout.strip()
            val = out == "false"
        except Exception:
            val = False
    _cache = val
    return val
