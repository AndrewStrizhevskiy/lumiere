#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Network diagnostics (read-only, per-process; changes nothing on the system).

    python3 diag/net_diag.py [--iface wlan0] [--out diag/net_diag_<label>.json] [--label home]

Measures, for the default route AND (if --iface is given) for that interface bypassing any VPN (SO_BINDTODEVICE):
exit IP/ISP, TCP connect + TLS + first-byte latency, ICMP loss/jitter (meaningless through a TUN VPN that answers locally),
and repeated HTTPS downloads (Cloudflare speed endpoint and the Blender Sintel mp4 that is also a public torrent).
"""
import argparse, json, re, statistics, subprocess, sys, time


def sh(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip(), r.returncode


def curl_json(url, iface=None, maxtime=15):
    base = ["curl", "-s", "-m", str(maxtime)] + (["--interface", iface] if iface else [])
    out, rc = sh(base + [url])
    try:
        return json.loads(out)
    except Exception:
        return {"error": f"rc={rc} {out[:80]}"}


def timing(url, iface=None, n=5):
    fmt = "%{time_namelookup} %{time_connect} %{time_appconnect} %{time_starttransfer} %{http_code}"
    rows = []
    for _ in range(n):
        out, rc = sh(["curl", "-s", "-o", "/dev/null", "-m", "15", "-w", fmt] + (["--interface", iface] if iface else []) + [url])
        try:
            dns, con, tls, ttfb, code = out.split()
            rows.append((float(dns), float(con), float(tls), float(ttfb), code))
        except Exception:
            rows.append(None)
    ok = [r for r in rows if r]
    if not ok:
        return {"failed": n}
    return {"ok": len(ok), "failed": n - len(ok),
            "tcp_connect_ms": round(1000 * statistics.median(r[1] - r[0] for r in ok)),
            "tls_ms": round(1000 * statistics.median(r[2] - r[1] for r in ok)),
            "ttfb_ms": round(1000 * statistics.median(r[3] - r[2] for r in ok)),
            "ttfb_max_ms": round(1000 * max(r[3] - r[2] for r in ok))}


def download(url, iface=None, seconds=20):
    out, rc = sh(["curl", "-s", "-o", "/dev/null", "-m", str(seconds), "-w", "%{speed_download} %{size_download} %{time_total} %{http_code}"]
                 + (["--interface", iface] if iface else []) + [url], timeout=seconds + 30)
    try:
        sp, sz, tt, code = out.split()
        return {"MBps": round(float(sp) / 1e6, 2), "bytes": int(float(sz)), "seconds": round(float(tt), 1), "http": code}
    except Exception:
        return {"error": f"rc={rc} {out[:60]}"}


def ping(host, iface=None, count=60):
    out, rc = sh(["ping"] + (["-I", iface] if iface else []) + ["-c", str(count), "-i", "0.2", "-q", host], timeout=count + 30)
    m = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    r = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)", out)
    return {"loss_pct": float(m.group(1)) if m else None,
            "rtt_min_avg_max_mdev_ms": [float(x) for x in r.groups()] if r else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iface")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out")
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    res = {"label": a.label, "time": time.strftime("%F %T")}
    gw, _ = sh(["sh", "-c", "ip route | awk '/^default/ {print $3; exit}'"])
    res["default_gateway"] = gw
    paths = {"default_route": None}
    if a.iface:
        paths["direct_" + a.iface] = a.iface
    res["gateway_ping"] = ping(gw, None, 30) if gw else None
    for name, iface in paths.items():
        r = {}
        info = curl_json("https://ipinfo.io/json", iface)
        r["exit"] = {k: info.get(k) for k in ("ip", "org", "city", "country", "error")}
        r["icmp_1.1.1.1"] = ping("1.1.1.1", iface)
        r["icmp_8.8.8.8"] = ping("8.8.8.8", iface)
        r["latency_https"] = {h: timing(f"https://{h}/", iface) for h in ("www.cloudflare.com", "webtorrent.io", "github.com")}
        r["https_cloudflare_25MB_MBps"] = [download("https://speed.cloudflare.com/__down?bytes=25000000", iface, 25) for _ in range(a.runs)]
        r["https_sintel_mp4_20s_MBps"] = [download("https://webtorrent.io/torrents/Sintel/Sintel.mp4", iface, 20) for _ in range(a.runs)]
        res[name] = r
        print(json.dumps({name: r}, indent=1), flush=True)
    if a.out:
        json.dump(res, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
