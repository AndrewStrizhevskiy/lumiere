#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release configuration. The repository ships with placeholders that must be replaced before publishing; this tool replaces them and checks that none are left.

    python3 tools/release_config.py check                       # exit 1 while any placeholder remains (also run by .githooks/pre-push)
    python3 tools/release_config.py apply --repo OWNER/NAME --security-email ADDR --conduct-email ADDR

Placeholders: @@GITHUB_REPO@@ (owner/name), @@SECURITY_EMAIL@@, @@CONDUCT_EMAIL@@. Nothing is guessed: `apply` needs every value explicitly.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = {"repo": "@@GITHUB_REPO@@", "security_email": "@@SECURITY_EMAIL@@", "conduct_email": "@@CONDUCT_EMAIL@@"}
PATTERN = re.compile(r"@@[A-Z_]+@@")


def tracked_text_files():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for f in out:
        p = ROOT / f
        if p.suffix in (".png", ".svg") or f == "tools/release_config.py":
            continue
        try:
            yield f, p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def remaining():
    return [(f, m) for f, t in tracked_text_files() for m in sorted(set(PATTERN.findall(t)))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    a = sub.add_parser("apply")
    a.add_argument("--repo", required=True, help="GitHub owner/name")
    a.add_argument("--security-email", required=True)
    a.add_argument("--conduct-email", required=True)
    args = ap.parse_args()
    if args.cmd == "check":
        left = remaining()
        for f, tok in left:
            print(f"unfilled placeholder {tok} in {f}", file=sys.stderr)
        if not (ROOT / "LICENSE").exists():
            print("LICENSE is missing", file=sys.stderr)
            return 1
        if left:
            print("not publishable yet: run `python3 tools/release_config.py apply ...`", file=sys.stderr)
            return 1
        print("release configuration complete")
        return 0
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        sys.exit("--repo must look like owner/name")
    for e in (args.security_email, args.conduct_email):
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
            sys.exit(f"not an email address: {e}")
    values = {TOKENS["repo"]: args.repo, TOKENS["security_email"]: args.security_email, TOKENS["conduct_email"]: args.conduct_email}
    n = 0
    for f, t in tracked_text_files():
        u = t
        for k, v in values.items():
            u = u.replace(k, v)
        if u != t:
            (ROOT / f).write_text(u, encoding="utf-8")
            n += 1
    print(f"updated {n} files; review `git diff` before committing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
