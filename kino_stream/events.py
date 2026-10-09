"""Structured engine events: codes + details, no user-facing text (the UI owns wording and translation)."""
from __future__ import annotations

from dataclasses import dataclass, field

READY = "READY"                              # media opened, URL available
NO_PEERS = "NO_PEERS"                        # no source connected for a while since the start
NETWORK_LOST = "NETWORK_LOST"                # sources were connected and are all gone
NETWORK_RESTORED = "NETWORK_RESTORED"
SLOW_CONNECTION = "SLOW_CONNECTION"          # playback keeps waiting for data and the rate is below the bitrate
CACHE_FULL = "CACHE_FULL"                    # older data is being freed to make room (playback may pause briefly)
UNSUPPORTED_FILE = "UNSUPPORTED_FILE"        # the player could not open the file
PLAYER_ERROR = "PLAYER_ERROR"
CACHE_UNSUPPORTED_FS = "CACHE_UNSUPPORTED_FS"
CACHE_TOO_SMALL = "CACHE_TOO_SMALL"
CACHE_DIR_NOT_MANAGED = "CACHE_DIR_NOT_MANAGED"
STORE_FAILED = "STORE_FAILED"                # the storage layer stopped to protect data integrity
OPEN_FAILED = "OPEN_FAILED"                  # metadata never arrived / unreadable torrent
INFO, WARNING, ERROR = "info", "warning", "error"


@dataclass(frozen=True)
class EngineEvent:
    code: str
    level: str = INFO
    detail: dict = field(default_factory=dict)
