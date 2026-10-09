#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain libtorrent benchmark (NOT the kino-stream application): isolates the network from our code.

    python3 diag/bt_bench.py sintel --seconds 60 [--iface wlan0] [--enc default|forced|disabled] [--label x]

Per-process only: UPnP/NAT-PMP are OFF (nothing is opened on the router), web seeds are OFF (pure BitTorrent), nothing
persistent is touched, data goes to a temp dir that is deleted. `--iface` binds sockets to that interface
(SO_BINDTODEVICE), which bypasses a TUN VPN without changing any route.
"""
import argparse, json, os, shutil, statistics, subprocess, sys, tempfile, time
import libtorrent as lt

ap = argparse.ArgumentParser()
ap.add_argument("torrent")
ap.add_argument("--seconds", type=int, default=60)
ap.add_argument("--iface")
ap.add_argument("--enc", default="default", choices=["default", "forced", "disabled"])
ap.add_argument("--port", type=int, default=0)
ap.add_argument("--label", default="")
ap.add_argument("--peers", help="file with ip:port,ip:port... added with connect_peer (when DHT/trackers are unusable)")
ap.add_argument("--out")
a = ap.parse_args()

C = lt.alert.category_t
s = {"enable_dht": True, "enable_lsd": False, "enable_upnp": False, "enable_natpmp": False,
     "alert_mask": int(C.error_notification | C.status_notification | C.tracker_notification | C.dht_notification),
     "alert_queue_size": 5000, "user_agent": "kino-stream-diag/1"}
if a.iface:
    ip = subprocess.run(["sh", "-c", f"ip -4 -br addr show {a.iface} | awk '{{print $3}}' | cut -d/ -f1"], capture_output=True, text=True).stdout.strip()
    s["outgoing_interfaces"] = a.iface
    s["listen_interfaces"] = f"{a.iface}:{a.port}"
else:
    s["listen_interfaces"] = f"0.0.0.0:{a.port}"
if a.enc == "forced":
    s.update(out_enc_policy=lt.enc_policy.forced, in_enc_policy=lt.enc_policy.forced, allowed_enc_level=lt.enc_level.rc4)
elif a.enc == "disabled":
    s.update(out_enc_policy=lt.enc_policy.disabled, in_enc_policy=lt.enc_policy.disabled)
sess = lt.session(s)
ti = lt.torrent_info(os.path.join(os.path.dirname(__file__), "..", "tests", ".cache", "torrents", a.torrent + ".torrent"))
tmp = tempfile.mkdtemp(prefix="ks-btbench-")
p = lt.add_torrent_params(); p.ti = ti; p.save_path = tmp
p.flags = (p.flags & ~lt.torrent_flags.auto_managed & ~lt.torrent_flags.paused) | lt.torrent_flags.override_web_seeds
p.url_seeds = []; p.http_seeds = []
h = sess.add_torrent(p)
if a.peers:
    for x in open(a.peers).read().split(','):
        ip_, port_ = x.rsplit(':', 1); h.connect_peer((ip_, int(port_)))
ev = {"tracker_reply": {}, "tracker_error": {}, "tracker_warning": 0, "dht_bootstrap": 0, "listen": [], "listen_failed": [], "dht_nodes": 0, "dht_global": 0, "other_errors": []}
series, seen_prev = [], set()
new_total = dropped_total = 0
t0 = time.time()
first_peer = first_byte = first_1MB = None
while time.time() - t0 < a.seconds:
    time.sleep(1.0)
    for al in sess.pop_alerts():
        n = type(al).__name__
        tu = lambda x: str(x.tracker_url() if callable(x.tracker_url) else x.tracker_url)
        if n == "tracker_reply_alert":
            ev["tracker_reply"][tu(al)] = ev["tracker_reply"].get(tu(al), []) + [al.num_peers]
        elif n == "tracker_error_alert":
            ev["tracker_error"][tu(al)] = (ev["tracker_error"].get(tu(al), []) + [str(al.error.message()) + " | " + str(getattr(al, "error_message", ""))])[:3]
        elif n == "tracker_warning_alert":
            ev["tracker_warning"] += 1
        elif n == "dht_bootstrap_alert":
            ev["dht_bootstrap"] += 1
        elif n == "dht_stats_alert":
            ev["dht_nodes"] = sum(b["num_nodes"] for b in al.routing_table)
        elif n == "listen_succeeded_alert":
            ev["listen"].append(al.message())
        elif n == "listen_failed_alert":
            ev["listen_failed"].append(al.message())
        elif n in ("file_error_alert", "torrent_error_alert"):
            ev["other_errors"].append(al.message())
    sess.post_dht_stats()
    st = h.status()
    pis = h.get_peer_info()
    cur = {(pi.ip[0], pi.ip[1]) for pi in pis}
    new_total += len(cur - seen_prev); dropped_total += len(seen_prev - cur); seen_prev = cur
    inbound = sum(1 for pi in pis if not (pi.flags & lt.peer_info.local_connection))
    enc = sum(1 for pi in pis if pi.flags & (lt.peer_info.rc4_encrypted | lt.peer_info.plaintext_encrypted))
    uploading_to_us = sum(1 for pi in pis if pi.down_speed > 0)
    t = time.time() - t0
    if first_peer is None and pis: first_peer = t
    if first_byte is None and st.total_payload_download > 0: first_byte = t
    if first_1MB is None and st.total_payload_download >= 1_000_000: first_1MB = t
    series.append({"t": round(t, 1), "kBps": round(st.download_payload_rate / 1000), "peers": st.num_peers, "seeds": st.num_seeds,
                   "list": st.list_peers, "cand": st.connect_candidates, "inbound": inbound, "enc": enc,
                   "sending_to_us": uploading_to_us, "bytes": st.total_payload_download, "dht": ev["dht_nodes"]})
trk = []
for tr in h.trackers():
    try:
        d = dict(tr) if not hasattr(tr, "url") else {"url": tr.url}
        eps = d.get("endpoints") or []
        trk.append({"url": d.get("url") or str(getattr(tr, "url", "?")), "fails": d.get("fails"),
                    "verified": d.get("verified"), "endpoints": [{k: (str(v) if not isinstance(v, (int, float, bool, type(None), str)) else v)
                                                              for k, v in e.items() if k in ("fails", "message", "last_error", "scrape_complete", "scrape_incomplete", "updating", "verified")} for e in eps][:2]})
    except Exception as e:
        trk.append({"repr": repr(tr)[:200], "err": str(e)})
rates = [x["kBps"] for x in series]
final = h.status()
summary = {
    "label": a.label, "torrent": a.torrent, "iface": a.iface or "default-route", "enc": a.enc, "seconds": a.seconds,
    "bytes": final.total_payload_download, "avg_MBps": round(final.total_payload_download / a.seconds / 1e6, 2),
    "peak_MBps": round(max(rates) / 1000, 2), "median_MBps": round(statistics.median(rates) / 1000, 2),
    "time_to_first_peer_s": first_peer, "time_to_first_byte_s": first_byte, "time_to_1MB_s": first_1MB,
    "peers_max": max(x["peers"] for x in series), "peers_median": statistics.median(x["peers"] for x in series),
    "seeds_max": max(x["seeds"] for x in series), "inbound_max": max(x["inbound"] for x in series),
    "encrypted_max": max(x["enc"] for x in series),
    "peers_sending_to_us_max": max(x["sending_to_us"] for x in series),
    "connections_opened": new_total, "connections_dropped": dropped_total,
    "connections_opened_per_min": round(new_total * 60 / a.seconds, 1),
    "dht_nodes_final": ev["dht_nodes"], "dht_bootstrap_alerts": ev["dht_bootstrap"],
    "trackers": trk, "tracker_replies": {k: v[:3] for k, v in ev["tracker_reply"].items()},
    "tracker_errors": {k: v[:2] for k, v in ev["tracker_error"].items()}, "listen": ev["listen"][:2], "listen_failed": ev["listen_failed"][:2],
    "hash_failed_pieces": None, "errors": ev["other_errors"][:2],
}
print(json.dumps(summary, indent=1, default=str))
if a.out:
    json.dump({"summary": summary, "series": series}, open(a.out, "w"), default=str)
sess.remove_torrent(h); time.sleep(0.5); del sess
shutil.rmtree(tmp, True)
