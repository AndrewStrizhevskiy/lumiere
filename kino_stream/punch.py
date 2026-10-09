# SPDX-License-Identifier: GPL-3.0-or-later
"""Hole punching (fallocate FALLOC_FL_PUNCH_HOLE) and allocated-space accounting.

Hole punching alone is NOT a safe way to evict from a live libtorrent torrent (it keeps advertising the piece and serves
zeros): it is only used here *while the torrent is removed from the session* (see bounded_store.py).
"""
from __future__ import annotations

import ctypes
import os
import tempfile
from pathlib import Path

_libc = ctypes.CDLL(None, use_errno=True)
FALLOC_FL_KEEP_SIZE = 1
FALLOC_FL_PUNCH_HOLE = 2


class PunchUnsupported(OSError):
    pass


def block_size(path: Path) -> int:
    return os.statvfs(path).f_frsize or 4096


def punch(path: Path | str, offset: int, length: int) -> None:
    fd = os.open(path, os.O_RDWR)
    try:
        if _libc.fallocate(fd, FALLOC_FL_KEEP_SIZE | FALLOC_FL_PUNCH_HOLE, ctypes.c_long(offset), ctypes.c_long(length)) != 0:
            e = ctypes.get_errno()
            if e in (95, 38, 22):                                   # EOPNOTSUPP, ENOSYS, EINVAL
                raise PunchUnsupported(e, f"filesystem does not support PUNCH_HOLE: {os.strerror(e)}")
            raise OSError(e, f"fallocate(PUNCH_HOLE) failed: {os.strerror(e)}")
    finally:
        os.close(fd)


def punch_inward(path: Path | str, start: int, end: int, block: int = 4096) -> int:
    """Release [start, end) of a file, shrunk *inward* to filesystem-block boundaries so that bytes outside the range
    (a neighbouring retained piece sharing a block) are never touched. Returns bytes actually released."""
    a = -(-start // block) * block
    b = end // block * block
    if b <= a:
        return 0
    punch(path, a, b - a)
    return b - a


def supports_punch(directory: Path) -> tuple[bool, str]:
    """Probe the filesystem under `directory` with a scratch file: write 3 blocks, punch the middle one, check that the
    allocation really dropped and the hole reads back as zeros. Never touches existing data."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    bs = block_size(directory)
    try:
        fd, name = tempfile.mkstemp(prefix=".kino-punch-probe-", dir=directory)
    except OSError as e:
        return False, f"cannot create a probe file in {directory}: {e}"
    try:
        os.write(fd, os.urandom(3 * bs))
        os.fsync(fd)
        os.close(fd)
        before = os.stat(name).st_blocks
        try:
            punch(name, bs, bs)
        except OSError as e:
            return False, str(e)
        st = os.stat(name)
        with open(name, "rb") as f:
            f.seek(bs)
            zeros = f.read(bs) == bytes(bs)
        if st.st_size != 3 * bs or not zeros:
            return False, "PUNCH_HOLE returned success but the hole did not read back as zeros"
        if st.st_blocks >= before:
            return False, "PUNCH_HOLE returned success but the allocation did not shrink (filesystem delays or ignores it)"
        return True, f"ok (block size {bs})"
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def allocated_bytes(root: Path | str) -> int:
    """Bytes really allocated under root (st_blocks * 512): sparse files, hidden part-files included."""
    total = 0
    for p in Path(root).rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_blocks * 512
        except OSError:
            pass
    return total
