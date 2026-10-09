# Network findings (anonymized)

These are the findings from the network diagnosis done while developing Kino Stream, with provider names, addresses and other identifying details removed. They are
**observations from one developer's machine on three kinds of network, a few runs each**, not statistics and not statements about any provider. The tools that produced them are
in `diag/` (`net_diag.py`, `udp_probe.py`, `bt_bench.py`); raw result files are intentionally not published. `kino-stream doctor --network` repeats the read-only probes.

The measurements were read-only: nothing persistent (routes, firewall, VPN, router) was changed, UPnP/NAT-PMP was never enabled, and web seeds were off in all BitTorrent runs.

## Setups compared
* **VPN path:** a system-wide TUN VPN was active, so the default route left through a hosted exit abroad. ICMP/TCP-connect timings through a TUN device are answered locally
  (≈0.1–0.3 ms) and **are not network measurements**.
* **Direct path A:** a phone hotspot on a mobile carrier (measured by binding to the Wi-Fi interface, without changing routes).
* **Direct path B:** a university Wi-Fi network (same method).

## Findings
1. **Plain HTTPS** worked on every path (single stream 25 MB: 1.5–1.8 MB/s on the VPN path at night to 6–13 MB/s elsewhere), except that one HTTPS test server was
   unreachable on path A directly (3 of 3 attempts, other sites fine) and capped at a constant ≈2.2 MB/s on path B directly.
2. **BitTorrent on path A directly:** 0 peers, 0 DHT nodes, 0 bytes — also with encryption forced or disabled and with known-good peers supplied. Over the VPN path the same
   torrent worked, but with **high variance (0.14–3.2 MB/s across runs on the same path)**. BitTorrent was not consistently slower than HTTP; it was consistently more variable.
3. **Path B directly:** outbound UDP to the internet was dropped (even DNS to public resolvers), so DHT and UDP trackers cannot work there; TCP BitTorrent handshakes succeeded for
   8 of 14 peers directly versus 11 of 14 over the VPN. Forcing protocol encryption doubled the single throughput sample (n=1, **not conclusive**).
4. **Ports:** TCP to arbitrary ports (6881, 6969, 51413, …) was open on both direct paths: no port-based TCP blocking was seen.
5. **Path A looked like protocol-specific filtering:** UDP DNS worked, but all DHT bootstrap pings and all UDP-tracker connects went unanswered, and TCP connects to peers succeeded while
   the BitTorrent handshake was never answered (0/14 direct versus 10/14 via the VPN), even obfuscated. The evidence does **not** say whether the carrier or the hotspot phone is responsible.
6. **Inbound connections:** 0 in every run (carrier/campus NAT plus the VPN exit): only peers we dial are reachable.
7. **Not shown:** ISP bandwidth throttling. No evidence either way beyond the filtering above. Kino Stream therefore never states throttling as a fact.
8. UDP is unreliable on every path tried (blocked, filtered, or patchy through the tunnel; UDP trackers show *unreachable* in libtorrent).

## What follows for users
* Prefer `.torrent` files (TCP/HTTP trackers) over magnet links, which depend on DHT/UDP.
* On networks that filter BitTorrent, try *Hide traffic from your network → Always on* (forced protocol encryption) and peer hints (`--peer` in the CLI); results vary.
* Expect long cold starts and 0–3 MB/s when everything goes through one VPN tunnel with many short connections and no inbound reachability.
* To separate "tunnel" from "network", measure once on a clean home line with the `diag/` tools.
* The native crash found in the same period was **not** caused by any of this; it was a use-after-free in the Python binding's `wait_for_alert()` (see KNOWN_ISSUES.md §1).

`diag/net_diag.py` asks a public service (`ipinfo.io`) for your exit address; run it only if you are comfortable with that. Its output files contain your addresses — do not publish them.
