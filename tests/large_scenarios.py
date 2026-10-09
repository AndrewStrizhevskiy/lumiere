# SPDX-License-Identifier: GPL-3.0-or-later
"""Large-file validation (opt-in, slow). ~25 GB files, local throttled seeder, real mpv.

    python -m tests.largemedia                       # once: generate the files (~20 min, ~75 GB in ~/.cache)
    python -m tests.large_scenarios bandwidth|seeks|bounded|containers|all

Writes docs/large_report.json. Nothing here downloads the whole file: the seeder is slow on purpose and
playback is real time.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import libtorrent as lt

from kino_stream.config import KiB, MiB
from kino_stream.session import StreamSession
from tests.largemedia import BASE, BITRATE_BPS, ensure_large
from tests.support import Seeder, disk_usage, free_port, leech_config

REPORT = Path(__file__).resolve().parent.parent / "docs" / "large_report.json"
PIECE = 4 * MiB
OVERRIDES: dict = {}      # key=value command-line overrides of Config fields, e.g. urgent_s=3


def large_torrent(path: Path) -> lt.torrent_info:
    tf = BASE / (path.name + ".torrent")
    if tf.exists():
        return lt.torrent_info(str(tf))
    t = time.time()
    fs = lt.file_storage()
    lt.add_files(fs, str(path))
    ct = lt.create_torrent(fs, PIECE, flags=lt.create_torrent.v1_only)
    lt.set_piece_hashes(ct, str(BASE))
    data = lt.bencode(ct.generate())
    tf.write_bytes(data)
    print(f"  hashed {path.name} in {time.time() - t:.0f}s", flush=True)
    return lt.torrent_info(data)


async def seek_and_measure(s, m, t: float, play_s: float = 3.0, timeout: float = 180) -> dict:
    """Seek mpv to t seconds and measure: playback-restart event, time until playback really moves again,
    bytes downloaded meanwhile, rebuffers, and deadlines still set on pieces far from the new head."""
    d0 = s.store.stats()["total_download"]
    rb0, rbs0 = m.rebuffers, m.rebuffer_s
    before = len(m.events)
    t_cmd = time.monotonic()
    await m.seek(t)
    restart = None
    while time.monotonic() - t_cmd < timeout:
        ev = [e for e in m.events[before:] if e[1] == "playback-restart"]
        if ev:
            restart = ev[0][0] - t_cmd
            break
        await asyncio.sleep(0.02)
    pos0 = None
    resumed = None
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = m.state
        if st and st.ts > t_cmd and st.time_pos is not None and not st.paused_for_cache:
            if pos0 is None:
                pos0 = st.time_pos
            elif st.time_pos >= pos0 + 1.0:
                resumed = time.monotonic() - t_cmd - 1.0
                break
        await asyncio.sleep(0.05)
    await asyncio.sleep(play_s)
    head = s.sched.head_byte()
    pm = s.store.piece_map
    stale = [p for p, (pr, dl) in s.store.applied().items() if dl is not None
             and not (head - 2 * pm.piece_length <= p * pm.piece_length <= head + s.sched.window_bytes())]
    return {"target_s": t, "restart_event_s": None if restart is None else round(restart, 2),
            "recovery_s": None if resumed is None else round(resumed, 2),
            "downloaded_MB": round((s.store.stats()["total_download"] - d0) / 1e6, 1),
            "rebuffers": m.rebuffers - rb0, "rebuffer_s": round(m.rebuffer_s - rbs0, 1),
            "stale_deadlines_after": len(stale), "head_source": s.sched.head_source()}


class Run:
    """One leech session + a disk-usage sampler + (optionally) mpv."""

    def __init__(self, name: str, media: Path, seeder_bps: int, **over):
        self.name, self.media, self.seeder_bps, self.over = name, media, seeder_bps, over
        self.tmp = Path(tempfile.mkdtemp(prefix=f"ks-large-{name}-"))
        self.peak_disk = 0
        self.disk_series: list[tuple[float, int]] = []
        self.t0 = time.monotonic()

    async def __aenter__(self):
        ti = large_torrent(self.media)
        self.seeder = Seeder(self.media, upload_limit=self.seeder_bps, ti=ti, data_parent=BASE, trust_data=True)
        kw = dict(readahead_s=90, min_readahead_bytes=128 * MiB, urgent_s=4, urgent_min_bytes=8 * MiB,
                  mpv_cache_bytes=64 * MiB, mpv_back_bytes=32 * MiB, window_margin_bytes=16 * MiB,
                  verify_source=self.media, piece_timeout=10.0, hard_timeout=120.0)
        kw.update(OVERRIDES)
        kw.update(self.over)
        self.cfg = leech_config(self.tmp, self.seeder, **kw)
        self.s = await StreamSession.open(self.cfg, ti, self.tmp / "dl")
        self.size = self.s.store.piece_map.files[self.s.file_index].size
        self._sampler = asyncio.create_task(self._sample())
        self.mpv = None
        return self

    async def _sample(self):
        while True:
            u = disk_usage(self.tmp / "dl")
            self.peak_disk = max(self.peak_disk, u)
            self.disk_series.append((round(time.monotonic() - self.t0, 1), u))
            await asyncio.sleep(0.5)

    async def play(self):
        self.t_play = time.monotonic()
        self.mpv = await self.s.play(headless=True, use_user_config=False)
        self.startup = await self.mpv.wait_playing(0.5, timeout=120)
        return self.startup

    async def seek(self, t: float, play_s: float = 3.0, timeout: float = 180) -> dict:
        return await seek_and_measure(self.s, self.mpv, t, play_s, timeout)

    def metrics(self) -> dict:
        s, m = self.s, self.mpv
        st = s.store.stats()
        pm = s.store.piece_map
        return {
            "file_bytes": self.size, "piece_length": pm.piece_length, "pieces_total": pm.num_pieces,
            "pieces_downloaded": st["pieces_have"], "bytes_downloaded": st["total_download"],
            "peak_allocated_disk_bytes": self.peak_disk, "http_bytes_sent": s.server.stats["bytes_sent"],
            "playback_s": None if not (m and m.state) else round(m.state.time_pos or 0, 1),
            "startup_s": None if not m else round(self.startup, 2),
            "rebuffer_count": None if not m else m.rebuffers, "rebuffer_s": None if not m else round(m.rebuffer_s, 1),
            "initial_buffer_s": None if not m else round(m.initial_buffer_s, 1),
            "deadline_sets": st["deadline_sets"], "deadline_resets": st["deadline_resets"],
            "obsolete_pieces_cancelled": st["obsolete_cancelled"], "hash_failed": st["hash_failed"],
            "peers_max": st["peers_max"], "peer_connects": st["peer_connects"], "peer_disconnects": st["peer_disconnects"],
            "zero_peer_s": st["zero_peer_s"], "alerts_dropped": st["alerts_dropped"],
            "http_mismatches": s.server.stats["mismatches"], "http_aborted": s.server.stats["aborted"],
            "stalls": s.server.stats["stalls"], "seeks_detected": s.sched.counters["seeks"],
        }

    async def __aexit__(self, *a):
        self._sampler.cancel()
        try:
            await self.s.close()
        finally:
            self.seeder.close()
            shutil.rmtree(self.tmp, True)


def save(section: str, value) -> None:
    REPORT.parent.mkdir(exist_ok=True)
    try:
        d = json.loads(REPORT.read_text())
    except Exception:
        d = {}
    d[section] = value
    REPORT.write_text(json.dumps(d, indent=1, sort_keys=True))


# ------------------------------------------------------------------------------------------- scenarios
async def bandwidth(media):
    out = {}
    for label, ratio in (("seeder_2x_bitrate", 2.0), ("seeder_1.05x_bitrate", 1.05), ("seeder_0.5x_bitrate", 0.5)):
        print(f"--- bandwidth: {label}", flush=True)
        async with Run(label, media, int(BITRATE_BPS * ratio)) as r:
            await r.play()
            await asyncio.sleep(75)                              # 75 s of wall-clock playback
            seek = await r.seek(1800)                            # then jump to 30:00
            await asyncio.sleep(20)
            m = r.metrics()
            m["seek_to_30min"] = seek
            m["seeder_bytes_per_s"] = int(BITRATE_BPS * ratio)
            m["paused_for_cache_total_s"] = round(r.mpv.rebuffer_s + r.mpv.initial_buffer_s, 1)
            out[label] = m
            print(json.dumps(m), flush=True)
    save("bandwidth", out)
    return out


async def seeks(media):
    print("--- seeks on", media.name, flush=True)
    steps = [("0 -> 10 min", 600), ("10 min -> 105 min", 6300), ("105 min -> 30 min", 1800),
             ("30 min -> 2 min (near start)", 120), ("near start -> near end (118 min)", 7080), ("near end -> start", 5)]
    async with Run("seeks", media, int(BITRATE_BPS * 2.0)) as r:
        await r.play()
        await asyncio.sleep(8)
        res = []
        for label, t in steps:
            x = await r.seek(t, play_s=4)
            x["step"] = label
            res.append(x)
            print(json.dumps(x), flush=True)
        m = r.metrics()
        m["seek_steps"] = res
        save("seeks", m)
        return m


async def bounded(media):
    """File size vs required local storage, and a huge open-ended Range."""
    print("--- bounded cache principle", flush=True)
    out = {}
    # (a) raw client, Range: bytes=0-, reads as fast as the server allows, for 40 s, real-time-ish virtual clock
    async with Run("bounded_raw", media, 50 * MiB, assumed_bytes_per_s=BITRATE_BPS) as r:
        port, path = r.s.server.port, r.s.server.path
        rd, wr = await asyncio.open_connection("127.0.0.1", port)
        wr.write(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nRange: bytes=0-\r\n\r\n".encode())
        head = await rd.readuntil(b"\r\n\r\n")
        got, t0 = 0, time.monotonic()
        while time.monotonic() - t0 < 40:
            try:
                c = await asyncio.wait_for(rd.read(4 * MiB), 0.5)
                got += len(c)
            except asyncio.TimeoutError:
                pass
        wr.close()
        win = r.s.sched.window_bytes()
        m = r.metrics()
        m.update(scenario="raw client Range: bytes=0- (declared length = whole file), 40 s", window_bytes=win,
                 client_received_bytes=got, declared_content_length=r.size,
                 expected_max_bytes=win + 40 * BITRATE_BPS + 8 * MiB)
        out["raw_open_ended_range"] = m
        print(json.dumps(m), flush=True)
        assert got <= m["expected_max_bytes"], f"open-ended range streamed {got} B"
        assert m["pieces_downloaded"] * PIECE < 0.1 * r.size
    # (b) mpv plays 120 s of wall-clock then seeks far; storage needed ~ viewed + window, not file size
    async with Run("bounded_mpv", media, int(BITRATE_BPS * 2.0)) as r:
        await r.play()
        await asyncio.sleep(120)
        m1 = r.metrics()
        await r.seek(5400, play_s=60)
        m = r.metrics()
        m.update(scenario="mpv 120 s from start, jump to 90:00, 60 s more", window_bytes=r.s.sched.window_bytes(),
                 first_phase_bytes_downloaded=m1["bytes_downloaded"], first_phase_peak_disk=m1["peak_allocated_disk_bytes"])
        out["mpv_play_and_far_seek"] = m
        print(json.dumps(m), flush=True)
    save("bounded", out)
    return out


async def containers(files):
    out = {}
    for name in ("big_moov_front", "big_moov_end", "big_cues_end"):
        print(f"--- container: {name}", flush=True)
        async with Run(name, files[name], int(BITRATE_BPS * 2.0)) as r:
            await r.play()
            st0 = r.s.store.stats()
            at_start = {"bytes_downloaded": st0["total_download"], "pieces": st0["pieces_have"],
                        "window_bytes": r.s.sched.window_bytes()}
            await asyncio.sleep(10)
            s1 = await r.seek(3600, play_s=5)
            s2 = await r.seek(7100, play_s=5)
            s3 = await r.seek(30, play_s=5)
            m = r.metrics()
            m.update(at_start=at_start, seek_mid=s1, seek_near_end=s2, seek_start=s3,
                     probe_connections=sum(1 for e in r.s.sched.events if e[1] == "conn_open" and e[2]["kind"] == "probe"),
                     pinned_ranges=r.s.sched.pinned)
            out[name] = m
            print(json.dumps(m, default=str), flush=True)
    save("containers", out)
    return out


async def main(which: str):
    files = ensure_large()
    big = files["big_cues_end"]
    for k, v in files.items():
        print(k, f"{v.stat().st_size / 2**30:.2f} GiB", flush=True)
    todo = ["bandwidth", "seeks", "bounded", "containers"] if which == "all" else [which]
    for t in todo:
        await {"bandwidth": lambda: bandwidth(big), "seeks": lambda: seeks(big),
               "bounded": lambda: bounded(big), "containers": lambda: containers(files)}[t]()


if __name__ == "__main__":
    for a in sys.argv[2:]:
        k, v = a.split("=")
        OVERRIDES[k] = float(v) if "." in v else int(v)
    if OVERRIDES:
        print("overrides:", OVERRIDES, flush=True)
    if OVERRIDES and "REPORT_SUFFIX" not in globals():
        REPORT = REPORT.with_name("large_report_" + "_".join(f"{k}{v}" for k, v in OVERRIDES.items()) + ".json")
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all"))
