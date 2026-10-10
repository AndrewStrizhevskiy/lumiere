# How Lumière works

## Streaming from a torrent

A torrent splits a file into fixed-size **pieces** (typically 0.25–4 MB). People who have pieces ("peers") send them to you; you get
different pieces from different peers, in whatever order libtorrent finds efficient. A normal torrent client downloads the
*rarest* pieces first, which is good for the swarm but useless for watching a video.

Lumière changes the order of what it **asks for**:

```
mpv  ──HTTP range requests──▶  local server  ──▶  scheduler  ──▶  libtorrent  ◀──▶  peers
 ▲                                  │                  │
 └── plays bytes as they arrive ◀───┘      "the next N seconds after the playhead first"
```

1. mpv reads the video from a small local web server (`127.0.0.1`, random port) using normal HTTP range requests.
2. The scheduler looks at where mpv is playing and at the video's measured bitrate, and tells libtorrent to prioritise the pieces just
   ahead of the playhead (and, at the start, the beginning and the end of the file, where many formats keep their index).
3. If mpv asks for bytes whose pieces have not arrived, the server **waits** for them. That wait is the "buffering" you see.
4. Every piece is verified by libtorrent's hash check before it is served; in tests every served byte is compared with the original file.

## Why playback and seeking depend on peers and the network

Lumière can only play what it has downloaded. Therefore:

* **Start-up** needs at least one peer that has the first pieces. Finding peers needs a tracker or DHT; some networks block those
  (see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)). On a healthy swarm the first frame appears in seconds; on a poor one it can take a minute or never.
* **Smooth playback** needs a sustained download rate above the video's bitrate. If few peers share the video, they are slow, or your
  connection is slow or congested, mpv runs out of data and pauses to wait. That is not a bug and nothing in the app can prevent it.
* **Seeking** to a part that has not been downloaded means starting a fresh request there. The seek bar shows what is already on disk
  (grey) and what is not (dark). Jumping into the dark is only as fast as the swarm. Jumping back to a part that was removed from the
  cache downloads it again.
* The status messages say only what was measured ("no sources right now", "N sources, X MB/s"). "Check my connection" can *confirm*
  specific facts (for example that DHT did not answer on this network). It cannot tell you *why*; whether an ISP is throttling BitTorrent
  is a hypothesis it labels as such.
* The seek bar's grey layer is by position in the **file**, the bar itself is by **time**. They coincide for constant-bitrate video and only approximate otherwise.

## The bounded cache

Streaming needs somewhere to put pieces. Lumière stores them in one **sparse file** per video and keeps the number of disk blocks
actually allocated below the limit you set (default 4 GB):

* Pieces behind the playhead are removed ("eviction") by punching holes in the file (`fallocate(PUNCH_HOLE)`), keeping a window
  behind you for short backward seeks (Settings → *Keep what you watched*).
* A durable index, not libtorrent, is the authority on what is on disk. An eviction is journalled first, so after a crash or power loss it is
  completed on the next start before any peer connects.
* Because libtorrent cannot "forget" a piece, an eviction removes the torrent from the session and adds it back with the exact set of
  pieces kept. **All peer connections drop for a moment each time** (measured at ~0.45 s plus ~0.7 s reconnect on a loopback test, unmeasured on real
  swarms). Evictions are batched to keep this rare.
* New requests are admitted only while there is room; if the cache is full of data that must stay (the window ahead, the file's start and
  end), downloading waits for room.

### What the cache limit guarantees

* **Guaranteed (tested):** the allocated blocks of the cache folder do not exceed the limit (plus a small reserve that is counted inside it);
  evicted data is never served, uploaded or advertised; an interrupted eviction is recovered; a filesystem that cannot release blocks is detected
  and refused rather than ignored.
* **Not guaranteed:** playback continuity. The limit is hard, read-ahead is not: under pressure playback may pause while room is made. A limit
  too small for the window plus read-ahead is rejected at start with an explanation.
* **Not covered:** the state files in `~/.local/state/lumiere` and mpv's small in-memory cache are outside the limit. Only ext4 has been tested.
  Power loss was simulated with process kills, not real power cuts.
* **Temporary mode** (offered only when the limit cannot be enforced, and only on your explicit confirmation) has **no limit**; its data is deleted when you close the video.

Design and crash analysis: [STAGE2_DESIGN.md](STAGE2_DESIGN.md). Known limits: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Threads

All libtorrent calls happen in one engine thread (`lumiere-engine`). The window talks to it through a thread-safe facade and Qt signals; the UI never imports
libtorrent. libtorrent alerts are read with `pop_alerts()` only — `wait_for_alert()` in the Python binding caused crashes and is forbidden by a test
(see the fixed defects in KNOWN_ISSUES.md).
