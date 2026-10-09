# SPDX-License-Identifier: GPL-3.0-or-later
"""All tunables in one place. Sizes are bytes, times are seconds unless the name says otherwise."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

KiB, MiB, GiB = 1 << 10, 1 << 20, 1 << 30


@dataclass
class Config:
    # --- libtorrent session ---------------------------------------------------------------
    listen: str = "0.0.0.0:6881,[::]:6881"
    dht: bool = True
    lsd: bool = True
    upnp: bool = True
    encryption: str = "default"                      # default | forced | disabled (BitTorrent protocol encryption, MSE/PE)
    web_seeds: bool = True                            # use HTTP web seeds listed in the .torrent (not BitTorrent peers!)
    peers: list = field(default_factory=list)         # [(host, port)] used by wake(); needed when no tracker/DHT
    state_dir: Path = Path.home() / ".local" / "state" / "kino-stream"
    download_limit: int = 0                           # bytes/s, 0 = unlimited
    upload_limit: int = 0
    limits_on_lan: bool = False                       # tests: apply rate limits to 127.0.0.1 peers too
    alert_queue_size: int = 50000
    min_reconnect_time: int = 0                       # 0: reconnect at once (default 60 broke idle->deadline wake-up)
    metadata_timeout: float = 120.0
    keep_data: bool = True                            # Stage 1: data stays on disk after close
    resume_interval: float = 60.0
    restart_after: float = 4.0                        # no peer for this long while data is wanted -> remove + re-add torrent
    stuck_after: float = 30.0                         # peers connected but < 1 kB/s for this long while data is wanted -> re-add torrent
    restart_after_cold: float = 25.0                  # same, but before any peer was ever connected (DHT/tracker bootstrap takes seconds)
    wake_interval: float = 2.0                        # re-wake the torrent if demanded pieces make no progress

    # --- bounded cache (Stage 2); cache_limit_bytes = 0 keeps Stage 1 behaviour (nothing is ever evicted) ---------
    cache_limit_bytes: int = 0                        # HARD limit on allocated disk blocks (st_blocks) of the cache directory
    cache_back_bytes: int = 0                         # retained behind the playback head for backward seeks (0 = 5% of limit)
    cache_back_seconds: float = 0.0                   # same, in seconds of video (converted with the measured bitrate; wins over 5%)
    cache_high: float = 0.90                          # start evicting above this fraction of the limit
    cache_low: float = 0.70                           # ... down to this fraction
    cache_emergency: float = 0.97                     # above this: no new read-ahead is requested, eviction ignores the interval
    evict_min_interval: float = 20.0                  # every eviction drops all peer connections: keep them rare
    evict_min_batch_pieces: int = 4
    flush_interval: float = 3.0                       # fdatasync + index write for newly finished pieces
    cache_verify_sample: int = 16                     # retained pieces re-hashed at startup
    drain_timeout: float = 5.0                        # readers of doomed pieces get this long to finish

    # --- scheduling -----------------------------------------------------------------------
    readahead_s: float = 120.0                        # download this many seconds ahead of the playback head
    min_readahead_bytes: int = 32 * MiB
    urgent_s: float = 4.0                            # pieces in this part of the window get deadlines
    urgent_min_bytes: int = 8 * MiB
    mpv_cache_bytes: int = 16 * MiB                   # must match --demuxer-max-bytes handed to mpv
    window_margin_bytes: int = 2 * MiB
    assumed_bytes_per_s: int = 2_000_000              # bitrate guess until the player reports duration
    pin_head_bytes: int = 1 * MiB                     # container header guess (container probing)
    pin_tail_bytes: int = 512 * KiB                   # moov/Cues guess; real probes extend the pinned set
    probe_max_bytes: int = 32 * MiB                    # a Range reaching to EOF with <= this left is a probe
    pin_cap_bytes: int = 32 * MiB                     # never pin more than this
    seek_back_slack: int = 1 * MiB                    # request starting this far behind the head is a seek
    seek_fwd_slack: int = 1 * MiB
    player_fresh_s: float = 1.5                       # an IPC sample older than this is not trusted
    recompute_interval: float = 0.25

    # --- HTTP -----------------------------------------------------------------------------
    chunk_bytes: int = 256 * KiB
    sndbuf: int = 64 * KiB                            # small send buffer => bytes sent ~= bytes consumed
    piece_timeout: float = 20.0                       # wait this long for a piece, then re-assert + wake and keep waiting
    hard_timeout: float = 90.0                        # then abort the connection (never send partial data as complete)
    verify_source: Path | None = None                 # tests: compare every served chunk with the original file

    # --- mpv ------------------------------------------------------------------------------
    mpv_back_bytes: int = 8 * MiB
    mpv_network_timeout: int = 150                    # must exceed hard_timeout, else mpv gives up while we wait
    poll_interval: float = 0.25

    def back_bytes(self, bytes_per_s: float = 0.0) -> int:
        if self.cache_back_bytes:
            return self.cache_back_bytes
        if self.cache_back_seconds and bytes_per_s:
            return int(min(self.cache_back_seconds * bytes_per_s, self.cache_limit_bytes * 0.40))   # never more than 40% of the cache
        return int(self.cache_limit_bytes * 0.05)

    def cache_reserve(self, block: int = 4096, piece_len: int = 0) -> int:
        """Slack for block rounding, extents, part-files and pieces that are partly downloaded when their priority drops
        (libtorrent finishes some of them; on a real swarm dozens of pieces are in flight at once - a 48 MiB cache overshot by 1.2%
        with a 4-piece reserve): requests are limited so that limit - reserve is never exceeded."""
        return max(8 * block, int(self.cache_limit_bytes * 0.02)) + max(24 * piece_len, 2 << 20)

    def window_bytes(self, bytes_per_s: float) -> int:
        """Effective download/serve window ahead of the head. Never smaller than what mpv itself will buffer."""
        ra = max(self.min_readahead_bytes, int(self.readahead_s * bytes_per_s))
        return max(ra, self.mpv_cache_bytes + self.window_margin_bytes)

    def urgent_bytes(self, bytes_per_s: float) -> int:
        return max(self.urgent_min_bytes, int(self.urgent_s * bytes_per_s))
