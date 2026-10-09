# kino-stream

Watch a torrent **while it downloads**, with an optional **hard-bounded disk cache** (Prizma-style): old pieces are evicted,
upcoming pieces are fetched ahead of the playback position, and a backward seek simply downloads what was evicted again.

    mpv  <-HTTP Range->  scheduler  ->  PieceStore (BoundedSparseStore)  ->  libtorrent  ->  sparse file on disk

Standalone: it does not touch other applications (media servers, torrent clients), and it never asks your router to open ports (no UPnP).

## Install
    sudo apt install python3-libtorrent mpv ffmpeg          # ffmpeg only for the tests
    git clone / copy this directory, then use it in place:
    ./bin/kino-stream --help                                # or: python3 -m kino_stream --help
    # optional: pip install --user -e .   (gives a `kino-stream` command; python-libtorrent still comes from apt)

Requirements: Python >= 3.12, python3-libtorrent 2.0.x, mpv, Linux. For the bounded cache: a filesystem that frees blocks on
`fallocate(PUNCH_HOLE)` (tested: ext4; the program probes it and refuses to start otherwise - it never falls back to anything unsafe).

## Use
Bounded cache, 3 GB hard limit, 150 MB kept behind the playhead for backward seeks (recommended):

    ./bin/kino-stream play "Movie.torrent" --save-path ~/.cache/kino-stream/movie --cache-limit-gb 3 --cache-back-mb 150

Unbounded (everything downloaded stays): drop `--cache-limit-gb`. Stop with `q` in mpv or Ctrl-C; a summary line is printed.
Resume later with the same command and the same `--save-path`: retained pieces are reused, an interrupted session is recovered.

| option | meaning |
|---|---|
| `--cache-limit-gb N` / `--cache-limit-mb N` | hard limit on *allocated* disk blocks of `--save-path` (0 = unbounded) |
| `--cache-back-mb N` | keep this much behind the playhead (default 5% of the limit) |
| `--save-path DIR` | cache directory. With a limit it must be dedicated to this torrent (data without an index is refused) |
| `--peer host:port` | peer hint, repeatable; helps when DHT/trackers are blocked |
| `--encryption forced` | BitTorrent protocol encryption; some networks treat plain BitTorrent differently |
| `--no-mpv` | only serve the HTTP URL (open it in any player that supports Range) |
| `--headless`, `--quit-after S`, `--ipc-socket P` | automation: no video output, stop after S seconds, mpv JSON IPC path |
| `--status-interval S` | log peers / pieces / disk usage every S seconds (default 10; 0 = off) |

Use a `.torrent` file when you can. Magnet links need DHT, which is blocked or flaky on several networks (see `docs/NETWORK_FINDINGS.md`).

### What the bounded cache guarantees
* `allocated blocks <= limit` at all times (requests are admitted only while there is room; stale data is evicted first - playback may briefly wait, the limit does not give).
* Evicted pieces are never served, uploaded or advertised: eviction removes the torrent from the session, punches the holes, and re-adds it with an exact `have_pieces` taken from a durable index (never from libtorrent resume data). Every HTTP byte is checked in tests against the original file.
* Crash-safe: journal + startup recovery before any peer connection (verified with simulated crashes at every step and with real `SIGKILL` of the process group while evicting).
* Details, crash table, policy: `docs/STAGE2_DESIGN.md`.

## Troubleshooting
    ./bin/kino-stream doctor --save-path ~/.cache/kino-stream/movie             # local checks (libtorrent, mpv, hole punching, free space, VPN hint)
    ./bin/kino-stream doctor --network                                          # + DHT / UDP trackers / DNS-over-UDP / exit IP probes, with CONFIRMED vs HYPOTHESIS verdicts
    ./bin/kino-stream play X.torrent --status-interval 3 ...                    # watch peers, pieces, disk, evictions
    tail -n 40 ~/.local/state/kino-stream/crash.log                             # native crash stacks (should stay empty)

| symptom | what to do |
|---|---|
| `peers=0 (waiting for peers ...)` | run `doctor --network`; if DHT/UDP trackers do not answer use a `.torrent` with HTTP/TCP trackers and `--peer`; try `--encryption forced` |
| `error: bounded cache is not possible here` | the directory's filesystem does not release blocks on hole punching; use another directory (ext4/xfs/btrfs/tmpfs) or no limit |
| `error: ... not managed by a bounded cache` | the directory contains data without an index; use an empty `--save-path` (or delete the old directory) |
| `error: cache limit ... is too small` | raise `--cache-limit-gb` or lower `--cache-back-mb` / `--mpv-cache-mb` |
| playback pauses at seeks | expected until the first pieces arrive: seconds on a healthy swarm; slower when peers are few |
| reset a cache completely | delete the `--save-path` directory **and** `~/.local/state/kino-stream/<infohash>.cache.json` |

Known limitations and open risks: `docs/KNOWN_ISSUES.md`. Network findings: `docs/NETWORK_FINDINGS.md`. Stage 1 numbers: `docs/STAGE1_VALIDATION.md`.

## Tests
    python3 -m unittest tests.test_cache tests.test_cli tests.test_alert_safety       # Stage 2, ~7 min
    python3 -m unittest discover -s tests -t .                                         # everything, ~30 min (needs ffmpeg + mpv)

Opt-in heavy/diagnostic tools: `tests/large_scenarios.py` (25 GB files), `tests/realswarm.py` (internet), `diag/` (network diagnostics,
`alert_stress.py`, `kill_storm.py`).

## Layout
`kino_stream/`: `piecemap.py` (offsets/pieces/files) - `store.py` (interface) - `lt_store.py` (Stage 1 store, alert pump, restarts) -
`bounded_store.py` + `cacheindex.py` + `punch.py` (bounded cache) - `scheduler.py` - `httpd.py` - `mpvctl.py` - `session.py` - `doctor.py`/`netprobe.py`.
