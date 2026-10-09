# Stage 1 validation (25 GB synthetic files, local throttled seeder, real mpv)

Files: `big_cues_end.mkv`, `big_moov_front.mp4`, `big_moov_end.mp4`, each 25.07 GB / 7142 s / ~3.5 MB/s (CBR H.264+AAC,
generated with ffmpeg, `tests/largemedia.py`). Torrent piece size 4 MiB (5977 pieces). One seeder on loopback, throttled.
Raw numbers: `docs/large_report.json`. Reproduce: `python -m tests.largemedia && python -m tests.large_scenarios all`.

| scenario (75 s of playback, then seek to 30:00) | startup | rebuffers (count / s) | downloaded | peak disk | HTTP sent | seek recovery |
|---|---|---|---|---|---|---|
| seeder 2.0x bitrate (7 MB/s)    | 2.6 s | 7 / 3.6  | 169 pieces, 711 MB (2.8%) | 703 MB | 448 MB | 3.0 s |
| seeder 1.05x bitrate (3.7 MB/s) | 3.7 s | 30 / 18.3 | 89 pieces, 379 MB (1.5%) | 378 MB | 302 MB | 5.8 s |
| seeder 0.5x bitrate (1.75 MB/s) | 5.6 s | 42 / 51.9 | 46 pieces, 196 MB (0.8%) | 196 MB | 181 MB | 11.2 s |

Seeks (2x seeder): 0->10 min 5.0 s, 10 min->105 min 4.9 s, 105->30 min 4.7 s, 30->2 min 3.6 s, near start->near end 4.7 s,
near end->start 2.1 s; 52-73 MB downloaded per seek; deadlines left on abandoned pieces after each seek: 0.

Containers (3 seeks each): first frame after 2.7 s (MKV, Cues at end), 3.7 s (MP4 moov front), 5.7 s (MP4 moov end);
bytes downloaded before first frame 10 / 17 / 31 MB; after 3 seeks 246-320 MB in total (~1% of the file).
The 6 MB `moov` at the end of the MP4 is recognised as a probe, not as a seek (1 probe connection, 3 seeks detected).

Bounded read-ahead: a raw client sending `Range: bytes=0-` (Content-Length 25,067,151,573) for 40 s received 455 MB
(window 315 MB + 40 s of pace); 110 pieces / 459 MB downloaded (1.8%), peak disk 459 MB. mpv: 120 s from the start, jump
to 90:00, 60 s more: 1.13 GB downloaded (4.5%), peak disk 1.12 GB, HTTP 833 MB.
**Stage 1 never deletes anything**, so disk use grows with what was watched; what is *required* at any moment is the window
(~0.3 GB here). Making that a hard bound is Stage 2.

Caveats: one seeder on loopback (peers_max 1), no real swarm, no DHT/trackers; synthetic CBR video; mpv headless;
a single 54 s seek (default libtorrent request timeout) was seen once in an earlier run, then mitigated
(`request_timeout`/`piece_timeout` lowered, stalled pieces cancel + re-request) but not reproduced afterwards.
