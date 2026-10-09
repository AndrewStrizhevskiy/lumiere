"""Torrent geometry: absolute torrent offsets <-> pieces <-> files.

A torrent is one byte string made of the files laid out back to back; pieces cut that string into equal chunks
(the last one is shorter). A piece may therefore contain the end of file A and the start of file B. `owners()`
reports that explicitly so no layer treats a piece as belonging to one file only.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass


@dataclass(frozen=True)
class FileSpan:
    index: int
    start: int        # absolute offset of the file's first byte inside the torrent
    size: int
    path: str         # relative to the save path
    pad: bool = False  # BEP 47 padding file: zeros, never real data

    @property
    def end(self) -> int:     # exclusive
        return self.start + self.size


class PieceMap:
    def __init__(self, piece_length: int, total_size: int, files: list[FileSpan]):
        if piece_length <= 0:
            raise ValueError("piece_length must be positive")
        self.piece_length = piece_length
        self.total_size = total_size
        self.files = files
        self.num_pieces = -(-total_size // piece_length)
        self._starts = [f.start for f in files]

    # --- construction ---------------------------------------------------------------------
    @classmethod
    def from_torrent_info(cls, ti) -> "PieceMap":
        import libtorrent as lt
        fs = ti.files()
        files = [FileSpan(i, fs.file_offset(i), fs.file_size(i), fs.file_path(i),
                          bool(fs.file_flags(i) & lt.file_storage.flag_pad_file)) for i in range(fs.num_files())]
        return cls(ti.piece_length(), ti.total_size(), files)

    # --- pieces ---------------------------------------------------------------------------
    def piece_size(self, piece: int) -> int:
        self._check_piece(piece)
        if piece == self.num_pieces - 1:
            return self.total_size - piece * self.piece_length
        return self.piece_length

    def piece_span(self, piece: int) -> tuple[int, int]:
        """Absolute [start, end) of a piece."""
        a = piece * self.piece_length
        return a, a + self.piece_size(piece)

    def range_pieces(self, file_index: int, first: int, last: int) -> range:
        """Pieces that must be present to read file bytes [first, last] (inclusive). Whole pieces, shared ones too."""
        f = self.files[file_index]
        if first < 0 or last < first or last >= f.size:
            raise ValueError(f"range {first}-{last} outside file of {f.size} bytes")
        return range((f.start + first) // self.piece_length, (f.start + last) // self.piece_length + 1)

    def owners(self, piece: int) -> list[tuple[int, int, int]]:
        """[(file_index, start_in_file, end_in_file_exclusive)] for every real (non-pad) file with bytes in this piece."""
        a, b = self.piece_span(piece)
        out = []
        i = max(bisect.bisect_right(self._starts, a) - 1, 0)
        while i < len(self.files) and self.files[i].start < b:
            f = self.files[i]
            lo, hi = max(a, f.start), min(b, f.end)
            if hi > lo and not f.pad:          # padding files carry no data, so they do not make a piece 'shared'
                out.append((f.index, lo - f.start, hi - f.start))
            i += 1
        return out

    def is_shared(self, piece: int) -> bool:
        return len(self.owners(piece)) > 1

    def shared_with(self, piece: int, file_index: int) -> list[int]:
        return [i for i, _, _ in self.owners(piece) if i != file_index]

    def exclusive_pieces(self, file_index: int) -> range:
        """Pieces lying entirely inside one file: the only ones a cache may drop without affecting other files."""
        f = self.files[file_index]
        if f.size == 0:
            return range(0)
        lo = -(-f.start // self.piece_length)
        hi = f.end // self.piece_length
        if f.end == self.total_size:
            hi = self.num_pieces
        return range(lo, max(lo, hi))

    def _check_piece(self, piece: int) -> None:
        if not 0 <= piece < self.num_pieces:
            raise IndexError(f"piece {piece} out of range 0..{self.num_pieces - 1}")
