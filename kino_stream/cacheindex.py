"""CacheIndex: the durable, authoritative record of which pieces are physically present, plus the eviction journal.

Rules (see docs/STAGE2_DESIGN.md):
  * libtorrent is ALWAYS started with have_pieces = index.retained; its own resume data is never trusted for `have`.
  * a piece is added to `retained` only after its bytes were fdatasync'ed;
  * an eviction is journalled (txn) before anything destructive happens; from then on recovery rolls FORWARD;
  * a piece leaves `retained` before libtorrent is started again, so libtorrent can neither advertise nor serve it.
All writes are atomic: temp file + fsync + rename + directory fsync.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

VERSION = 1


class SimulatedCrash(BaseException):
    """Raised by test hooks to emulate the process dying at a precise point (BaseException: nothing may swallow it)."""


class CacheIndex:
    def __init__(self, path: Path, infohash: str, num_pieces: int, piece_length: int):
        self.path = Path(path)
        self.infohash, self.num_pieces, self.piece_length = infohash, num_pieces, piece_length
        self.retained = bytearray(num_pieces)
        self.txn: dict | None = None
        self.epoch = 0
        self.loaded_from_disk = False
        self.corrupt = False
        # One lock for every mutation and every save: a save running in a worker thread must never observe a half-applied
        # change (e.g. txn 'punched' but retained not yet cleared would persist a claim on punched pieces) and two saves
        # must never share a temp file.
        self._lock = threading.RLock()

    # ---------------------------------------------------------------------------------------- persistence
    @classmethod
    def load(cls, path: Path, infohash: str, num_pieces: int, piece_length: int) -> "CacheIndex":
        idx = cls(path, infohash, num_pieces, piece_length)
        if not Path(path).exists():
            return idx
        try:
            d = json.loads(Path(path).read_text())
            if (d.get("version") != VERSION or d.get("infohash") != infohash or d.get("num_pieces") != num_pieces
                    or d.get("piece_length") != piece_length):
                raise ValueError("index belongs to a different torrent / version")
            bits = bytes.fromhex(d["retained"])
            if len(bits) != num_pieces:
                raise ValueError("bitmap size mismatch")
            idx.retained = bytearray(bits)
            idx.txn = d.get("txn")
            idx.epoch = int(d.get("epoch", 0))
            idx.loaded_from_disk = True
        except Exception:
            idx.retained = bytearray(num_pieces)            # cannot trust anything: retain nothing (re-download)
            idx.txn = None
            idx.corrupt = True
        return idx

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        self.epoch += 1
        d = {"version": VERSION, "infohash": self.infohash, "num_pieces": self.num_pieces,
             "piece_length": self.piece_length, "epoch": self.epoch, "retained": bytes(self.retained).hex(), "txn": self.txn}
        tmp = self.path.with_name(self.path.name + ".tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(d, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        dfd = os.open(self.path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)

    # ------------------------------------------------------------------------------------------ queries
    def is_retained(self, p: int) -> bool:
        return bool(self.retained[p])

    def retained_set(self) -> set[int]:
        return {i for i, b in enumerate(self.retained) if b}

    def as_bool_list(self) -> list[bool]:
        return [bool(b) for b in self.retained]

    # --------------------------------------------------------------------------------------- mutations
    def add_retained(self, pieces) -> None:
        with self._lock:
            for p in pieces:
                self.retained[p] = 1

    def begin_txn(self, evict: list[int]) -> str:
        """Journal the eviction. After this returns (durably), recovery rolls forward."""
        with self._lock:
            if self.txn is not None:
                raise RuntimeError("a transaction is already open")
            tid = uuid.uuid4().hex[:12]
            self.txn = {"id": tid, "evict": sorted(evict), "state": "begin"}
            self._save_locked()
            return tid

    def mark_punched(self) -> None:
        """Pieces leave `retained` BEFORE libtorrent is started again."""
        with self._lock:
            assert self.txn is not None
            for p in self.txn["evict"]:
                self.retained[p] = 0
            self.txn["state"] = "punched"
            self._save_locked()

    def abort_txn(self) -> None:
        """Only legal before anything destructive happened."""
        with self._lock:
            self.txn = None
            self._save_locked()

    def commit(self) -> None:
        with self._lock:
            self.txn = None
            self._save_locked()
