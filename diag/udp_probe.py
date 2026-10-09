#!/usr/bin/env python3
"""Raw protocol probes, direct interface vs default route. Read-only; sockets live for a few seconds.
Answers: does UDP work? do DHT bootstrap nodes answer a BEP 5 ping? does a UDP tracker answer a BEP 15 connect request?
Do BitTorrent TCP handshakes to real peers complete / get reset?"""
import os, socket, struct, sys, time, json, secrets

IFACE = sys.argv[1] if len(sys.argv) > 1 else None


def sock(kind, bind_dev):
    s = socket.socket(socket.AF_INET, kind)
    if bind_dev:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, bind_dev.encode())
    s.settimeout(4)
    return s


def resolve(host):
    try:
        return socket.gethostbyname(host)
    except Exception as e:
        return None


def udp_exchange(dev, ip, port, payload, wait=4):
    s = sock(socket.SOCK_DGRAM, dev)
    t = time.time()
    try:
        s.sendto(payload, (ip, port))
        data, _ = s.recvfrom(2048)
        return {"reply_bytes": len(data), "rtt_ms": round((time.time() - t) * 1000)}
    except socket.timeout:
        return {"reply": None, "timeout_s": wait}
    except OSError as e:
        return {"error": str(e)}
    finally:
        s.close()


def dns_query(dev, server):
    q = secrets.token_bytes(2) + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + b"\x07example\x03com\x00\x00\x01\x00\x01"
    return udp_exchange(dev, server, 53, q)


def dht_ping(dev, host, port):
    ip = resolve(host)
    if not ip:
        return {"dns": "unresolved"}
    msg = b"d1:ad2:id20:" + secrets.token_bytes(20) + b"e1:q4:ping1:t2:aa1:y1:qe"
    r = udp_exchange(dev, ip, port, msg)
    r["ip"] = ip
    return r


def udp_tracker(dev, host, port):
    ip = resolve(host)
    if not ip:
        return {"dns": "unresolved"}
    tid = struct.unpack(">I", secrets.token_bytes(4))[0]
    msg = struct.pack(">QII", 0x41727101980, 0, tid)
    r = udp_exchange(dev, ip, port, msg)
    r["ip"] = ip
    return r


def tcp_connect(dev, ip, port):
    s = sock(socket.SOCK_STREAM, dev)
    t = time.time()
    try:
        s.connect((ip, port))
        return {"connected_ms": round((time.time() - t) * 1000)}
    except Exception as e:
        return {"error": type(e).__name__ + ": " + str(e)[:50], "after_ms": round((time.time() - t) * 1000)}
    finally:
        s.close()


def bt_handshake(dev, ip, port, ih):
    """BitTorrent handshake over TCP: does the peer answer, or is the connection reset/dropped?"""
    s = sock(socket.SOCK_STREAM, dev)
    t = time.time()
    try:
        s.connect((ip, port))
        s.sendall(b"\x13BitTorrent protocol" + b"\x00" * 8 + ih + secrets.token_bytes(20))
        data = s.recv(68)
        return {"handshake_reply_bytes": len(data), "ms": round((time.time() - t) * 1000), "proto_ok": data[:20] == b"\x13BitTorrent protocol"}
    except Exception as e:
        return {"error": type(e).__name__ + ": " + str(e)[:50], "after_ms": round((time.time() - t) * 1000)}
    finally:
        s.close()


def run(label, dev, peers, ih):
    out = {"dns_udp_1.1.1.1": dns_query(dev, "1.1.1.1"), "dns_udp_8.8.8.8": dns_query(dev, "8.8.8.8")}
    for host, port in (("router.bittorrent.com", 6881), ("router.utorrent.com", 6881), ("dht.transmissionbt.com", 6881), ("dht.libtorrent.org", 25401)):
        out[f"dht_ping {host}"] = dht_ping(dev, host, port)
    for host, port in (("tracker.opentrackr.org", 1337), ("explodie.org", 6969), ("tracker.leechers-paradise.org", 6969), ("open.demonii.com", 1337)):
        out[f"udp_tracker {host}:{port}"] = udp_tracker(dev, host, port)
    hs = {}
    for ip, port in peers:
        hs[f"{ip}:{port}"] = bt_handshake(dev, ip, port, ih)
    out["bt_tcp_handshakes"] = hs
    out["tcp_443_cloudflare"] = tcp_connect(dev, "1.1.1.1", 443)
    return {label: out}


if __name__ == "__main__":
    peers = [tuple(p.split(":")) for p in (sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[2] else [])]
    peers = [(ip, int(pt)) for ip, pt in peers]
    ih = bytes.fromhex("08ada5a7a6183aae1e09d831df6748d566095a10")      # Sintel (public CC torrent)
    res = {}
    res.update(run("default_route", None, peers, ih))
    if IFACE:
        res.update(run("direct_" + IFACE, IFACE, peers, ih))
    print(json.dumps(res, indent=1))
