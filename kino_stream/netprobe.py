# SPDX-License-Identifier: GPL-3.0-or-later
"""Small, read-only network probes (used by `kino-stream doctor --network`). They send a handful of tiny packets to
public DHT nodes / UDP trackers / DNS resolvers (the same hosts BitTorrent itself talks to) and report what came back.
Every result is a single 4-second sample: an observation, not proof of who is responsible."""
from __future__ import annotations

import json
import secrets
import socket
import struct
import subprocess
import time
import urllib.request

DHT_NODES = [("router.bittorrent.com", 6881), ("router.utorrent.com", 6881), ("dht.transmissionbt.com", 6881),
             ("dht.libtorrent.org", 25401)]
UDP_TRACKERS = [("tracker.opentrackr.org", 1337), ("explodie.org", 6969), ("tracker.leechers-paradise.org", 6969),
                ("open.demonii.com", 1337)]


def _udp(ip: str, port: int, payload: bytes, wait: float = 4.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(wait)
    try:
        s.sendto(payload, (ip, port))
        s.recvfrom(2048)
        return True
    except (socket.timeout, OSError):
        return False
    finally:
        s.close()


def _resolve(host: str):
    try:
        return socket.gethostbyname(host)
    except OSError:
        return None


def dns_udp(server: str = "1.1.1.1") -> bool:
    q = secrets.token_bytes(2) + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
    return _udp(server, 53, q)


def dht_replies() -> tuple[int, int]:
    ok = 0
    for host, port in DHT_NODES:
        ip = _resolve(host)
        if ip and _udp(ip, port, b"d1:ad2:id20:" + secrets.token_bytes(20) + b"e1:q4:ping1:t2:aa1:y1:qe"):
            ok += 1
    return ok, len(DHT_NODES)


def udp_tracker_replies() -> tuple[int, int]:
    ok = 0
    for host, port in UDP_TRACKERS:
        ip = _resolve(host)
        if ip and _udp(ip, port, struct.pack(">QII", 0x41727101980, 0, struct.unpack(">I", secrets.token_bytes(4))[0])):
            ok += 1
    return ok, len(UDP_TRACKERS)


def tcp_http_ports(ports=(6881, 51413)) -> dict[int, bool]:
    out = {}
    for p in ports:
        try:
            with urllib.request.urlopen(f"http://portquiz.net:{p}", timeout=6) as r:
                out[p] = r.status == 200
        except Exception:
            out[p] = False
    return out


def exit_info() -> dict:
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=8) as r:
            d = json.load(r)
        return {k: d.get(k) for k in ("ip", "org", "city", "country")}
    except Exception as e:
        return {"error": str(e)[:60]}


def https_speed_mbps(megabytes: int = 8) -> float | None:
    t = time.time()
    try:
        n = 0
        with urllib.request.urlopen(f"https://speed.cloudflare.com/__down?bytes={megabytes * 1000000}", timeout=20) as r:
            while True:
                c = r.read(1 << 16)
                if not c:
                    break
                n += len(c)
        return round(n / (time.time() - t) / 1e6, 2)
    except Exception:
        return None


def default_route_iface() -> str | None:
    try:
        out = subprocess.run(["ip", "-o", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=3).stdout
        parts = out.split()
        return parts[parts.index("dev") + 1] if "dev" in parts else None
    except Exception:
        return None
