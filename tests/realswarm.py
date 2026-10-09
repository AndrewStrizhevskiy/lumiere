"""Real public swarm validation (opt-in; needs internet). Blender open-movie torrents distributed by webtorrent.io:
legal, CC-licensed, public trackers + DHT, no private trackers.

    python -m tests.realswarm sintel torrent noweb 1      # <name> <torrent|magnet> <web|noweb> <trials>

Torrent files are expected in tests/.cache/torrents/. Results are appended to docs/real_swarm_report.json.
"web" = HTTP web seed enabled (not BitTorrent), "noweb" = pure BitTorrent swarm (what we want to measure).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import libtorrent as lt

from kino_stream.config import Config, MiB
from kino_stream.session import StreamSession
from tests.large_scenarios import seek_and_measure
from tests.support import disk_usage

TORRENTS = Path(__file__).parent / ".cache" / "torrents"
REPORT = Path(__file__).resolve().parent.parent / "docs" / "real_swarm_report.json"


def magnet_for(ti: lt.torrent_info) -> str:
    # trackers only: NO ws= web seed, so this exercises pure BitTorrent metadata exchange (ut_metadata via peers/DHT)
    return f"magnet:?xt=urn:btih:{ti.info_hash()}&dn={ti.name().replace(' ', '+')}" + "".join(f"&tr={t.url}" for t in ti.trackers())


def block_everything(session, on: bool) -> None:
    f = lt.ip_filter()
    if on:
        f.add_rule("0.0.0.0", "255.255.255.255", 1)
        f.add_rule("::", "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff", 1)
    session.set_ip_filter(f)


async def trial(name: str, mode: str, web: bool, idx: int, play_s: int = 90) -> dict:
    tpath = TORRENTS / f"{name}.torrent"
    ti = lt.torrent_info(str(tpath))
    tmp = Path(tempfile.mkdtemp(prefix=f"ks-real-{name}-"))
    cfg = Config(listen="0.0.0.0:0", dht=True, lsd=False, upnp=False, web_seeds=web, state_dir=tmp / "state",
                 metadata_timeout=150, readahead_s=45, min_readahead_bytes=8 * MiB, mpv_cache_bytes=8 * MiB,
                 mpv_back_bytes=4 * MiB, window_margin_bytes=2 * MiB, urgent_min_bytes=2 * MiB, piece_timeout=10.0,
                 hard_timeout=120.0)
    import os as _os
    if _os.environ.get("KS_CACHE_MB"):
        cfg.cache_limit_bytes = int(float(_os.environ["KS_CACHE_MB"]) * MiB)
    series: list[dict] = []
    res: dict = {"cache_limit_bytes": int(float(os.environ.get("KS_CACHE_MB", 0)) * MiB) if (os := __import__("os")) else 0, "torrent": name, "mode": mode, "web_seeds": web, "trial": idx, "file_total_bytes": ti.total_size()}
    t_open = time.monotonic()
    source = magnet_for(ti) if mode == "magnet" else str(tpath)
    s = await StreamSession.open(cfg, source, tmp / "dl")
    res["metadata_s"] = round(time.monotonic() - t_open, 2)
    print("  metadata/open %.1fs" % res["metadata_s"], flush=True)
    pm = s.store.piece_map
    sel = pm.files[s.file_index]
    res.update(selected_file=sel.path, selected_file_bytes=sel.size, piece_length=pm.piece_length,
               pieces_total=pm.num_pieces, torrent_files=[(f.path, f.size) for f in pm.files])
    stop = asyncio.Event()
    peak = {"disk": 0}

    async def sampler():
        t0 = time.monotonic()
        while not stop.is_set():
            try:
                st = s.store.handle.status()
            except RuntimeError:                                 # handle is being replaced by a restart
                await asyncio.sleep(0.5)
                continue
            u = disk_usage(tmp / "dl")
            peak["disk"] = max(peak["disk"], u)
            series.append({"t": round(time.monotonic() - t0, 1), "peers": st.num_peers, "seeds": st.num_seeds,
                           "list_peers": st.list_peers, "rate_kBps": round(st.download_payload_rate / 1000),
                           "disk": u, "have": s.store.stats().get("pieces_have", -1)})
            await asyncio.sleep(1.0)
    sam = asyncio.create_task(sampler())
    try:
        mpv = await s.play(headless=True, use_user_config=False)
        res["startup_s"] = round(await mpv.wait_playing(0.5, timeout=150), 2)
        print("  first frame after %.1fs" % res["startup_s"], flush=True)
        res["initial_buffer_s"] = round(mpv.initial_buffer_s, 1)
        res["bytes_at_first_frame"] = s.store.stats()["total_download"]
        res["pieces_at_first_frame"] = s.store.stats()["pieces_have"]
        dur = mpv.state.duration
        res["duration_s"] = dur
        # --- steady playback
        rb0, rbs0 = mpv.rebuffers, mpv.rebuffer_s
        p0 = mpv.state.time_pos
        await asyncio.sleep(play_s)
        res["steady"] = {"wall_s": play_s, "played_s": round(mpv.state.time_pos - p0, 1),
                         "rebuffers": mpv.rebuffers - rb0, "rebuffer_s": round(mpv.rebuffer_s - rbs0, 1)}
        # --- seeks: middle, near end, near start, back to middle, very end, start
        seeks = []
        for label, frac in (("10%", 0.10), ("50%", 0.50), ("92%", 0.92), ("2%", 0.02), ("50% again", 0.50),
                            ("99%", 0.99), ("0:05", 5 / dur)):
            x = await seek_and_measure(s, mpv, dur * frac, play_s=3, timeout=150)
            x["label"] = label
            seeks.append(x)
            print("  seek", label, x["restart_event_s"], x["recovery_s"], flush=True)
        res["seeks"] = seeks
        # --- all peers become unavailable for 12 s while playing, then return
        await seek_and_measure(s, mpv, dur * 0.30, play_s=5, timeout=150)
        st_before = s.store.stats()
        block_everything(s.store.session, True)
        t_block = time.monotonic()
        await asyncio.sleep(12)
        peers_during = s.store.handle.status().num_peers
        stalled_pos = mpv.state.time_pos
        block_everything(s.store.session, False)
        t_unblock = time.monotonic()
        rec = None
        while time.monotonic() - t_unblock < 90:
            st = mpv.state
            if st and st.time_pos is not None and st.time_pos > stalled_pos + 2.0 and not st.paused_for_cache and s.store.handle.status().num_peers > 0:
                rec = time.monotonic() - t_unblock
                break
            await asyncio.sleep(0.2)
        st_after = s.store.stats()
        res["peer_outage_12s"] = {"peers_during_outage": peers_during, "recovered_playback_s": None if rec is None else round(rec, 1),
                                  "restarts": st_after["restarts"] - st_before["restarts"],
                                  "zero_peer_s_added": round(st_after["zero_peer_s"] - st_before["zero_peer_s"], 1),
                                  "http_stalls": s.server.stats["stalls"], "http_aborted": s.server.stats["aborted"]}
        await asyncio.sleep(10)
        # --- totals
        st = s.store.stats()
        have = {i for i in range(pm.num_pieces) if s.store.have(i)}
        outside = sorted(have - s.store.ever_demanded)
        peers = [x["peers"] for x in series]
        res.update(
            bytes_downloaded=st["total_download"], pieces_downloaded=st["pieces_have"],
            fraction_of_file=round(st["total_download"] / sel.size, 3), peak_allocated_disk_bytes=peak["disk"],
            http_bytes_sent=s.server.stats["bytes_sent"], mpv_total_rebuffers=mpv.rebuffers,
            mpv_total_rebuffer_s=round(mpv.rebuffer_s, 1), hash_failed=st["hash_failed"], restarts=st["restarts"],
            peer_connects=st["peer_connects"], peer_disconnects=st["peer_disconnects"], zero_peer_s=st["zero_peer_s"],
            peers_min=min(peers), peers_median=statistics.median(peers), peers_max=max(peers),
            seeds_max=max(x["seeds"] for x in series), pieces_ever_demanded=len(s.store.ever_demanded),
            pieces_downloaded_but_never_demanded=outside[:20], count_outside_window=len(outside),
            deadline_sets=st["deadline_sets"], obsolete_pieces_cancelled=st["obsolete_cancelled"],
            http_mismatch=s.server.stats["mismatches"], seeks_detected=s.sched.counters["seeks"], stalls=st["restarts"] + s.server.stats["stalls"])
        res["series_every_5s"] = series[::5]
        save(res)                                                    # persist BEFORE teardown: close() once crashed the process
    finally:
        stop.set()
        await sam
        try:
            await asyncio.wait_for(s.close(), 30)
        except Exception as e:
            print('  close problem:', repr(e), flush=True)
        finally:
            shutil.rmtree(tmp, True)
    return res


def save(r: dict) -> None:
    try:
        d = json.loads(REPORT.read_text())
    except Exception:
        d = []
    d.append(r)
    REPORT.write_text(json.dumps(d, indent=1))


async def main():
    name, mode, web, n = sys.argv[1], sys.argv[2], sys.argv[3] == "web", int(sys.argv[4])
    for i in range(n):
        print(f"=== {name} {mode} web={web} trial {i + 1}/{n}", flush=True)
        r = await trial(name, mode, web, i)
        brief = {k: v for k, v in r.items() if k not in ("series_every_5s", "torrent_files", "seeks")}
        print(json.dumps(brief), flush=True)
        for sk in r["seeks"]:
            print("   seek", json.dumps(sk), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
