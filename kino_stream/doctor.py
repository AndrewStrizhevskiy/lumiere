"""`kino-stream doctor`: read-only checks with an explicit separation of CONFIRMED observations and HYPOTHESES."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import netprobe
from .punch import supports_punch

OK, WARN, BAD = "ok  ", "WARN", "FAIL"


def _line(tag: str, text: str) -> None:
    print(f"[{tag}] {text}")


def run_doctor(save_path: Path, network: bool) -> int:
    bad = 0
    print("== local setup (nothing is changed, nothing leaves this machine)")
    try:
        import libtorrent as lt
        _line(OK, f"python-libtorrent {lt.__version__}")
    except Exception as e:
        _line(BAD, f"python-libtorrent missing: {e}  (sudo apt install python3-libtorrent)")
        return 1
    for tool in ("mpv",):
        path = shutil.which(tool)
        if path:
            v = subprocess.run([tool, "--version"], capture_output=True, text=True).stdout.splitlines()[:1]
            _line(OK, f"{tool}: {v[0] if v else path}")
        else:
            _line(BAD, f"{tool} not found (sudo apt install {tool})")
            bad += 1
    sp = Path(save_path).expanduser()
    ok, why = supports_punch(sp)
    if ok:
        _line(OK, f"{sp}: hole punching works ({why}) -> --cache-limit-gb is available here")
    else:
        _line(WARN, f"{sp}: hole punching NOT available: {why} -> run without --cache-limit-gb or use another directory")
    free = shutil.disk_usage(sp).free
    _line(OK if free > 2 << 30 else WARN, f"free space at {sp}: {free / 2**30:.1f} GiB")
    crash = Path.home() / ".local/state/kino-stream/crash.log"
    if crash.exists() and crash.stat().st_size:
        _line(WARN, f"{crash} is not empty: a native crash was recorded - send its tail when reporting a bug")
    iface = netprobe.default_route_iface()
    if iface:
        vpnish = iface.startswith(("tun", "wg", "vpn", "tap", "ppp", "utun"))
        _line(WARN if vpnish else OK, f"default route goes through '{iface}'" + (" - looks like a VPN/tunnel (observation: all BitTorrent traffic is tunnelled)" if vpnish else ""))
    if not network:
        print("\n(run with --network for DHT / UDP-tracker / DNS-over-UDP / exit-IP checks; they contact public hosts)")
        return 1 if bad else 0

    print("\n== network probes (single 4 s samples, public DHT nodes / trackers / resolvers)")
    info = netprobe.exit_info()
    _line(OK, f"exit address as seen by the internet: {info}")
    dns = netprobe.dns_udp()
    dht, dht_n = netprobe.dht_replies()
    trk, trk_n = netprobe.udp_tracker_replies()
    tcp = netprobe.tcp_http_ports()
    speed = netprobe.https_speed_mbps()
    _line(OK if dns else WARN, f"DNS over UDP to 1.1.1.1: {'answered' if dns else 'NO answer'}")
    _line(OK if dht else WARN, f"DHT bootstrap nodes answering: {dht}/{dht_n}")
    _line(OK if trk else WARN, f"UDP trackers answering: {trk}/{trk_n}")
    _line(OK if all(tcp.values()) else WARN, f"TCP to arbitrary BitTorrent ports (portquiz.net): {tcp}")
    _line(OK if speed else WARN, f"single-stream HTTPS download: {speed} MB/s" if speed else "single-stream HTTPS download failed")

    print("\n== interpretation")
    if not dns:
        print("CONFIRMED (this path, this moment): outbound UDP to public resolvers gets no answer -> UDP is filtered or the tunnel drops it.")
        print("  Consequence: DHT and UDP trackers cannot work. Use a .torrent file with trackers over TCP/HTTP or --peer hints; magnet links need DHT.")
    elif dht == 0 and trk == 0:
        print("CONFIRMED (this path, this moment): UDP DNS works but DHT and UDP-tracker packets get no answer.")
        print("  HYPOTHESIS (not provable from here): protocol-specific filtering by the network or the VPN. Try --encryption forced, another")
        print("  network, or a different VPN exit; magnets will not resolve without DHT, .torrent files + --peer still can.")
    elif dht == 0 or trk == 0:
        print("OBSERVED: partial UDP reachability (some DHT nodes / trackers answer, some do not). Public nodes also go offline, so this alone")
        print("  is not evidence of filtering.")
    else:
        print("No UDP restriction observed in this sample.")
    if not all(tcp.values()):
        print("OBSERVED: some arbitrary TCP ports are not reachable (port-based blocking is possible; confirm with another port/host).")
    else:
        print("CONFIRMED: no port-based TCP blocking for the ports tried.")
    print("NOT MEASURED: bandwidth throttling by the ISP; whether peers can connect to you (no inbound test is performed).")
    return 1 if bad else 0


def network_report(include_speed: bool = False) -> dict:
    """Structured network probes. Every verdict is tagged: confirmed (measured now on this path), observed (partial/ambiguous),
    hypothesis (cannot be proven from here), not_measured. Never claims throttling by an ISP."""
    info = netprobe.exit_info()
    dns = netprobe.dns_udp()
    dht, dht_n = netprobe.dht_replies()
    trk, trk_n = netprobe.udp_tracker_replies()
    tcp = netprobe.tcp_http_ports()
    speed = netprobe.https_speed_mbps() if include_speed else None
    iface = netprobe.default_route_iface()
    verdicts: list[tuple[str, str]] = []
    if not dns:
        verdicts.append(("confirmed", "udp_dropped"))
    elif dht == 0 and trk == 0:
        verdicts.append(("confirmed", "udp_bittorrent_no_answer"))
        verdicts.append(("hypothesis", "protocol_filtering_possible"))
    elif dht == 0 or trk == 0:
        verdicts.append(("observed", "udp_partial"))
    else:
        verdicts.append(("observed", "udp_ok"))
    if not all(tcp.values()):
        verdicts.append(("observed", "tcp_ports_unreachable"))
    else:
        verdicts.append(("confirmed", "no_tcp_port_blocking"))
    if iface and iface.startswith(("tun", "wg", "vpn", "tap", "ppp", "utun")):
        verdicts.append(("observed", "vpn_in_path"))
    verdicts.append(("not_measured", "isp_throttling"))
    verdicts.append(("not_measured", "inbound_reachability"))
    return {"exit": info, "dns_udp": dns, "dht": [dht, dht_n], "udp_trackers": [trk, trk_n], "tcp_ports": tcp,
            "https_MBps": speed, "default_iface": iface, "verdicts": verdicts}
