# Command line reference

    lumiere play SOURCE [options]       # SOURCE: .torrent file or magnet link; opens mpv
    lumiere doctor [--network] [--save-path DIR]
    lumiere --version

| option | meaning |
|---|---|
| `--cache-limit-gb N` / `--cache-limit-mb N` | hard limit on *allocated* disk blocks of `--save-path` (0 = unbounded) |
| `--cache-back-mb N` | keep this much behind the playhead (default 5% of the limit) |
| `--save-path DIR` | cache directory. With a limit it must be dedicated to this torrent (data without an index is refused) |
| `--peer host:port` | peer hint, repeatable; helps when DHT/trackers are blocked |
| `--encryption forced` | BitTorrent protocol encryption; some networks treat plain BitTorrent differently |
| `--no-mpv` | only serve the HTTP URL (open it in any player that supports Range) |
| `--headless`, `--quit-after S`, `--ipc-socket P` | automation: no video output, stop after S seconds, mpv JSON IPC path |
| `--file N` | play file N of a multi-file torrent (default: the largest video file) |
| `--status-interval S` | log peers / pieces / disk usage every S seconds (default 10; 0 = off) |
| `--mpv-cache-mb N`, `--mpv-arg ARG` | mpv's own demuxer cache / extra mpv arguments |
| `--no-dht`, `--listen ADDR`, `--state-dir DIR`, `--verify-source` | engine options (see `--help`) |

Stop with `q` in mpv or Ctrl-C; a one-line summary is printed. Resume with the same command and `--save-path`.
`doctor` runs local checks (libtorrent, mpv, hole punching, free space); `doctor --network` adds read-only DHT/UDP-tracker/DNS probes,
each result labelled *confirmed*, *observed* or *hypothesis*.
