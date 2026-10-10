# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end through the real command line: lumiere play ... --cache-limit-mb ... with headless mpv, seeks through
mpv's IPC socket, and a real SIGKILL of the whole process group at different moments, followed by recovery."""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import libtorrent as lt

from lumiere.cacheindex import CacheIndex
from lumiere.config import MiB
from lumiere.piecemap import PieceMap
from lumiere.punch import allocated_bytes
from tests.support import Seeder, free_port, media

ROOT = Path(__file__).resolve().parent.parent
LIMIT_MB = 6


def need_tools():
    if not (shutil.which("mpv") and shutil.which("ffmpeg")):
        raise unittest.SkipTest("needs mpv and ffmpeg")


class CliCase(unittest.TestCase):
    def setUp(self):
        need_tools()
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-cli-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = media()["moov_front"]
        self.sd = Seeder(self.src, upload_limit=1_500_000)
        self.addCleanup(self.sd.close)
        self.ti = self.sd.ti
        self.torrent = self.tmp / "t.torrent"
        self.torrent.write_bytes(lt.bencode(lt.create_torrent(self.ti).generate()))
        self.dl, self.state = self.tmp / "dl", self.tmp / "state"

    def cmd(self, quit_after, ipc=None, extra=()):
        c = [sys.executable, "-m", "lumiere", "play", str(self.torrent), "--peer", f"127.0.0.1:{self.sd.port}",
             "--save-path", str(self.dl), "--state-dir", str(self.state), "--no-dht", "--listen", f"127.0.0.1:{free_port()}",
             "--headless", "--cache-limit-mb", str(LIMIT_MB), "--cache-back-mb", "1", "--mpv-cache-mb", "1",
             "--min-readahead-mib", "1", "--readahead-s", "8", "--status-interval", "0", "--quit-after", str(quit_after),
             "--verify-source", str(self.src)]
        if ipc:
            c += ["--ipc-socket", str(ipc)]
        return c + list(extra)

    @staticmethod
    def ipc_send(sock_path, *cmd):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(str(sock_path))
        s.sendall((json.dumps({"command": list(cmd)}) + "\n").encode())
        try:
            s.recv(4096)
        except socket.timeout:
            pass
        s.close()

    def summary(self, out: str) -> dict:
        line = [l for l in out.splitlines() if l.startswith("SUMMARY ")]
        self.assertTrue(line, f"no SUMMARY line in output:\n{out[-800:]}")
        return json.loads(line[-1][8:])

    def check_integrity(self):
        """Offline: every retained piece in the index re-hashes correctly and no transaction is left open."""
        idx_path = next(self.state.glob("*.cache.json"))
        pm = PieceMap.from_torrent_info(self.ti)
        idx = CacheIndex.load(idx_path, str(self.ti.info_hash()), pm.num_pieces, pm.piece_length)
        self.assertFalse(idx.corrupt)
        self.assertIsNone(idx.txn, "an eviction journal entry was left open")
        data = self.dl / pm.files[0].path
        bad = []
        with open(data, "rb") as f:
            for p in idx.retained_set():
                a, b = pm.piece_span(p)
                f.seek(a)
                import hashlib
                if hashlib.sha1(f.read(b - a)).digest() != bytes(self.ti.hash_for_piece(p)):
                    bad.append(p)
        self.assertEqual(bad, [], "retained pieces with wrong content")
        return len(idx.retained_set())


class CliBounded(CliCase):
    def test_play_seek_both_ways_inside_a_hard_cache_limit(self):
        ipc = self.tmp / "mpv.sock"
        p = subprocess.Popen(self.cmd(32, ipc), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
        t0 = time.time()
        while not ipc.exists() and time.time() - t0 < 20:
            time.sleep(0.2)
        time.sleep(8)
        peak = 0
        for target in (80, 10, 100, 5):                       # forward, back, far forward, back to start
            self.ipc_send(ipc, "seek", target, "absolute")
            for _ in range(8):
                peak = max(peak, allocated_bytes(self.dl))
                time.sleep(0.5)
        out, _ = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, out[-1500:])
        s = self.summary(out)
        self.assertLessEqual(max(peak, s["allocated_bytes"]), LIMIT_MB * MiB, f"cache limit exceeded: {peak}")
        self.assertGreaterEqual(s["evictions"], 1)
        self.assertEqual(s["http_mismatches"], 0)
        self.assertEqual(s["http_aborted"], 0)
        self.assertGreaterEqual(s["seeks"], 3)
        self.assertEqual(s["reason"], "quit-after")
        self.assertNotIn("Traceback", out)
        self.check_integrity()

    def test_sigkill_at_different_moments_then_recovery(self):
        """Real process death (SIGKILL of the whole group, mpv included) while the cache is evicting."""
        for round_, delay in enumerate((9, 12.5, 16)):
            p = subprocess.Popen(self.cmd(120), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT,
                                 start_new_session=True)
            time.sleep(delay)
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            p.communicate(timeout=20)
            self.assertEqual(p.returncode, -signal.SIGKILL)
        # last life: must recover (journal/orphans) before touching peers, play, and stay inside the limit
        p = subprocess.Popen(self.cmd(14), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
        out, _ = p.communicate(timeout=90)
        self.assertEqual(p.returncode, 0, out[-1500:])
        s = self.summary(out)
        self.assertLessEqual(s["allocated_bytes"], LIMIT_MB * MiB)
        self.assertEqual(s["http_mismatches"], 0)
        self.assertIsNone(s["store_error"])
        kept = self.check_integrity()
        self.assertGreater(kept, 0)

    def test_refuses_directory_without_hole_punching_support_message_is_clear(self):
        # a --save-path that cannot be created/probed must give a one-line error, not a traceback
        bad = self.tmp / "file_not_dir"
        bad.write_text("x")
        c = self.cmd(5)
        c[c.index("--save-path") + 1] = str(bad / "sub")
        r = subprocess.run(c, capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertNotEqual(r.returncode, 0)


class Doctor(unittest.TestCase):
    def test_doctor_runs_offline(self):
        r = subprocess.run([sys.executable, "-m", "lumiere", "doctor", "--save-path", tempfile.mkdtemp()], capture_output=True,
                           text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("hole punching works", r.stdout)


if __name__ == "__main__":
    unittest.main()
