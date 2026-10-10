# Known issues and open risks (read this before relying on kino-stream)

## 0a. Interface refinements (design direction "Lumière") — what was verified, and what was not
* Verified by automated tests on one machine (Ubuntu 24.04, GNOME/Wayland, PyQt6 6.6.1 on Qt 6.4.2): themes and contrast tokens, focus visibility and Tab order, interruptible fades and banner, reduced motion, Home composition at 720/1040/1440 px, long and CJK titles in cards, the offline title cleaner, positions and history preserved. Most of these tests run offscreen; the real-display run covers the player (`tests/test_ui_player.py`).
* **Not tested:** screen readers, X11, fractional/HiDPI scaling beyond the development display, high-contrast desktop themes, right-to-left languages, other Qt versions. Screenshots in `docs/design/screens/` are offscreen renders with made-up titles.
* Fonts are not bundled; on a machine without the named serif or sans families the interface uses generic ones and looks different (and may wrap differently).
* The title cleaner is deliberately conservative and local: it cannot identify a film, does not fix wrong file names, leaves unknown tags (for example `VOSTFR`) in the title, and declines TV episodes, season packs and collections (the readable file name is shown). Rules and limits: `docs/design/TITLE_CLEANER.md`.
* "Continue watching" keeps **one entry per torrent** (keyed by infohash) and the app always opens the largest video of a torrent; multi-file torrents (season packs) are therefore represented by one file. A proposal for changing this is in `docs/design/HISTORY_MODEL_PROPOSAL.md`; nothing was changed.
* The theme is chosen with `KINO_STREAM_THEME=dark|light` (dark by default); there is no Settings toggle. GNOME's reduce-animations setting is read once at start (`KINO_REDUCE_MOTION` overrides it).
* The product is named **Lumière** (display name only, owner decision 2026-10-10). The commands, packages, desktop-entry/icon file names and the settings/state/cache folders still say `kino-stream`; engine and command-line error strings may still say "Kino Stream". **No trademark or domain check has been done.** `KINO_STREAM_BRAND=kino` shows the previous name.

## 0b. One unexplained native crash in the automated tests — UNRESOLVED
**What happened.** During development, one run of the complete automated test suite (1 of 18 full runs of the interface work) was killed by the operating system with a segmentation fault (exit code 139) while a GUI test (`tests.test_ui.Window.test_open_failure_maps_to_dialog_and_hides_overlay`) was running. No stack trace was captured, because crash reporting and core dumps were not enabled for that run. That run used an earlier development state of the interface code.

**What we know.** It has never happened again: not in the later full runs (including runs with crash reporting and core dumps on, and two under glibc heap checking), nor in about 165 repeated runs of the GUI tests (60 with an aggressive garbage collector, 11 under a debugger), nor in about 440 loaded runs of the command-line/mpv test. It has only ever been seen inside the test run, never while using the application.

**What we do not know.** The cause. It could be a defect in this project's code, in PyQt6/Qt, or a rare interaction in the test setup. A connection with the interface changes is neither shown nor excluded. That later runs passed does **not** show that the application is crash-free; it only shows that the crash is rare.

**What it could mean for you.** The worst plausible outcome is the application closing. The disk cache and its journal are designed to survive a crash and are tested with real `SIGKILL`, so a crash should not corrupt your downloaded data (this is tested, not guaranteed).

**If it happens to you.** Please open an issue and attach `~/.local/state/kino-stream/crash.log` (the application writes native stack traces there; it was empty in all our application runs). A readable stack would need Qt/Python debug symbols, which were deliberately not installed during development. The engine's separate, fixed `wait_for_alert` crash (section 1) is a different problem.

## 0c. Found and fixed during release preparation: eviction journal left open by a clean shutdown
* In a full run under load, `tests.test_cli.CliBounded.test_play_seek_both_ways_inside_a_hard_cache_limit` failed once with "an eviction journal entry was left open" (txn state `punched`) after a *clean* exit. Cause (established by code reading and a deterministic reproduction): `BoundedSparseStore.close()` cancelled the cache loop while it was between `mark_punched()` and `commit()` of an eviction. This never exceeded the cache limit and never served wrong data (the next start rolls the journal forward; see the crash-point tests), but a clean exit should leave a clean journal. Fixed in `kino_stream/bounded_store.py` (`close()` waits up to 20 s for an in-flight eviction; no new eviction starts while closing); regression test `tests/test_cache.py::CrashRecovery::test_closing_while_the_cache_loop_is_evicting_lets_the_eviction_finish_and_leaves_a_closed_journal` (red before, green after). Reproduction rate before the fix: 0 of 8 runs alone, 2 of 18 with three runs in parallel.

## 0d. Found and fixed during release preparation: zeros served for a completed piece under heavy CPU load
* Under 6- to 10-way parallel load (several full CLI/mpv runs at once on 8 cores) `tests.test_cli.CliBounded.test_play_seek_both_ways_inside_a_hard_cache_limit` reported `http_mismatches: 1` (the server sent a piece as zeros that the store already counted as downloaded). Rate before the fix: 4 of 100 runs at 10-way load (0 of 8 runs alone). Evidence: the diagnostic copy logged `all_zero_in_served: True` for exactly one piece with `have=1`, no eviction, no restart, and a re-read 0.3 s later equalled the original. Cause: libtorrent's `piece_finished` alert can precede the visibility of the piece's blocks in the file; the store read the file immediately. It is a contract violation of the store (`kino_stream/store.py`: never return zero/missing data) that existed in the engine before the interface work.
* Fix (`kino_stream/lt_store.py`, `bounded_store.py`, `httpd.py`): the first time a piece is served it is verified against the torrent's SHA-1 piece hash; if it does not match yet the read raises `PieceUnavailable` and the HTTP server waits (20 ms steps, aborting with an explanation after `hard_timeout`). Same load after the fix: 0 mismatches in 100 runs. Limits: only pieces lying entirely inside the streamed file are verifiable (up to 2 boundary pieces per file are not); pure BitTorrent-v2 torrents have no v1 piece hashes and are not checked; a piece that stays wrong on disk for `hard_timeout` now aborts the connection (previously it would have been served corrupt). Before this fix, damaged retained data was only detected by the startup sample or the player; it is now also detected when served.
* The real-swarm behaviour of this check is **not measured** (all measurements are loopback swarms).

## 0. Desktop app (0.3.0) — scope of what was verified
* **Two of three first real-internet torrents did not start streaming in the GUI (cause not established).** In the developer's first real use, three public single-/multi-file `.torrent` files
  (≈4.3 GB, ≈7.0 GB and ≈22.8 GB; all with 15 http/https/udp trackers and 4 MiB pieces) were opened in one app session. The 7 GB torrent played (the history records a known duration and a saved position of 84 s)
  and logged no stuck warnings. The other two were opened afterwards: one was abandoned after ≈65 s (two restarts, 22–27 peers connected), the other after ≈2 minutes (five restarts, 3–5 peers),
  with the log line "connected to N peers but no payload for 30s" at ≈25 s intervals and no data ever written to either cache. Investigation so far (details in `docs/RELEASE_READINESS.md` §7a):
  * *Verified:* the restart triggers are exactly as in the code (peers connected, data wanted, <1 kB/s for 25 s before anything was ever downloaded, 30 s afterwards, at least 15 s between restarts); the logged "30s" was
    wrong for the 25 s cold limit (fixed, see below); opening several different torrents one after another in one session works on a local swarm; a seeder that keeps us choked for 40 s or 70 s serves us within
    0.4 s of unchoking despite the intervening restarts.
  * *Not established:* why those peers sent nothing. The engine does not log whether peers choke us or lack the wanted pieces, so the existing logs cannot tell a swarm-side cause (peers that never unchoke us, or that
    do not have the requested pieces) from a network-side cause. Not tested: any external network behaviour (no external test has been run).
  * A proposed diagnostic (peer choke/interest summary in the restart message) is **not implemented** pending approval.
* **Fixed after the first real use (found by code review, reproduced locally): false "no payload" restarts after any re-add.** After a restart or a bounded-cache eviction the new libtorrent handle counts downloaded
  payload from zero, but the stall detector kept the old high-water mark, so healthy downloading was declared stuck and the torrent restarted every 30 s (dropping all connections) until the new handle had
  downloaded as much as the old one. Reproduced on a local swarm (20 kB/s flowing, restarted at +30 s and +60 s) and fixed by rebasing the mark; thresholds are unchanged. Regression tests: `tests/test_stalls.py`
  (`NoFalseStuckAfterRestart`). This did **not** cause the two failed openings above (nothing had ever been downloaded for them). It may have contributed to the frequent restarts noted in section 5 (unverified).
* Verified on one machine: Ubuntu 24.04, GNOME/Wayland, ext4, Intel graphics, Python 3.12, PyQt6 6.6.1, libmpv 0.37. X11, NVIDIA/AMD, other
  distributions and filesystems are unverified.
* The player was exercised end to end against **local** swarms (torrent file and magnet link, seeks, pause, volume, track selection). Real-internet
  playback through the GUI was not part of the automated tests; engine-level real-swarm runs are described in section 5.
* Screenshots in `docs/gui/` are Qt widget grabs (offscreen or from the live window); they were not taken by an external screen recorder.
* Audio/subtitle selection was exercised on files with one audio track and no subtitles; menu construction for many tracks is unit-level only.
* Fullscreen was verified in code and offscreen, not on a real multi-monitor setup.
* The tutorial and error dialogs were checked at window sizes from 720×480 to 1920×1080 (layout assertions plus screenshots); screen-reader behaviour was not tested
  (this PyQt6 build exposes no `QAccessible`, so only accessible names/descriptions are set).
* GNOME's "reduce animations" setting is read once at startup.
* Stale `kino-stream-<pid>.sock` files can remain in `$XDG_RUNTIME_DIR` after killed command-line runs (harmless).
* Launching from the GNOME application menu was not clicked through. The installed `.desktop` file was launched with `gio launch` from a throw-away profile (manual check), plus a second launch to confirm hand-over to the running window.

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

## Intermittent: `test_magnet_link_plays_end_to_end` (GUI player test)

Seen twice (2 of ~14 runs, both right after a long full-suite run); the failing runs took ~100 s because the test waited its full 60 s for playback after the open had succeeded. In the failing runs mpv never reached 2 s of playback within 60 s; the engine snapshot was not captured then (the failure message now includes the snapshot, mpv log lines and engine event codes).
Not reproduced since: 1 + 12 solo runs, 12 runs with three in parallel, 6 module runs under full-CPU load, all passing. Root cause is **inconclusive**. Candidates, none confirmed: the magnet path's metadata→re-add step (the engine already waits 0.4 s there after a known peer-teardown race), or a local-port reuse race (`free_port()` hands out a port that is bound a moment later). If it recurs, read the snapshot in the assertion message first: `peers == 0` with `phase == opening/starting` points at the magnet re-add; `peers > 0` with no `pieces_have` growth points at the store.

## Intermittent: `tests.test_stalls.LostRequests.test_black_holed_seeder_requests_are_cancelled_and_reissued` (engine test)

Fails with "stall must be noticed" (the HTTP server did not count a stall within 15 s after the seeder was throttled to 1 B/s). Seen in 1 of 3 discovery
runs and 1 of 3 module runs during P5 (it passed in the earlier full runs and alone 4/4). No engine code involved in this path (`httpd.py`, `lt_store.py`) changed in P5.
Not investigated further; likely timing (the range requested may already be partly delivered by in-flight requests when the throttle starts). Treat a failure here as "unknown" rather than
proof of a regression, and rerun it alone. Root cause: **unknown**.
