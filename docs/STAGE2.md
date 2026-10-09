# Stage 2 (bounded cache): spike findings (the implementation is described in STAGE2_DESIGN.md, section 9)

Hard rule: **hole punching alone is unsafe** (`spikes/s2_forget_piece.py`): libtorrent keeps `have_piece()==True`, serves
zeros, and resume data still claims the piece. `torrent_handle.clear_piece()` does not exist in the Python binding and
Python cannot select/replace libtorrent's disk I/O. `force_recheck()` is exact but re-reads everything.

## Candidate that passed S3 (`spikes/s3_evict_cycle.py`, libtorrent 2.0.10, ext4, 4 KiB blocks)

    save resume -> REMOVE torrent (wait torrent_removed_alert) -> punch holes -> RE-ADD with exact have_pieces
    + no_verify_files -> reconnect

The order *remove first, punch second* removes the "stop serving" window altogether: libtorrent no longer has the
files open while they change, so there is nothing to disable and nothing half-evicted to serve.

Measured:
* 8 consecutive cycles (231 pieces, 12% evicted each): `have_piece` == retained set and every retained piece
  re-hashed against the torrent's SHA-1 -> exact every time. Re-add takes ~1 ms, remove ~20 ms.
* Observer peer that can only download from the evicting node, 8 cycles, 77 pieces transferred: **0 hash failures,
  0 bans, 0 corrupt pieces held**; after every re-add the bitfield L1 advertises (`peer_info.pieces`) equals the
  retained set, **no evicted piece advertised** (checked in cycles 3-7).
* Crash between punch and re-add: stale resume data claiming everything + a journal of intended evictions ->
  `have_pieces = resume & ~journal`, `no_verify_files` -> exact state without a recheck.
* Multi-file, unaligned file starts: evicting only pieces exclusive to one file (`PieceMap.exclusive_pieces`), punching
  *inward* to 4 KiB block boundaries: neighbouring retained bytes untouched, state exact.
* Evicted piece re-downloads on demand in ~1 s (local seeder) after a cycle.
* Cost: `punch` spiked to 0.4-2.6 s when the file still had dirty pages (flush before punching).
* Reconnect after quick remove/re-add of the same torrent: ~0.7 s locally. BUT re-adding in the same instant as the
  removal raced the peers' teardown (stalls of 60+ s): wait ~0.4 s, and do not carry the old peer list over.

Findings from Stage 1 that matter here:
* Files with *file* priority 0 are written to a hidden `.<hash>.parts` part-file. Calling `prioritize_files` on a
  running torrent has lasting side effects on piece priorities (measured 79% instead of 44% downloaded).
* libtorrent can keep a disconnected peer as a non-candidate forever (`connect_candidates` 0): connect_peer, pause/
  resume, force_reannounce all failed. Remove + re-add recovers. `PersistentFileStore` already uses this as an
  escalation (`restart_after`, 4 s without peers while data is wanted).
* Alert objects (and members like `save_resume_data_alert.params`) are only valid until the next `pop_alerts`.

## Still to test before implementing

* Real-world peer reconnection cost with many peers, trackers and DHT (everything above is a loopback swarm).
* Batching policy: how often can we remove/re-add without hurting playback (cycle cost ~1 s + reconnect ~0.7 s locally).
* What an active HTTP reader sees during a cycle (`PieceUnavailable` + "lost" events are the hooks; not exercised yet).
* mmap vs posix disk I/O under PUNCH_HOLE (not selectable from Python; remove-first avoids concurrent mmap).
* Other filesystems (ext4 only so far), flush/fsync policy before punching, SSD vs HDD.
* Budget accounting by allocated blocks (`st_blocks`), not apparent size.

Invariant for any implementation: libtorrent's `have` state must never disagree with the bytes on disk.
