#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Release configuration. The repository ships with placeholders that must be replaced before publishing; this tool replaces them and checks that none are left.

    python3 tools/release_config.py check                       # exit 1 while any placeholder remains (also run by .githooks/pre-push)
    python3 tools/release_config.py apply --repo OWNER/NAME [--security-email ADDR] [--conduct-email ADDR]

Placeholders: @@GITHUB_REPO@@ (owner/name), and, only if a file still contains them, @@SECURITY_EMAIL@@ and @@CONDUCT_EMAIL@@. Nothing is guessed: `apply` refuses (and writes nothing) if any
placeholder would be left without a value. The shipped SECURITY.md / CODE_OF_CONDUCT.md use GitHub's private reporting and need no email address.
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
        if p.suffix in (".png", ".svg") or f in ("tools/release_config.py", "tests/test_release_config.py"):
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
    a.add_argument("--security-email")
    a.add_argument("--conduct-email")
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
        if e is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
            sys.exit(f"not an email address: {e}")
    values = {TOKENS["repo"]: args.repo}
    if args.security_email:
        values[TOKENS["security_email"]] = args.security_email
    if args.conduct_email:
        values[TOKENS["conduct_email"]] = args.conduct_email
    changed, unfilled = {}, []
    for f, t in tracked_text_files():
        u = t
        for k, v in values.items():
            u = u.replace(k, v)
        unfilled += [(f, m) for m in sorted(set(PATTERN.findall(u)))]
        if u != t:
            changed[f] = u
    if unfilled:                                                    # never guess, never half-apply
        sys.exit("refusing to apply: no value for " + ", ".join(f"{m} (in {f})" for f, m in unfilled))
    for f, u in changed.items():
        (ROOT / f).write_text(u, encoding="utf-8")
    print(f"updated {len(changed)} files; review `git diff` before committing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
