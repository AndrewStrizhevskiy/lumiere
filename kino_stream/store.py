"""PieceStore: the only thing the scheduler and the HTTP server know about storage.

Deliberately does NOT promise that a piece, once present, stays present: `read()` may raise PieceUnavailable even
after `have()` returned True, and implementations announce losses with a "lost" event. Stage 1's
PersistentFileStore never loses pieces; a future BoundedSparseStore will.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .piecemap import PieceMap


class PieceUnavailable(Exception):
    """Some of the pieces needed for a read are not (or no longer) available."""

    def __init__(self, pieces):
        super().__init__(f"pieces not available: {sorted(pieces)[:8]}")
        self.pieces = list(pieces)


class PieceTimeout(Exception):
    def __init__(self, pieces):
        super().__init__(f"timed out waiting for pieces {sorted(pieces)[:8]}")
        self.pieces = list(pieces)


class StoreError(Exception):
    """Unrecoverable storage / torrent error."""


class CacheUnsupportedError(StoreError):
    """The filesystem cannot release disk blocks (no PUNCH_HOLE): a bounded cache is not possible there."""


class CacheDirNotManagedError(StoreError):
    """The cache directory holds data that no cache index describes: refused, never adopted or touched."""


class CacheTooSmallError(ValueError):
    """The configured limit cannot hold the retention window, pinned container data and a minimal read-ahead."""


@dataclass
class Demand:
    """What the scheduler wants right now. Applied wholesale: anything not listed is no longer wanted."""
    deadlines: dict[int, int] = field(default_factory=dict)   # piece -> deadline in ms (smaller = more urgent)
    wanted: set[int] = field(default_factory=set)             # read-ahead pieces, no deadline
    pinned: set[int] = field(default_factory=set)             # container head/tail pieces, no deadline

    def all_pieces(self) -> set[int]:
        return set(self.deadlines) | self.wanted | self.pinned

    def key(self):
        return (tuple(sorted(self.deadlines.items())), tuple(sorted(self.wanted)), tuple(sorted(self.pinned)))


@dataclass
class RetentionHint:
    """What the scheduler wants to keep on disk (used by bounded stores; ignored by unbounded ones)."""
    head_piece: int = 0
    keep_lo: int = 0           # first piece of the retention window (behind the head, for backward seeks)
    keep_hi: int = 0           # last piece of the read-ahead window
    pinned: set[int] = field(default_factory=set)


Listener = Callable[[str, object], None]    # (event, payload): "have"|"lost"|"hash_failed"|"error"


class PieceStore(abc.ABC):
    piece_map: PieceMap

    @abc.abstractmethod
    def have(self, piece: int) -> bool: ...

    def missing(self, pieces: Iterable[int]) -> list[int]:
        return [p for p in pieces if not self.have(p)]

    @abc.abstractmethod
    async def wait_have(self, pieces: Iterable[int], timeout: float) -> None:
        """Return when every piece is present; raise PieceTimeout otherwise. Must be cancellable."""

    @abc.abstractmethod
    def read(self, file_index: int, offset: int, length: int) -> bytes:
        """Bytes of one file. Raises PieceUnavailable rather than ever returning missing/zero data."""

    @abc.abstractmethod
    def apply_demand(self, demand: Demand, force: Iterable[int] = ()) -> None:
        """Replace the current demand. `force` re-asserts deadlines of these pieces even if unchanged."""

    @abc.abstractmethod
    def wake(self, reason: str = "") -> None:
        """Make sure the swarm is being worked: reconnect peers, re-announce, resume if idle."""

    def retain(self, hint: "RetentionHint") -> None:        # optional: bounded stores use it to choose eviction victims
        return None

    @abc.abstractmethod
    def add_listener(self, cb: Listener) -> None: ...

    @abc.abstractmethod
    def stats(self) -> dict: ...

    @abc.abstractmethod
    async def close(self) -> None: ...
