# SPDX-License-Identifier: GPL-3.0-or-later
"""User settings (toolkit-agnostic): plain words in the file, validated on load, mapped to the engine's Config.

Stored in $XDG_CONFIG_HOME/lumiere/settings.json (default ~/.config/lumiere). A damaged file is moved aside
(`settings.json.bad`) and defaults are used: settings can never prevent the application from starting."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import Config, MiB
from .migrate import LEGACY, base_dirs, migrate_user_dirs

GiB = 1 << 30
NETWORK_PRESETS = {                      # how long to wait for a missing part before retrying / giving up (seconds)
    "patient":  {"piece_timeout": 20.0, "hard_timeout": 90.0, "mpv_network_timeout": 150},
    "balanced": {"piece_timeout": 12.0, "hard_timeout": 45.0, "mpv_network_timeout": 75},
    "quick":    {"piece_timeout": 6.0,  "hard_timeout": 20.0, "mpv_network_timeout": 40},
}
ENCRYPTION_MAP = {"auto": "default", "always": "forced", "off": "disabled"}


def config_dir() -> Path:
    migrate_user_dirs()                  # once per process: moves ~/.config/kino-stream (the former name) to ~/.config/lumiere, recoverably (see migrate.py)
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "lumiere"


def state_dir() -> Path:
    migrate_user_dirs()
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "lumiere"


def default_cache_root() -> Path:
    migrate_user_dirs()
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "lumiere"


def legacy_cache_root() -> Path:
    """The former default cache folder (`~/.cache/kino-stream`). A settings.json written by an older version may name it explicitly."""
    return base_dirs()["cache"] / LEGACY


@dataclass
class Settings:
    cache_gb: float = 4.0                # hard limit for streaming data on disk
    keep_minutes: float = 10.0           # how much already-watched video stays on disk for jumping back
    network: str = "patient"             # patient | balanced | quick
    encryption: str = "auto"             # auto | always | off
    on_close: str = "keep"               # keep | delete   (streaming data of the video that was closed)
    cache_root: str = ""                 # "" = ~/.cache/lumiere
    tour_done: bool = False
    language: str = "en"
    version: int = 1

    # ---------------------------------------------------------------------------------------------- validation
    def normalized(self) -> "Settings":
        d = Settings()
        s = Settings(**{f.name: getattr(self, f.name) for f in fields(self)})
        try:
            s.cache_gb = min(max(float(s.cache_gb), 0.5), 4096.0)
        except (TypeError, ValueError):
            s.cache_gb = d.cache_gb
        try:
            s.keep_minutes = min(max(float(s.keep_minutes), 0.0), 240.0)
        except (TypeError, ValueError):
            s.keep_minutes = d.keep_minutes
        if s.network not in NETWORK_PRESETS:
            s.network = d.network
        if s.encryption not in ENCRYPTION_MAP:
            s.encryption = d.encryption
        if s.on_close not in ("keep", "delete"):
            s.on_close = d.on_close
        s.tour_done = bool(s.tour_done)
        s.cache_root = str(s.cache_root or "")
        if s.cache_root and Path(s.cache_root).expanduser() == legacy_cache_root():
            s.cache_root = ""            # the former default folder was migrated to the current default (migrate.py); an older file may still name it
        s.language = str(s.language or "en")
        return s

    @property
    def cache_root_path(self) -> Path:
        return Path(self.cache_root).expanduser() if self.cache_root else default_cache_root()

    # ------------------------------------------------------------------------------------------------ mapping
    def to_config(self, temporary: bool = False) -> Config:
        """Engine configuration for this user's settings. `temporary` = explicit opt-in mode without a cache limit."""
        s = self.normalized()
        cfg = Config()
        cfg.upnp = False                                               # never touches the router
        cfg.encryption = ENCRYPTION_MAP[s.encryption]
        for k, v in NETWORK_PRESETS[s.network].items():
            setattr(cfg, k, v)
        if not temporary:
            cfg.cache_limit_bytes = int(s.cache_gb * GiB)
            cfg.cache_back_seconds = s.keep_minutes * 60.0
        cfg.cache_back_bytes = 0
        return cfg

    # ------------------------------------------------------------------------------------------- persistence
    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_dir() / "settings.json"
        try:
            raw = json.loads(Path(path).read_text())
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in raw.items() if k in known}).normalized()
        except FileNotFoundError:
            return cls()
        except Exception:
            try:
                os.replace(path, str(path) + ".bad")                  # keep the damaged file for inspection
            except OSError:
                pass
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = Path(path or config_dir() / "settings.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self.normalized()), indent=2))
        os.replace(tmp, path)
