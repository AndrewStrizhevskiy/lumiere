# SPDX-License-Identifier: GPL-3.0-or-later
import os
import tempfile
import unittest
from pathlib import Path

import libtorrent as lt

from kino_stream.piecemap import FileSpan, PieceMap
from tests.support import PIECE_LENGTH, Seeder, random_file


class PieceMapMath(unittest.TestCase):
    def setUp(self):
        # three files 250 + 500 + 250 bytes, pieces of 100: pieces 2 and 7 each straddle two files
        self.pm = PieceMap(100, 1000, [FileSpan(0, 0, 250, "a"), FileSpan(1, 250, 500, "b"), FileSpan(2, 750, 250, "c")])

    def test_range_pieces_whole_pieces(self):
        self.assertEqual(list(self.pm.range_pieces(1, 0, 0)), [2])             # first byte of b lives in shared piece 2
        self.assertEqual(list(self.pm.range_pieces(1, 0, 499)), list(range(2, 8)))
        self.assertEqual(list(self.pm.range_pieces(0, 0, 249)), [0, 1, 2])

    def test_ownership_across_file_boundary(self):
        self.assertEqual(self.pm.owners(2), [(0, 200, 250), (1, 0, 50)])
        self.assertEqual(self.pm.owners(7), [(1, 450, 500), (2, 0, 50)])
        self.assertEqual(self.pm.owners(4), [(1, 150, 250)])
        self.assertTrue(self.pm.is_shared(2))
        self.assertFalse(self.pm.is_shared(4))
        self.assertEqual(self.pm.shared_with(2, 1), [0])

    def test_exclusive_pieces_exclude_shared_ones(self):
        self.assertEqual(list(self.pm.exclusive_pieces(1)), [3, 4, 5, 6])      # 2 and 7 are shared with a / c
        self.assertEqual(list(self.pm.exclusive_pieces(0)), [0, 1])
        self.assertEqual(list(self.pm.exclusive_pieces(2)), [8, 9])

    def test_last_piece_short(self):
        pm = PieceMap(100, 950, [FileSpan(0, 0, 950, "x")])
        self.assertEqual(pm.num_pieces, 10)
        self.assertEqual(pm.piece_size(9), 50)
        self.assertEqual(pm.piece_span(9), (900, 950))

    def test_bad_ranges(self):
        with self.assertRaises(ValueError):
            self.pm.range_pieces(0, 0, 250)
        with self.assertRaises(IndexError):
            self.pm.piece_size(10)

    def test_every_byte_belongs_to_exactly_the_right_pieces(self):
        for fi, f in enumerate(self.pm.files):
            for off in range(0, f.size, 7):
                p = (f.start + off) // 100
                self.assertIn(p, self.pm.range_pieces(fi, off, off))
                self.assertIn((fi, ), [(o[0],) for o in self.pm.owners(p)])


class AgainstLibtorrent(unittest.TestCase):
    def test_matches_torrent_info_map_file_on_multifile_torrent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "t"
            root.mkdir()
            random_file(root / "0_prefix.bin", 100_003, 1)
            random_file(root / "1_movie.bin", 1_000_001, 2)
            random_file(root / "2_tail.bin", 70_000, 3)
            sd = Seeder(root)                        # v1-only, unaligned: files share boundary pieces
            try:
                ti = sd.ti
                pm = PieceMap.from_torrent_info(ti)
                self.assertEqual(pm.piece_length, PIECE_LENGTH)
                self.assertEqual(pm.num_pieces, ti.num_pieces())
                self.assertEqual(len(pm.files), 3)
                for fi in range(3):
                    size = pm.files[fi].size
                    for off in (0, 1, 777, size // 2, size - 1):
                        req = ti.map_file(fi, off, 1)
                        self.assertIn(req.piece, pm.range_pieces(fi, off, off))
                        self.assertEqual(req.piece, (pm.files[fi].start + off) // pm.piece_length)
                # the movie starts inside a piece shared with the prefix file: that piece must be reported as shared
                first = pm.range_pieces(1, 0, 0)[0]
                self.assertTrue(pm.is_shared(first))
                self.assertEqual({o[0] for o in pm.owners(first)}, {0, 1})
            finally:
                sd.close()


if __name__ == "__main__":
    unittest.main()


class PaddedTorrent(unittest.TestCase):
    def test_pad_files_are_not_owners(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "t"
            root.mkdir()
            random_file(root / "0_prefix.bin", 100_003, 1)
            random_file(root / "1_movie.bin", 300_001, 2)
            sd = Seeder(root, hybrid=True)         # hybrid v1+v2 torrents carry BEP 47 pad files
            try:
                pm = PieceMap.from_torrent_info(sd.ti)
                pads = [f for f in pm.files if f.pad]
                self.assertTrue(pads, "expected pad files in a hybrid torrent")
                for p in range(pm.num_pieces):
                    self.assertTrue(all(not pm.files[i].pad for i, _, _ in pm.owners(p)))
                    self.assertFalse(pm.is_shared(p))        # aligned: no real piece mixes two real files
            finally:
                sd.close()
