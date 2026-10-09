# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike 2: how can libtorrent 'forget' a completed piece?  clear_piece() is absent from this binding (see s0_api.py),
so we measure what a hole-punched (evicted) piece looks like to libtorrent, to peers, after recheck, after resume, after re-add.
"""
import os, sys, tempfile, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libtorrent as lt
from swarm import *

libc = ctypes.CDLL(None, use_errno=True)
def punch(path, off, length):
    fd = os.open(path, os.O_RDWR)
    try:
        r = libc.fallocate(fd, 1 | 2, ctypes.c_long(off), ctypes.c_long(length))  # KEEP_SIZE|PUNCH_HOLE
        if r: raise OSError(ctypes.get_errno(), "fallocate")
    finally:
        os.close(fd)

PL = 256 * 1024
work = tempfile.mkdtemp(prefix="ks-spike2-")
src = os.path.join(work, "seed"); os.makedirs(src)
make_payload(os.path.join(src, "v.bin"), 64 * 2**20)
ti = make_torrent(src, "v.bin"); N = ti.num_pieces()
orig_sha = sha(os.path.join(src, "v.bin"))
EV = list(range(50, 60))            # the 10 pieces we "evict"
print(f"libtorrent {lt.__version__}, N={N}, evicting pieces {EV[0]}..{EV[-1]}")

seed = new_session(47100, upload_limit=8_000_000)
hs = add(seed, ti, src); wait_until(lambda: hs.status().is_seeding, 20)

L1 = new_session(47101); d1 = os.path.join(work, "l1"); os.makedirs(d1)
h1 = add(L1, ti, d1); h1.connect_peer(("127.0.0.1", 47100))
assert wait_until(lambda: h1.status().is_seeding, 60), "leech1 did not finish"
f1 = os.path.join(d1, "v.bin")
print("leech1 complete, sha matches source:", sha(f1) == orig_sha)
seed.remove_torrent(hs); del seed; time.sleep(0.5)       # from now on leech1 is the only holder

# --- punch holes ---------------------------------------------------------------------------------
st_before = os.stat(f1)
punch(f1, EV[0] * PL, len(EV) * PL)
st_after = os.stat(f1)
print(f"\n[punch] size {st_before.st_size}->{st_after.st_size}, allocated {st_before.st_blocks*512//2**20}MiB->{st_after.st_blocks*512//2**20}MiB, mtime changed: {st_before.st_mtime_ns != st_after.st_mtime_ns}")

# E1. what does libtorrent believe?
print("[E1] have_piece for evicted pieces:", [h1.have_piece(i) for i in EV[:3]], "... status.pieces says:", all(h1.status(lt.torrent_handle.query_pieces).pieces[i] for i in EV))
h1.read_piece(EV[0]); time.sleep(0.5)
for a in L1.pop_alerts():
    if isinstance(a, lt.read_piece_alert) and a.piece == EV[0]:
        buf = bytes(a.buffer) if a.buffer is not None else b""
        print(f"     read_piece({EV[0]}) -> {len(buf)} bytes, all zero: {buf == bytes(len(buf))}, error: {a.error.message() if a.error else None}")

# E2. does leech1 advertise/serve the evicted pieces to another peer?
L2 = new_session(47102); d2 = os.path.join(work, "l2"); os.makedirs(d2)
h2 = add(L2, ti, d2); h2.connect_peer(("127.0.0.1", 47101))
hashfail = set(); bans = 0; t0 = time.time()
while time.time() - t0 < 25:
    for a in L2.pop_alerts():
        if isinstance(a, lt.hash_failed_alert): hashfail.add(a.piece_index)
        if isinstance(a, lt.peer_ban_alert): bans += 1
    if h2.status().is_seeding: break
    time.sleep(0.2)
s2 = h2.status()
print(f"[E2] leecher2 downloading ONLY from leech1: have {s2.num_pieces}/{N}; hash_failed pieces: {sorted(hashfail)}; peer_ban alerts: {bans}; leech1 sent zero-pieces silently: {bool(hashfail)}")
L2.remove_torrent(h2); del L2

# E5a. resume data written while stale
h1.save_resume_data(lt.save_resume_flags_t.flush_disk_cache); time.sleep(0.5)
rd = None
for a in L1.pop_alerts():
    if isinstance(a, lt.save_resume_data_alert): rd = a.params
have_in_resume = [i for i, b in enumerate(rd.have_pieces) if b] if rd else None
print(f"[E5a] resume data written after punch claims have for evicted pieces: {all(i in have_in_resume for i in EV)} ({len(have_in_resume)}/{N} pieces)")

# E3. recheck
t0 = time.time(); h1.force_recheck()
wait_until(lambda: h1.status().state not in (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data), 60)
time.sleep(0.5)
print(f"[E3] after force_recheck ({time.time()-t0:.1f}s for a 64MiB torrent): have evicted -> {[h1.have_piece(i) for i in EV[:3]]}...; total have {h1.status().num_pieces}/{N}; other pieces intact: {all(h1.have_piece(i) for i in range(N) if i not in EV)}")

# E4. re-download evicted pieces (seeder returns), request them via deadline with prio 0 elsewhere
seed2 = new_session(47103, upload_limit=8_000_000); hs2 = add(seed2, ti, src); wait_until(lambda: hs2.status().is_seeding, 20)
h1.connect_peer(("127.0.0.1", 47103))
for i in EV: h1.set_piece_deadline(i, 500)
ok = wait_until(lambda: all(h1.have_piece(i) for i in EV), 30)
print(f"[E4] evicted pieces re-downloaded after recheck: {ok}; file sha matches source: {sha(f1) == orig_sha}")

# E5b. alternative to recheck: remove + re-add with a crafted have_pieces (no hashing of the rest)
punch(f1, EV[0] * PL, len(EV) * PL)
L1.remove_torrent(h1); time.sleep(0.5)
p = lt.add_torrent_params(); p.ti = ti; p.save_path = d1
p.have_pieces = [i not in EV for i in range(N)]
p.flags |= lt.torrent_flags.no_verify_files
t0 = time.time(); h3 = L1.add_torrent(p); time.sleep(1.5)
st = h3.status()
print(f"[E5b] re-add with crafted have_pieces (no_verify_files): state={st.state}, have {st.num_pieces}/{N}, evicted reported missing: {not any(h3.have_piece(i) for i in EV)}, others present: {all(h3.have_piece(i) for i in range(N) if i not in EV)} ({time.time()-t0:.1f}s)")
h3.connect_peer(("127.0.0.1", 47103))
for i in EV: h3.set_piece_deadline(i, 500)
ok = wait_until(lambda: all(h3.have_piece(i) for i in EV), 30)
print(f"     re-downloaded evicted pieces: {ok}; file sha matches source: {sha(f1) == orig_sha}")
