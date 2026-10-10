#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Kill the whole lumiere process group (SIGKILL) at random moments while a 6 MiB cache is evicting, N times, then
recover once and verify integrity. Reports how many kills landed inside an open eviction transaction."""
import hashlib, json, os, random, shutil, signal, socket, subprocess, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import libtorrent as lt
from lumiere.cacheindex import CacheIndex
from lumiere.piecemap import PieceMap
from lumiere.punch import allocated_bytes
from tests.support import Seeder, free_port, media

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
src = media()["moov_front"]
sd = Seeder(src, upload_limit=1_500_000); ti = sd.ti
tmp = Path(tempfile.mkdtemp(prefix="ks-killstorm-"))
tor = tmp / "t.torrent"; tor.write_bytes(lt.bencode(lt.create_torrent(ti).generate()))
dl, state = tmp / "dl", tmp / "state"
def cmd(quit_after):
    return [sys.executable, "-m", "lumiere", "play", str(tor), "--peer", f"127.0.0.1:{sd.port}", "--save-path", str(dl), "--state-dir", str(state),
            "--no-dht", "--listen", f"127.0.0.1:{free_port()}", "--headless", "--cache-limit-mb", "6", "--cache-back-mb", "1", "--mpv-cache-mb", "1",
            "--min-readahead-mib", "1", "--readahead-s", "8", "--status-interval", "0", "--quit-after", str(quit_after), "--verify-source", str(src)]
pm = PieceMap.from_torrent_info(ti); rnd = random.Random(42)
open_txn = {"begin": 0, "punched": 0}; none = 0; over = 0
for i in range(N):
    ipc = tmp / f"mpv{i}.sock"
    p = subprocess.Popen(cmd(300) + ["--ipc-socket", str(ipc)], stdout=open(tmp / f"run{i}.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < 4: time.sleep(0.2)                 # let it start, then jump around to force downloads + evictions
    for _ in range(3):
        try:
            c = socket.socket(socket.AF_UNIX); c.settimeout(2); c.connect(str(ipc))
            c.sendall((json.dumps({"command": ["seek", rnd.uniform(5, 110), "absolute"]}) + "\n").encode()); c.close()
        except OSError: pass
        time.sleep(rnd.uniform(1.0, 3.5))
    time.sleep(rnd.uniform(0.2, 4))
    os.killpg(os.getpgid(p.pid), signal.SIGKILL); p.wait()
    idx_files = list(state.glob("*.cache.json"))
    if idx_files:
        idx = CacheIndex.load(idx_files[0], str(ti.info_hash()), pm.num_pieces, pm.piece_length)
        if idx.txn: open_txn[idx.txn["state"]] += 1
        else: none += 1
    print(f"kill {i+1}/{N}: txn={'-' if not idx_files or not idx.txn else idx.txn['state']} allocated={allocated_bytes(dl)/1e6:.2f} MB", flush=True)
p = subprocess.run(cmd(14), capture_output=True, text=True, timeout=120)
s = json.loads([l for l in p.stdout.splitlines() if l.startswith("SUMMARY ")][-1][8:])
idx = CacheIndex.load(next(state.glob("*.cache.json")), str(ti.info_hash()), pm.num_pieces, pm.piece_length)
bad = 0
with open(dl / pm.files[0].path, "rb") as f:
    for q in idx.retained_set():
        a, b = pm.piece_span(q); f.seek(a)
        bad += hashlib.sha1(f.read(b - a)).digest() != bytes(ti.hash_for_piece(q))
print(json.dumps({"kills": N, "killed_with_open_txn": open_txn, "killed_outside_txn": none, "recovery_rc": p.returncode,
                  "recovery_allocated_MB": round(s["allocated_bytes"]/1e6, 2), "limit_MB": 6.29, "mismatches": s["http_mismatches"],
                  "retained_after": len(idx.retained_set()), "corrupt_retained_pieces": bad, "txn_left_open": idx.txn is not None}))
print("--- seeder state: peers", sd.handle.status().num_peers, "list_peers", sd.handle.status().list_peers, "uploads", sd.handle.status().num_uploads)
fresh = lt.session({"listen_interfaces": "127.0.0.1:0", "enable_dht": False, "enable_lsd": False, "enable_upnp": False, "enable_natpmp": False, "alert_mask": 0, "allow_multiple_connections_per_ip": True})
fp = lt.add_torrent_params(); fp.ti = ti; fp.save_path = tempfile.mkdtemp(); fp.flags = fp.flags & ~lt.torrent_flags.auto_managed & ~lt.torrent_flags.paused
fh = fresh.add_torrent(fp); fh.connect_peer(("127.0.0.1", sd.port)); time.sleep(3)
print("--- a FRESH plain leech connecting to the same seeder: peers =", fh.status().num_peers, "(seeder peers now", sd.handle.status().num_peers, ")")
print("--- one more life, verbose:"); v = subprocess.run([a for a in cmd(15) if a != "0"][:cmd(15).index("--status-interval")+1] + ["2"] + cmd(15)[cmd(15).index("--status-interval")+2:], capture_output=True, text=True, timeout=120); print(v.stdout[-1800:], v.stderr[-1500:])
import glob; [print("--", f, open(f).read()[-500:].replace(chr(10), " | ")) for f in sorted(glob.glob(str(tmp / "run*.log")))[-4:]]; sd.close(); shutil.rmtree(tmp, True)
