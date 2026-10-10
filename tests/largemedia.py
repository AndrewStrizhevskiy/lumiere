# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate ~25 GB synthetic-but-playable test videos (our own testsrc2/sine, no third-party content).

A 60 s CBR segment (~28 Mbit/s = 3.5 MB/s) is encoded once and stream-copied N times, so a file of ~2 h / ~25 GB exists
without 2 h of encoding. Outputs (in ~/.cache/lumiere-testmedia, outside the repo):
  big_cues_end.mkv   MKV, Cues at the end
  big_moov_front.mp4 MP4 with moov at the start (faststart)
  big_moov_end.mp4   MP4 with moov at the end
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path.home() / ".cache" / "lumiere-testmedia"
SEGMENTS = 119          # x 60 s
BITRATE_BPS = 3_500_000  # bytes/s, nominal


def ffmpeg(*args):
    t = time.time()
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)
    print(f"  ffmpeg {args[-1]} {time.time() - t:.0f}s", flush=True)


def ensure_large() -> dict[str, Path]:
    BASE.mkdir(parents=True, exist_ok=True)
    seg = BASE / "seg.mkv"
    if not seg.exists():
        ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
               "-t", "60", "-c:v", "libx264", "-preset", "ultrafast", "-b:v", "28M", "-minrate", "28M", "-maxrate", "28M",
               "-bufsize", "28M", "-x264-params", "nal-hrd=cbr", "-g", "50", "-c:a", "aac", "-b:a", "128k", str(seg) + ".tmp.mkv")
        os.replace(str(seg) + ".tmp.mkv", seg)
    lst = BASE / "list.txt"
    lst.write_text("".join(f"file '{seg}'\n" for _ in range(SEGMENTS)))
    out = {"big_cues_end": BASE / "big_cues_end.mkv", "big_moov_end": BASE / "big_moov_end.mp4",
           "big_moov_front": BASE / "big_moov_front.mp4"}
    if not out["big_cues_end"].exists():
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", str(out["big_cues_end"]) + ".tmp.mkv")
        os.replace(str(out["big_cues_end"]) + ".tmp.mkv", out["big_cues_end"])
    if not out["big_moov_end"].exists():
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", str(out["big_moov_end"]) + ".tmp.mp4")
        os.replace(str(out["big_moov_end"]) + ".tmp.mp4", out["big_moov_end"])
    if not out["big_moov_front"].exists():
        ffmpeg("-i", out["big_moov_end"], "-c", "copy", "-movflags", "+faststart", str(out["big_moov_front"]) + ".tmp.mp4")
        os.replace(str(out["big_moov_front"]) + ".tmp.mp4", out["big_moov_front"])
    return out


if __name__ == "__main__":
    for k, v in ensure_large().items():
        print(k, v, f"{v.stat().st_size / 2**30:.2f} GiB")
