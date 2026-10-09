# Stage 2 design: bounded streaming cache ("Prizma")

Status: **implemented** (`bounded_store.py`, `cacheindex.py`, `punch.py`; tests in `tests/test_cache.py`, `tests/test_mpv.py::BoundedCacheWithMpv`). The notes at the end list where the implementation differs from or adds to this design. Evidence: `docs/STAGE2.md` (spikes S2/S3), `docs/STAGE1_VALIDATION.md`,
`docs/REAL_SWARM.md`. Product requirement: watch a 20-30 GB torrent with a 2-5 GB local cache; keep downloading what is
coming, evict what was watched, re-download evicted data on a backwards seek; never serve a wrong byte.

## 1. Acceptance criteria (each one gets an automated test)

| # | Criterion | Test |
|---|---|---|
| A1 | Hard, configurable cache limit (`cache_limit_bytes`) measured as **allocated** blocks (`st_blocks`, part-files and hidden files included) + a filesystem/safety reserve, never apparent size | 25 GB file, 3 GB limit, play 20+ min of wall clock and several seeks: peak `du` <= limit at every 0.5 s sample |
| A2 | Read-ahead window around the playback head, bounded by the budget; window shrinks (logged) if limit is too small | config validation test + 25 GB run |
| A3 | Pieces outside the retention window are evicted; evicted bytes are physically released | `st_blocks` drops after a cycle; `statvfs` free space rises |
| A4 | Seek into an evicted region re-downloads it correctly | hash-verified read after evict + seek back |
| A5 | **No corrupt byte to mpv or to peers**: libtorrent never advertises/serves an evicted piece | observer-peer test (as S3) incl. during a cycle; every HTTP byte compared with the source |
| A6 | Crash at any point of the eviction transaction (and during normal download) recovers to an exact state | fault injection at every step (section 4) |
| A7 | No second full copy of the video | only the one data file + at most 2 boundary-piece stubs |
| A8 | Stable playback when network >= bitrate | 25 GB scenario: rebuffers comparable to Stage 1 |
| A9 | Graceful buffering when network < bitrate | 0.5x scenario: no abort, no corruption, playback continues |
| A10 | Fail-safe: if a transaction cannot complete, stop serving and report; never expose a state where `have` != bytes | fault injection (disk full, EIO, libtorrent refusing) |

## 2. Components (the HTTP server and the scheduler do not change)

    mpv -> HTTP Range server -> Scheduler -> PieceStore (interface, unchanged) -> BoundedSparseStore -> libtorrent -> files
                                                                  |
                                              CacheIndex (journal + retained bitmap, our single source of truth)
                                              Evictor    (transaction state machine)
                                              Budget     (st_blocks accounting, watermarks, window clamp)

* `LibtorrentEngine` - extracted from `PersistentFileStore`: session, alert thread, add/remove/restart primitive
  (the restart code already exists and is tested), peer bookkeeping.
* `CacheIndex` - `index.json` (atomic write: temp + fsync + rename + dir fsync) with `retained` bitmap, `epoch`, and a
  `txn` record. **It, not libtorrent's resume data, decides `have`.** libtorrent is always started with
  `have_pieces = index.retained` and `no_verify_files` (S3-D). Resume data is advisory (peers, stats) only.
* `BoundedSparseStore(PieceStore)` - `have(p)` = `p in retained and p not in doomed`; `read()` takes a per-piece
  reader reference; implements the `lost` event for evicted pieces so the scheduler re-demands them.
* `Evictor` - the transaction below. `Budget` - admission control and victim choice.
* `Scheduler` gains one method, `retention_window() -> (lo_byte, hi_byte)` plus pinned ranges; everything else is as is.

## 3. Policy

* Retain `[head - back_window, head + window]` and the pinned head/tail (container index). Default back window 5% of
  the limit. Nothing else is wanted from the swarm (already true in Stage 1).
* Hysteresis: start evicting at 90% of the limit, evict down to 70%; victims = retained pieces farthest *behind* the
  head first, then farthest ahead of the window (after a seek). Never evict pinned or in-window pieces.
* Eviction is **batched** (>= 5% of the limit or >= 64 MiB) and rate-limited (default >= 30 s apart) because each
  transaction drops all peer connections (section 6). It is scheduled when the player has >= 20 s buffered.
* Only pieces **exclusive** to the streamed file (`PieceMap.exclusive_pieces`) may be evicted; shared boundary pieces
  stay (<= 2 pieces). Punching is block-aligned *inward*, so bytes of neighbouring retained pieces are never touched.
* Budget = allocated blocks (`st_blocks`) of every file under the save path + reserve (2% + 64 MiB for block rounding,
  extent overhead, partfile). Window is clamped so `pinned + back + window + one piece in flight` fits the limit.

## 4. The eviction transaction and every crash point

    P0 plan        choose set E (exclusive, not pinned, not in window); compute reader set
    P1 journal     index.txn = {id, E, state: "begin"}  ; fsync       <- point of no return, from here we ROLL FORWARD
    P2 doom        mark E unavailable: have(p)=False for p in E; new reads raise PieceUnavailable; HTTP waits/re-demands
    P3 drain       wait until no reader holds a piece of E (reads are <= 256 KiB; bounded by a timeout -> abort+fail-safe)
    P4 remove      save nothing; session.remove_torrent; wait torrent_removed_alert   (libtorrent no longer has the files)
                   -> nothing can be served or advertised from here until P8
    P5 punch       fdatasync data file; punch every p in E inward-aligned; fdatasync
    P6 index       index.retained -= E ; index.txn.state="punched" ; atomic write + fsync
    P7 settle      sleep 0.4 s (peers tear down the old connection; re-adding instantly stalled for 60+ s in Stage 1)
    P8 re-add      add_torrent(have_pieces = index.retained, no_verify_files)       (S3: exact, ~1 ms)
    P9 verify      for all p: handle.have_piece(p) == (p in retained); mismatch => FAIL-SAFE (remove, serve nothing)
    P10 commit     index.txn = None ; atomic write ; re-apply the scheduler's last demand ; undoom E

| crash after | state on disk | recovery on restart |
|---|---|---|
| before P1 | no txn | nothing happened |
| P1..P5 (any point, incl. mid-punch) | txn=begin, E listed, some of E punched | roll forward: finish punching E (idempotent), P6, then normal start |
| P6 | txn=punched | normal start with `retained` (E already excluded) |
| P8..P9 | torrent was added, nothing else changed | normal start |
| P10 | no txn | normal start |

Rule that makes all of them safe: **the index never lists a piece as retained unless its bytes are on disk and flushed**,
and a piece in E leaves `retained` *before* libtorrent is ever started again. libtorrent cannot learn of a piece the
index does not contain, so it can neither advertise nor serve it.

Normal downloads: a finished piece enters `retained` only after `fdatasync` of the data file (batched, every N pieces or
5 s via `handle.flush_cache()` + fdatasync, then an index write). A crash loses at most that interval of downloads (they
are simply re-downloaded; the stray bytes are reclaimed by punching every non-retained range at startup). Startup also
hashes a sample (default 16 random retained pieces + all pieces adjacent to the last txn) against the torrent's SHA-1
and drops mismatches from the index; any file-size or mtime surprise triggers a full verify of retained pieces.

## 5. Active HTTP readers, concurrent requests

* A reader of a doomed piece is not an error: `PieceUnavailable` -> the HTTP layer waits (`wait_have`), the scheduler
  re-demands the piece (the `lost` event already forces a re-assert); after P10 it downloads again. Worst case delay =
  transaction time + download time, bounded by `hard_timeout` (then the connection is aborted, never padded).
* New requests during a transaction are accepted and queued; `apply_demand` stores the demand and applies it at P10.
* A seek into E during P2-P9: same path; E is by construction behind/outside the window, so this is rare.
* Two transactions never overlap (single evictor lock); a transaction in progress delays, never races, a new one.

## 6. Peer reconnection delay (the main unknown)

Every transaction disconnects all peers. Measured locally: reconnect ~0.7 s (S3). In a real swarm it is unmeasured
(`docs/REAL_SWARM.md` has the cold-start numbers: first useful peers after 5-10 s; that is the worst case if
connections were lost entirely). Mitigations: large rare batches; run only with a healthy buffer; keep the peer list
(try `peers=` from `get_peer_info()` after the settle delay - to be validated, Stage 1 saw a stall when carrying a
stale list across a *magnet* conversion); `restart_after` already exists as the escalation. Spike R1 (below) decides
the batch size from real-swarm numbers before the evictor is tuned.

## 7. Failure handling (A10)

* Journal write fails -> abort before any change.
* Punch error on piece k -> continue with the rest; E is still removed from `retained` (roll forward); pieces not
  punched keep their disk space until retried at next startup/cycle (budget counts them).
* Re-add raises, or P9 mismatch, or the torrent reports errors -> remove the torrent, store state FAILED: HTTP aborts
  connections, nothing is advertised; a retry rebuilds from the index; two consecutive failures stop streaming with a
  clear error. Corrupt data is never an option.
* Disk full during download -> libtorrent `file_error_alert` -> same as FAILED, plus an eviction attempt first.

## 8. Implementation plan (each step lands with its tests; existing system untouched until A1-A10 pass)

1. Extract `LibtorrentEngine`; keep all 58+ tests green (small refactor).
2. `CacheIndex` + journal + atomic writes + startup recovery - pure Python, fault-injection tests for every crash row.
3. `Budget` (st_blocks accounting, window clamp) - unit tests with synthetic sparse files.
4. `BoundedSparseStore` + `Evictor` against the local swarm (S3 as the template), observer-peer test, crash tests that
   kill the process (`os._exit`) at each step and restart.
5. Scheduler `retention_window`, policy, hysteresis, batching; HTTP interplay tests (doomed-piece reads).
6. 25 GB acceptance with a 3 GB limit (A1-A9) and the real-swarm run with a small limit on Sintel/Tears of Steel.
7. Only then: integration into other media tools (not started, not part of this plan).

Spikes still open before step 4: R1 real-swarm reconnect cost after remove/re-add and whether carrying the peer list
helps; R2 flush/punch cost with dirty pages (S3 saw 0.4-2.6 s); R3 behaviour on XFS/btrfs (ext4 only so far).


## 9. Implementation notes (differences from the design above, found while testing)
* **Admission control makes the limit hard.** First version (eviction on a 0.5 s poll) overshot the limit by up to 28%. The store
  now admits requests only while `have + requested <= (limit - reserve) / piece_len`, ordered pinned -> urgent -> read-ahead
  (nearest to the head first), and kicks the eviction loop the moment something is held back. Playback may wait for room; the
  limit is not exceeded. Measured: 6 MiB limit, 13 evictions while streaming 10.5 MB: peak allocated 5.84 MB.
* **Pieces that finish between flush and removal** are made durable and kept after the torrent is removed (they were silently
  dropped before: fully allocated but unclaimed data, the cause of a 3.4 MB overshoot). Anything still unclaimed is released.
* The reserve includes 4 pieces for partly downloaded pieces whose priority dropped.
* `PieceStore.retain(RetentionHint)` is the only interface addition; stores that ignore it (Stage 1, FakeStore) are unchanged.
* The sampled startup verification re-hashes 16 random retained pieces plus the neighbours of an interrupted eviction.
* A directory that has data but no index is refused rather than adopted; an unreadable index retains nothing and releases the space.
* The design said "stop serving then remove": removal first is the stronger form - once the torrent is not in the session it
  cannot serve or advertise anything, so there is no window to get wrong.

Tests (see `tests/test_cache.py`): exact state after eviction (libtorrent == index == bytes on disk, every survivor re-hashed),
re-download of evicted pieces, reads of evicted pieces raise (never zeros), shared boundary pieces refused, adjacent pieces and
neighbouring files intact, observer peer sees no evicted piece and receives no corrupt piece across 4 eviction cycles, crash
injection at all 10 stages incl. stale resume data, filesystem without hole punching (clear error, data untouched), unmanaged
directory refused, corrupt index, damaged retained piece caught at startup, HTTP Range during and after an eviction, hard limit
while streaming a whole file with the backward-seek window preserved (in-window seek re-downloads nothing, out-of-window seek does),
limit too small rejected, and a real mpv playing/seeking inside a 6 MiB cache.
* **Index locking.** All index mutations and saves share one lock, and a flush is skipped while a transaction is open: found by
  the test run - two concurrent saves shared one temp file (ENOENT on rename), and a save running in a worker thread could have
  persisted "txn punched" together with a `retained` bitmap that still claimed the punched pieces.
* **Reserve.** `reserve = max(2% of limit, 8 blocks) + max(24 pieces, 2 MiB)`. On a real swarm many pieces are in flight at once; a
  48 MiB cache with a 4-piece reserve peaked 1.2% over the limit (50.9 MB vs 50.3 MB), which is why the reserve grew.
