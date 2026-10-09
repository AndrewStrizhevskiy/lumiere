# Known issues and open risks (read this before relying on kino-stream)

## 1. libtorrent crashes (SIGSEGV / SIGABRT): root cause found, fixed, verified by a controlled experiment
**Root cause.** `session.wait_for_alert()` in the Python binding returns a raw pointer to an alert inside the *live* alert
queue. libtorrent's other threads keep posting alerts (and the queue reallocates / is swapped) while Python converts and
uses that pointer: a use-after-free (`pure virtual method called`, `free(): invalid pointer`, SIGSEGV in `__dynamic_cast`).
It is rare with a few alerts per second and frequent with the thousands per second of a real swarm - which is why the
loopback tests never saw it and real swarms crashed ~2 runs in 5.

**Proof** (`diag/alert_stress.py`, identical workload: 3 loopback seeders, all alert categories, about 35 000 alerts/s), 40 s each:

| how alerts are read | result |
|---|---|
| second thread: `wait_for_alert(20)` + `pop_alerts()` | **crashed 3 of 3** (SIGABRT, SIGABRT, SIGSEGV) |
| second thread: `pop_alerts()` only | survived 3 of 3 (1.5-1.7 M alerts each) |
| main thread: `pop_alerts()` only | survived 3 of 3 (1.3-2.0 M alerts each) |

**Fix.** kino-stream never calls `wait_for_alert()`: alerts are polled with `pop_alerts()` from the event-loop thread every
50 ms and converted into plain tuples immediately (objects are only valid until the next `pop_alerts()`). Regression tests:
`tests/test_alert_safety.py` (a source guard that forbids `wait_for_alert` in the package and the test fixtures, plus the
alert storm in a subprocess for both safe reader styles). The earlier mitigations (narrow alert mask) stay but are no longer
what protects us. No automatic restart was added to hide crashes. `python -m kino_stream` still writes native crash stacks to
`~/.local/state/kino-stream/crash.log`.

**Residual risk.** The controlled experiment and the regression tests prove the mechanism, not that no other defect exists.
Confirmation on real swarms is recorded in `docs/real_swarm_report.json` (runs after the fix); any crash still leaves a
stack in `crash.log`.

## 2. Bounded cache (Stage 2) limitations
* Only the streamed file is evictable, and only pieces that lie entirely inside it. Boundary pieces shared with another file
  (at most 2 per file) are never evicted.
* Every eviction removes the torrent from the session and re-adds it, so **all peer connections drop**. Measured on loopback:
  0.45 s per transaction and ~0.7 s to reconnect. On a real swarm this is unmeasured; evictions are batched (>= 4 pieces, at most
  every `evict_min_interval` = 20 s unless the cache is full).
* Under pressure (cache full of data that must stay) playback can pause while the store makes room: the limit is hard,
  read-ahead is not. A limit too small for `pins + back window + read-ahead` is rejected at start with a clear message.
* The limit counts allocated blocks of the whole cache directory with a reserve (2% or 8 blocks, plus 4 pieces for partially
  downloaded pieces). The index and journal live in the state directory (`~/.local/state/kino-stream`), not in the limit.
* Needs a filesystem that really releases blocks on `fallocate(PUNCH_HOLE)`: probed at start with a scratch file; otherwise
  startup fails and the directory is left untouched. Tested: ext4 only. Other filesystems (btrfs/xfs/zfs/NFS) are untested.
* A cache directory is bound to its index. A directory with data but no index is refused (never adopted silently).
* Startup re-hashes a random sample of retained pieces (16) plus the neighbours of an interrupted eviction; damage elsewhere
  is only detected when a peer or the player is affected.
* Power loss: pieces become "retained" only after `fdatasync`; the journal is fsync'ed. Tested with simulated process
  crashes (`SimulatedCrash` at every stage), not with real power cuts.
* One torrent per process; not integrated into media servers or libraries (by design for now).

## 3. Earlier, still valid
* Real-swarm cold start is 2-22 s to the first frame (DHT/tracker/peer ramp), seeks into un-downloaded regions 2-12 s.
* `pause`/`connect_peer` cannot revive a peer that libtorrent stopped considering; the store re-adds the torrent after 4 s
  without peers (or 15 s without payload). This is a workaround for libtorrent behaviour, not a crash workaround.

## 4. Found and fixed during integration (kept here as lessons)
* A manual peer hint added while the torrent had nothing to download ("finished") became a permanent non-candidate when pieces
  were already on disk: a second launch with a populated cache had **0 peers for 25+ s**. Hints are now connected when data is
  first wanted (`wake()`), and a stuck torrent is re-added (`restart_after`).
* Pieces that finish between the pre-eviction flush and the torrent removal used to be dropped from the bookkeeping while
  staying allocated on disk (cache exceeded its limit). They are now kept (made durable) and strays are reclaimed.
* Network findings (what is confirmed vs hypothesis) live in `docs/NETWORK_FINDINGS.md`; `kino-stream doctor --network` repeats the probes.

## 5. Real-swarm behaviour of the bounded cache (3 runs, Sintel 129 MB / limit 48 MiB twice, Tears of Steel 571 MB / limit 160 MiB)
* No crash, no served mismatch, no corrupt piece, nothing downloaded outside the demanded windows; peak disk 46.0, 50.9 (limit 50.3: 1.2% over,
  before the reserve was enlarged), 153.2 MB (limit 168 MB).
* Seeks into un-downloaded regions took 1.5-11 s on Sintel and 11-64 s on Tears of Steel (a slow swarm: the unbounded run also needed 7-12 s);
  restarts of the torrent after "no payload" were frequent there (10 in 5 min), so `stuck_after` was raised to 30 s.
  These numbers depend on the swarm and on the VPN path (`docs/NETWORK_FINDINGS.md`) and are not a property of the cache.
