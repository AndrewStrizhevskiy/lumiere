#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does libtorrent's Python binding crash when alerts are read with wait_for_alert() from a second thread?

    python3 diag/alert_stress.py wait|tpoll|poll SECONDS

Same workload for both modes: 3 loopback seeders + 1 leecher, 128 MiB file in 16 KiB pieces, ALL alert categories on
(thousands of alerts/s, so the alert queue keeps growing/re-allocating while the reader runs).
  wait : a Python thread loops   a = ses.wait_for_alert(20); ses.pop_alerts()      (what lumiere used to do)
  poll : the main thread loops   ses.pop_alerts(); sleep(0.02)                       (what it does now)
Exit status -11 = SIGSEGV."""
import os, random, shutil, sys, tempfile, threading, time
import libtorrent as lt

mode, seconds = sys.argv[1], float(sys.argv[2])
work = tempfile.mkdtemp(prefix="ks-alertstress-")
src = os.path.join(work, "seed"); os.makedirs(src)
path = os.path.join(src, "big.bin")
r = random.Random(1)
with open(path, "wb") as f:
    for _ in range(128):
        f.write(r.randbytes(1 << 20))
fs = lt.file_storage(); lt.add_files(fs, path)
ct = lt.create_torrent(fs, 16 * 1024, flags=lt.create_torrent.v1_only); lt.set_piece_hashes(ct, src)
ti = lt.torrent_info(lt.bencode(ct.generate()))

def sess(port, mask):
    return lt.session({"listen_interfaces": f"127.0.0.1:{port}", "enable_dht": False, "enable_lsd": False, "enable_upnp": False,
                       "enable_natpmp": False, "allow_multiple_connections_per_ip": True, "alert_mask": mask, "alert_queue_size": 500000,
                       "upload_rate_limit": 0, "download_rate_limit": 0})
seeders = []
for i in range(3):
    s = sess(0, 0); p = lt.add_torrent_params(); p.ti = ti; p.save_path = src; p.flags |= lt.torrent_flags.seed_mode
    seeders.append((s, s.add_torrent(p)))
time.sleep(1.5)
leech = sess(0, int(lt.alert.category_t.all_categories))
dl = os.path.join(work, "dl"); os.makedirs(dl)
p = lt.add_torrent_params(); p.ti = ti; p.save_path = dl; p.flags = p.flags & ~lt.torrent_flags.auto_managed & ~lt.torrent_flags.paused
h = leech.add_torrent(p)
for s, _ in seeders:
    h.connect_peer(("127.0.0.1", s.listen_port()))
stop = threading.Event(); count = [0]

def waiter():
    while not stop.is_set():
        a = leech.wait_for_alert(20)              # <- returns a pointer into the live alert queue
        if a is not None:
            a.what()
        count[0] += len(leech.pop_alerts())

def tpoller():
    while not stop.is_set():
        count[0] += len(leech.pop_alerts())            # pop_alerts() only, but from a second thread
        time.sleep(0.02)

if mode == "wait":
    t = threading.Thread(target=waiter); t.start()
elif mode == "tpoll":
    t = threading.Thread(target=tpoller); t.start()
t0 = time.time()
while time.time() - t0 < seconds:
    if mode == "poll":
        count[0] += len(leech.pop_alerts())
    time.sleep(0.02)
    if h.status().is_seeding:                      # keep the storm going: restart the download when finished
        leech.remove_torrent(h); time.sleep(0.2)
        shutil.rmtree(dl, True); os.makedirs(dl)
        p = lt.add_torrent_params(); p.ti = ti; p.save_path = dl; p.flags = p.flags & ~lt.torrent_flags.auto_managed & ~lt.torrent_flags.paused
        h = leech.add_torrent(p)
        for s, _ in seeders:
            h.connect_peer(("127.0.0.1", s.listen_port()))
stop.set()
if mode in ("wait", "tpoll"):
    t.join()
print(f"{mode}: survived {seconds:.0f}s, alerts processed {count[0]}", flush=True)
shutil.rmtree(work, True)
