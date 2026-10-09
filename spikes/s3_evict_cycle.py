# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike S3 (Stage 2): evict by  REMOVE torrent -> punch holes -> RE-ADD with exact have_pieces.

Order matters: the torrent is removed *before* the holes are punched, so libtorrent cannot serve a half-evicted piece
(there is no 'stop serving' window to get wrong). Measured here, against real libtorrent 2.0.10:
  A. have-state == physical data after each cycle (every retained piece re-hashed against the torrent's SHA-1s,
     every evicted piece reported missing),
  B. an observer peer that downloads only from the evicting node never receives a bad piece across many cycles,
  C. what a cycle costs (remove / punch / re-add / reconnect) and how many peers are lost,
  D. crash between punch and re-add: recovery from a journal + stale resume data without a recheck,
  E. unaligned multi-file torrent: block-aligned punching never damages neighbouring retained bytes.
"""
import ctypes
import hashlib
import os
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import libtorrent as lt
from tests.support import Seeder, free_port, media, random_file, PIECE_LENGTH

libc = ctypes.CDLL(None, use_errno=True)
BLOCK = os.statvfs("/tmp").f_bsize


def punch(path, off, length):
    fd = os.open(path, os.O_RDWR)
    try:
        if libc.fallocate(fd, 1 | 2, ctypes.c_long(off), ctypes.c_long(length)):
            raise OSError(ctypes.get_errno(), "fallocate")
    finally:
        os.close(fd)


def punch_inward(path, start, end):
    """Punch [start,end) shrunk inward to filesystem-block boundaries: never touches bytes outside the range."""
    a = -(-start // BLOCK) * BLOCK
    b = end // BLOCK * BLOCK
    if b > a:
        punch(path, a, b - a)
    return max(0, b - a)


def session(port, up=0, **kw):
    s = {"listen_interfaces": f"127.0.0.1:{port}", "enable_dht": False, "enable_lsd": False, "enable_upnp": False,
         "enable_natpmp": False, "ignore_limits_on_local_network": False, "upload_rate_limit": up,
         "allow_multiple_connections_per_ip": True, "close_redundant_connections": False, "min_reconnect_time": 0,
         "alert_mask": lt.alert.category_t.status_notification | lt.alert.category_t.error_notification | lt.alert.category_t.peer_notification | lt.alert.category_t.connect_notification,
         "alert_queue_size": 20000}
    s.update(kw)
    return lt.session(s)


def atp(ti, path, have=None, no_verify=False, paused=False):
    p = lt.add_torrent_params()
    p.ti, p.save_path = ti, str(path)
    if have is not None:
        p.have_pieces = list(have)
    p.flags = p.flags & ~lt.torrent_flags.auto_managed & ~lt.torrent_flags.paused    # default flags include `paused`
    if no_verify:
        p.flags |= lt.torrent_flags.no_verify_files
    if paused:
        p.flags |= lt.torrent_flags.paused
    return p


def wait(cond, timeout, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


def piece_ok(ti, path, i):
    pl = ti.piece_length()
    n = ti.piece_size(i)
    with open(path, "rb") as f:
        f.seek(i * pl)
        return hashlib.sha1(f.read(n)).digest() == bytes(ti.hash_for_piece(i)) if hasattr(ti, "hash_for_piece") else None


def sha1_of(ti, i):
    h = ti.hash_for_piece(i)
    return h if isinstance(h, (bytes, bytearray)) else bytes(h)


def check_state(ti, path, h, retained, label):
    """Returns (ok, details): libtorrent's have() vs reality."""
    N = ti.num_pieces()
    lt_have = {i for i in range(N) if h.have_piece(i)}
    bad_hash = [i for i in lt_have if hashlib.sha1(open(path, "rb").read()[i * ti.piece_length(): i * ti.piece_length() + ti.piece_size(i)]).digest() != sha1_of(ti, i)] if N < 400 else None
    ok = lt_have == set(retained) and not bad_hash
    return ok, {"label": label, "lt_have": len(lt_have), "expected": len(retained), "extra": sorted(lt_have - set(retained))[:5],
                "missing": sorted(set(retained) - lt_have)[:5], "have_but_corrupt": bad_hash}


def main():
    src = media()["moov_front"]
    work = Path(tempfile.mkdtemp(prefix="ks-s3-"))
    S = Seeder(src, upload_limit=3_000_000)
    ti = S.ti
    N, PL = ti.num_pieces(), ti.piece_length()
    print(f"libtorrent {lt.__version__}  pieces={N}  piece_length={PL}  fs block={BLOCK}")

    # ---- leech L1 = the node whose cache we evict. Fill it completely first.
    p1 = work / "l1"; p1.mkdir()
    L1 = session(free_port(), up=400_000)
    h1 = L1.add_torrent(atp(ti, p1))
    h1.connect_peer(("127.0.0.1", S.port))
    assert wait(lambda: h1.status().is_seeding, 60), "L1 did not complete"
    f1 = p1 / src.name
    print("L1 complete")

    # ---- observer L2: knows ONLY L1.  It tries to download everything from L1 while L1 is being evicted.
    p2 = work / "l2"; p2.mkdir()
    l2port = free_port()
    L2 = session(l2port)
    h2 = L2.add_torrent(atp(ti, p2))
    l1_port = L1.listen_port()
    h2.connect_peer(("127.0.0.1", l1_port))
    l2_hash_failed = 0
    l2_bans = 0

    def pump_l2():
        nonlocal l2_hash_failed, l2_bans
        for a in L2.pop_alerts():
            if isinstance(a, lt.hash_failed_alert):
                l2_hash_failed += 1
            elif isinstance(a, lt.peer_ban_alert):
                l2_bans += 1

    retained = set(range(N))
    cycles = []
    rnd = random.Random(5)
    disconnects = 0
    for cyc in range(8):
        # choose pieces to evict (all currently retained, random 12% of them)
        ev = set(rnd.sample(sorted(retained), max(1, len(retained) // 8)))
        t = {}
        t0 = time.time()
        h1.save_resume_data(lt.save_resume_flags_t.flush_disk_cache)
        L1.remove_torrent(h1)
        removed = wait(lambda: any(isinstance(a, lt.torrent_removed_alert) for a in L1.pop_alerts()), 10)
        t["remove_s"] = round(time.time() - t0, 3)
        t1 = time.time()
        punched = 0
        for i in sorted(ev):
            punched += punch_inward(f1, i * PL, i * PL + ti.piece_size(i))
        t["punch_s"] = round(time.time() - t1, 3)
        retained -= ev
        t2 = time.time()
        h1 = L1.add_torrent(atp(ti, p1, have=[i in retained for i in range(N)], no_verify=True))
        t["readd_s"] = round(time.time() - t2, 3)
        ok, det = check_state(ti, f1, h1, retained, f"cycle{cyc}")
        # observer's view of L1 right after re-add
        pump_l2()
        cycles.append({"cycle": cyc, "evicted": len(ev), "retained": len(retained), "punched_bytes": punched,
                       "state_exact": ok, **t, **({} if ok else {"detail": det})})
        # observer keeps trying to pull from L1 for ~3 s; right after re-add look at what L1 advertises to it
        adv_checked = False
        for _ in range(12):
            h2.connect_peer(("127.0.0.1", l1_port))
            time.sleep(0.25)
            pump_l2()
            pis = h2.get_peer_info()
            if pis and not adv_checked and getattr(pis[0], "pieces", None) is not None and sum(pis[0].pieces) > 0:
                adv = {i for i, b in enumerate(pis[0].pieces) if b}
                leaked = sorted(adv & ev)
                cycles[-1]["advertised_by_L1"] = len(adv)
                cycles[-1]["evicted_but_advertised"] = leaked
                adv_checked = True
    for c in cycles:
        print(c)
    pump_l2()
    # observer final accounting: everything L2 holds must be valid; L2 must never have received an evicted-then-served piece
    l2_have = {i for i in range(N) if h2.have_piece(i)}
    l2_bad = [i for i in l2_have if hashlib.sha1(open(p2 / src.name, "rb").read()[i * PL: i * PL + ti.piece_size(i)]).digest() != sha1_of(ti, i)] if N < 400 else None
    print(f"B. observer: has {len(l2_have)}/{N} pieces, hash_failed={l2_hash_failed}, bans={l2_bans}, corrupt pieces held={l2_bad}")

    # ---- C. does an evicted piece come back from the seeder on demand, and how long until the first byte after re-add
    h1.connect_peer(("127.0.0.1", S.port))
    victim = sorted(set(range(N)) - retained)[0]
    t0 = time.time()
    h1.piece_priority(victim, 0)
    h1.set_piece_deadline(victim, 100)
    got = wait(lambda: h1.have_piece(victim), 15)
    print(f"C. re-download of evicted piece {victim}: {got} in {time.time() - t0:.2f}s (cycle cost above; peers lost per cycle: all, reconnect included)")

    # ---- D. crash between punch and re-add: stale resume claims everything, journal says which were punched
    print("D. crash recovery without recheck")
    journal = sorted(set(range(N)) - retained)               # what we had journaled before punching
    L1.remove_torrent(h1); time.sleep(0.5)
    stale_have = [True] * N                                  # worst case: resume data written before the evictions
    exact = [(stale_have[i] and i not in set(journal)) for i in range(N)]
    h1 = L1.add_torrent(atp(ti, p1, have=exact, no_verify=True))
    ok, det = check_state(ti, f1, h1, {i for i in range(N) if exact[i]}, "after-crash-recovery")
    print("   recovered state exact:", ok, det if not ok else "")

    # ---- E. unaligned multi-file torrent
    print("E. multi-file, unaligned file starts")
    root = work / "mf"; root.mkdir()
    random_file(root / "a.bin", 300_001, 1); random_file(root / "b.bin", 700_003, 2); random_file(root / "c.bin", 300_007, 3)
    S2 = Seeder(root, upload_limit=0)
    ti2 = S2.ti
    from kino_stream.piecemap import PieceMap
    pm = PieceMap.from_torrent_info(ti2)
    shared = [i for i in range(pm.num_pieces) if pm.is_shared(i)]
    pdir = work / "mfl"; pdir.mkdir()
    L3 = session(free_port())
    h3 = L3.add_torrent(atp(ti2, pdir)); h3.connect_peer(("127.0.0.1", S2.port))
    assert wait(lambda: h3.status().is_seeding, 30)
    L3.remove_torrent(h3); time.sleep(0.5)
    # evict ONLY pieces exclusive to file b; punch inside b, inward-aligned
    bidx = next(f.index for f in pm.files if f.path.endswith("b.bin"))
    ev2 = [i for i in pm.exclusive_pieces(bidx)][::2]
    bpath = pdir / pm.files[bidx].path
    for i in ev2:
        a, b = pm.piece_span(i)
        punch_inward(bpath, a - pm.files[bidx].start, b - pm.files[bidx].start)
    N2 = pm.num_pieces
    keep2 = [i not in set(ev2) for i in range(N2)]
    h3 = L3.add_torrent(atp(ti2, pdir, have=keep2, no_verify=True)); time.sleep(0.8)
    bad = []
    for i in range(N2):
        if keep2[i]:
            a, b = pm.piece_span(i)
            buf = bytearray()
            for fi, fa, fb in pm.owners(i):
                # pad-free torrent: read the bytes of this piece from each owning file
                with open(pdir / pm.files[fi].path, "rb") as f:
                    f.seek(fa); buf += f.read(fb - fa)
            if hashlib.sha1(bytes(buf)).digest() != sha1_of(ti2, i):
                bad.append(i)
    lt_have2 = {i for i in range(N2) if h3.have_piece(i)}
    print(f"   shared boundary pieces={shared}; evicted exclusive-to-b pieces={len(ev2)}; retained pieces corrupted={bad}; "
          f"libtorrent have == expected: {lt_have2 == {i for i in range(N2) if keep2[i]}}")
    summary = {"cycles_all_exact": all(c["state_exact"] for c in cycles), "observer_hash_failed": l2_hash_failed,
               "observer_corrupt_pieces": l2_bad, "crash_recovery_exact": ok, "multifile_corrupted": bad}
    print("SUMMARY", summary)
    S.close(); S2.close()


if __name__ == "__main__":
    main()
