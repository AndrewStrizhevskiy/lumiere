# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike 1: can a piece with priority 0 be downloaded because it has a deadline? Real libtorrent, local throttled swarm.

Variants (each repeated in fresh sessions to expose flakiness):
  V1 all pieces prio 0, nothing else wanted -> torrent reaches 'finished' state, set deadline, wait
  V2 same as V1 but call connect_peer() after setting the deadline
  V3 one 'anchor' piece kept wanted (prio 1) so the torrent is never 'finished'; deadline on other prio-0 pieces
  V4 control: all prio 0, no deadline (must download nothing)
"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import libtorrent as lt
from swarm import *

work = tempfile.mkdtemp(prefix="ks-spike1-")
src = os.path.join(work, "seed"); os.makedirs(src)
make_payload(os.path.join(src, "v.bin"), 64 * 2**20)
ti = make_torrent(src, "v.bin")
N = ti.num_pieces()
print(f"libtorrent {lt.__version__}; pieces={N} piece_length={ti.piece_length()}")
SEED_PORT = 47000
seed = new_session(SEED_PORT, upload_limit=4_000_000)
hs = add(seed, ti, src)
assert wait_until(lambda: hs.status().is_seeding, 20)
n_port = [47001]

def trial(variant, settle, **sess):
    leech = new_session(n_port[0], **sess); n_port[0] += 1
    d = tempfile.mkdtemp(dir=work)
    h = add(leech, ti, d)
    prios = [0] * N
    if variant == "V3":
        prios[0] = 1
    h.prioritize_pieces(prios)
    h.connect_peer(("127.0.0.1", SEED_PORT))
    time.sleep(settle)
    st0 = h.status()
    want = [100, 101, 102, 103]
    t0 = time.time()
    if variant != "V4":
        for k, i in enumerate(want):
            h.set_piece_deadline(i, 300 + 200 * k)
    if variant == "V2":
        h.connect_peer(("127.0.0.1", SEED_PORT))
    got = wait_until(lambda: all(h.have_piece(i) for i in want), 8)
    st = h.status()
    others = [i for i in range(N) if h.have_piece(i) and i not in want and not (variant == "V3" and i == 0)]
    prio = [h.piece_priority(i) for i in want]
    leech.remove_torrent(h)
    return (f"{variant} settle={settle}s state_before={st0.state} peers_before={st0.num_peers} -> deadlined pieces got={got} "
            f"in {time.time()-t0:.1f}s, prio_after={prio}, other pieces downloaded={len(others)}")

for variant in ("V4", "V1", "V2", "V3"):
    for settle in (0.3, 4):
        print(trial(variant, settle))
print("--- sweep: V1, how long may the torrent sit idle before a deadline stops working?")
for settle in (0.5, 1, 2, 3, 5):
    print(trial("V1", settle))
print("--- same with min_reconnect_time=0 and peer_turnover tweaks")
for settle in (0.5, 4):
    print(trial("V1", settle, min_reconnect_time=0))
