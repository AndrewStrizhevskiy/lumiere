# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline title cleaner: deterministic, no Qt, no network, no filesystem, no clock (the year ceiling is passed explicitly)."""
import ast
import re
import subprocess
import sys
import unicodedata
import unittest
from pathlib import Path

from kino_stream.titles import (KIND_CLEANED, KIND_DECLINED, KIND_READABLE, DisplayTitle, clean_release_name as clean, for_name, for_recent_item)

MAX = 2026
ROOT = Path(__file__).resolve().parents[1]


def c(name):
    return clean(name, MAX)


class Ordinary(unittest.TestCase):
    CASES = [
        ("Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv", "Some Movie", 2024),
        ("Casino.Royale.2006.2160p.WEB-DL.DDP5.1.HDR.x265-GRP.mkv", "Casino Royale", 2006),
        ("The.Matrix.Reloaded.2003.720p.BRRip.XviD.mkv", "The Matrix Reloaded", 2003),
        ("Wall-E.2008.1080p.BluRay.x264-GRP.mkv", "Wall-E", 2008),
        ("12.Years.a.Slave.2013.1080p.BluRay.x264.mkv", "12 Years a Slave", 2013),
        ("The.Lord.of.the.Rings.The.Return.of.the.King.2003.EXTENDED.1080p.BluRay.x264.mkv", "The Lord of the Rings The Return of the King", 2003),
        ("Se7en.1995.REMASTERED.1080p.BluRay.x264.mkv", "Se7en", 1995),
        ("Crash.1996.1080p.BluRay.x264.mkv", "Crash", 1996),
        ("Crash.2004.1080p.BluRay.x264.mkv", "Crash", 2004),                      # same title, different film: different year, never merged here
        ("Big Buck Bunny (2008) [1080p].mp4", "Big Buck Bunny", 2008),
        ("Big Buck Bunny (2008).mp4", "Big Buck Bunny", 2008),                    # a parenthesised year is explicit evidence even without release tags
        ("[YTS] Parasite (2019) 1080p.mp4", "Parasite", 2019),
        ("www.Example.com - Some Movie 2020 720p HDTV x264.avi", "Some Movie", 2020),
        ("Mr.Nobody.2009.1080p.BluRay.mkv", "Mr Nobody", 2009),
        ("Some.Movie.2024.1080p.WEB-DL.x264-GROUP", "Some Movie", 2024),          # no extension (a torrent's folder name)
    ]

    def test_ordinary_release_names(self):
        for name, title, year in self.CASES:
            with self.subTest(name=name):
                r = c(name)
                self.assertEqual((r.display, r.year, r.kind), (title, year, KIND_CLEANED))
                self.assertEqual(r.original, name)                                # the original is never altered

    def test_title_with_release_words_inside_is_not_cut(self):
        r = c("The.Final.Cut.1999.1080p.BluRay.x264.mkv")                         # "Cut" is a weak word: kept inside a title
        self.assertEqual((r.display, r.year), ("The Final Cut", 1999))
        r = c("Extended.Family.2015.1080p.WEB-DL.mkv")
        self.assertEqual((r.display, r.year), ("Extended Family", 2015))


class Years(unittest.TestCase):
    def test_year_only_when_clear(self):
        self.assertEqual(c("Sintel.2010.mkv").year, None)                          # no release tag, no parentheses: a number is just a number
        self.assertEqual(c("Sintel.2010.mkv").display, "Sintel 2010")
        self.assertEqual(c("Sintel.2010.mkv").kind, KIND_READABLE)

    def test_two_plausible_years_in_a_row_are_not_decided(self):
        for name, shown in (("Movie.Night.2024.2025.1080p.mkv", "Movie Night 2024 2025"), ("1917.2019.1080p.WEB-DL.DD5.1.H264-GRP.mkv", "1917 2019"),
                            ("2012.2009.1080p.BluRay.x264.mkv", "2012 2009")):
            with self.subTest(name=name):
                r = c(name)
                self.assertIsNone(r.year)
                self.assertEqual(r.display, shown)

    def test_an_unknown_tag_between_year_and_release_tags_gives_no_year_instead_of_a_guess(self):
        r = c("Film.2019.VOSTFR.1080p.WEB-DL.x264.mkv")           # documented limitation (docs/design/TITLE_CLEANER.md): honest and imperfect
        self.assertIsNone(r.year)
        self.assertEqual(r.display, "Film 2019 VOSTFR")

    def test_year_inside_the_title_is_kept_and_the_release_year_is_found(self):
        r = c("2001.A.Space.Odyssey.1968.1080p.BluRay.x264.mkv")
        self.assertEqual((r.display, r.year), ("2001 A Space Odyssey", 1968))
        r = c("Blade.Runner.2049.2017.2160p.UHD.BluRay.x265-GRP.mkv")              # 2049 is not a plausible release year
        self.assertEqual((r.display, r.year), ("Blade Runner 2049", 2017))
        r = c("1917.1080p.BluRay.x264.mkv")
        self.assertEqual((r.display, r.year), ("1917", None))                     # a title that is a year, no other year: never promoted to a release year

    def test_implausible_years_are_never_used(self):
        for name in ("IMG_2048.mov", "IMG_2048.1080p.mov", "Photo.1850.1080p.x264.mkv", "Movie.2099.1080p.x264.mkv"):
            with self.subTest(name=name):
                self.assertIsNone(c(name).year)
        self.assertEqual(c("IMG_2048.mov").display, "IMG 2048")                   # readable, honest
        self.assertEqual(c("IMG_2048.mov").kind, KIND_READABLE)

    def test_the_year_ceiling_is_a_parameter_not_the_clock(self):
        self.assertEqual(clean("Movie.2027.1080p.x264.mkv", 2026).year, None)
        self.assertEqual(clean("Movie.2027.1080p.x264.mkv", 2027).year, 2027)

    def test_a_conflicting_parenthesised_year_does_not_force_a_year(self):
        r = c("Some Movie (2019) (2020) 1080p.mp4")
        self.assertIsNone(r.year)


class NotAFilm(unittest.TestCase):
    def test_episodes_season_packs_and_collections_are_declined(self):
        for name in ("Some.Show.S01E03.1080p.WEB-DL.x264-GRP.mkv", "Some.Show.1x03.720p.mkv", "Some.Show.E05.1080p.mkv", "Some Show Episode 4 1080p.mp4",
                     "Some.Show.S01.Complete.1080p.BluRay.x265-GRP", "Some.Show.Season.2.1080p.WEB-DL", "Some.Show.Complete.Series.720p",
                     "The.Lord.of.the.Rings.Trilogy.2001-2003.1080p.mkv", "Pixar.Collection.1995-2020.1080p", "Bond.Box.Set.1080p.BluRay"):
            with self.subTest(name=name):
                r = c(name)
                self.assertEqual((r.kind, r.year), (KIND_DECLINED, None))
                self.assertTrue(r.display)                                          # still a readable name, never empty

    def test_the_word_season_inside_a_film_title_without_a_number_is_not_a_pack(self):
        self.assertEqual(c("Seasons.of.Love.2015.1080p.BluRay.x264.mkv").kind, KIND_CLEANED)


class Unicode(unittest.TestCase):
    @staticmethod
    def pair(name):
        r = clean(name, MAX)
        return r.display, r.year

    def test_non_latin_and_accented_names(self):
        self.assertEqual(self.pair("Левиафан.2014.1080p.BluRay.x264.mkv"), ("Левиафан", 2014))
        self.assertEqual(self.pair("千と千尋の神隠し.2001.1080p.BluRay.x264.mkv"), ("千と千尋の神隠し", 2001))
        self.assertEqual(self.pair("Amélie.2001.1080p.BluRay.x264.mkv"), ("Amélie", 2001))
        self.assertEqual(self.pair("Das.Leben.der.Anderen.2006.720p.BluRay.x264.mkv"), ("Das Leben der Anderen", 2006))

    def test_decomposed_accents_are_normalised_but_not_changed_otherwise(self):
        nfd = unicodedata.normalize("NFD", "Amélie.2001.1080p.BluRay.x264.mkv")
        r = clean(nfd, MAX)
        self.assertEqual(r.display, unicodedata.normalize("NFC", "Amélie"))
        self.assertEqual(r.original, nfd)                                         # the stored original is exactly what was passed

    def test_spelling_is_never_invented(self):
        r = c("Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p.BluRay.x264-GROUP.mkv")
        self.assertEqual(r.display, "Le Fabuleux Destin d Amelie Poulain")        # no accents added, no apostrophe guessed: that would be inventing a title
        self.assertEqual(r.year, 2001)


class Punctuation(unittest.TestCase):
    def test_meaningful_punctuation_survives(self):
        self.assertEqual(c("Wall-E.2008.1080p.BluRay.x264-GRP.mkv").display, "Wall-E")
        self.assertEqual(c("Spider-Man.Into.the.Spider-Verse.2018.1080p.BluRay.x264.mkv").display, "Spider-Man Into the Spider-Verse")
        self.assertEqual(c("Don't.Look.Up.2021.1080p.WEB-DL.x264.mkv").display, "Don't Look Up")
        self.assertEqual(c("Dr. Strangelove 1964 1080p BluRay x264.mkv").display, "Dr. Strangelove")
        self.assertEqual(c("What.Ever.Happened.to.Baby.Jane?.1962.1080p.BluRay.x264.mkv").display, "What Ever Happened to Baby Jane?")

    def test_case_is_preserved(self):
        self.assertEqual(c("SOME.MOVIE.2024.1080p.WEB-DL.x264-GRP.mkv").display, "SOME MOVIE")

    def test_dangling_separators_are_trimmed(self):
        self.assertEqual(c("Some Movie - 2024 - 1080p - BluRay.mkv").display, "Some Movie")


class EdgeCases(unittest.TestCase):
    def test_empty_none_and_whitespace(self):
        for name in ("", "   ", None, ".mkv"):
            with self.subTest(name=name):
                r = clean(name, MAX)
                self.assertEqual((r.display, r.year, r.kind), ("", None, KIND_READABLE))

    def test_unrecognised_names_become_readable_not_cleaned(self):
        for name, shown in (("holiday_video_final_v2.mp4", "holiday video final v2"), ("Tears of Steel.mkv", "Tears of Steel"), ("IMG_2048.mov", "IMG 2048")):
            with self.subTest(name=name):
                r = c(name)
                self.assertEqual((r.display, r.year, r.kind), (shown, None, KIND_READABLE))

    def test_a_tag_as_the_very_first_word_is_not_a_title_cut(self):
        r = c("1080p.Some.Movie.mkv")
        self.assertNotEqual(r.display, "")

    def test_very_long_and_odd_input_never_raises(self):
        for name in ("a" * 5000, "." * 50, "x264", "(2020)", "[1080p]", "2020", "(((", "\x00\x01.2020.1080p", "Movie.2020." + "1080p." * 500):
            with self.subTest(name=name[:20]):
                clean(name, MAX)


class Guarantees(unittest.TestCase):
    NAMES = ["Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv", "Movie.Night.2024.2025.1080p.mkv", "IMG_2048.mov", "2001.A.Space.Odyssey.1968.1080p.BluRay.x264.mkv",
             "Some.Show.S01E03.1080p.mkv", "Sintel.2010.mkv", "Amélie.2001.1080p.BluRay.x264.mkv", "Big Buck Bunny (2008) [1080p].mp4", "Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p.mkv",
             "holiday_video_final_v2.mp4", "Crash.2004.1080p.BluRay.x264.mkv", "The.Final.Cut.1999.1080p.BluRay.x264.mkv", "[YTS] Parasite (2019) 1080p.mp4"]

    def test_nothing_is_ever_invented(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                r = c(name)
                words = set(re.split(r"[\s._()\[\]]+", unicodedata.normalize("NFC", name)))
                for w in r.display.split():
                    self.assertIn(w, words, f"'{w}' is not in the original name")
                if r.year is not None:
                    self.assertIn(str(r.year), name, "a year that is not in the name")

    def test_the_original_is_always_preserved_and_the_function_is_deterministic(self):
        for name in self.NAMES:
            self.assertEqual(c(name).original, name)
            self.assertEqual(c(name), c(name))

    def test_display_title_boundary_and_recent_items(self):
        d = for_name("Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv", MAX)
        self.assertEqual((d.text, d.year, d.source, d.original), ("Some Movie", 2024, "filename-cleaned", "Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv"))
        d = for_name("IMG_2048.mov", MAX)
        self.assertEqual((d.text, d.year, d.source), ("IMG 2048", None, "filename"))
        item = {"infohash": "a" * 40, "title": "Some.Movie.2024.1080p.WEB-DL.x264-GROUP", "position_s": 12.0}
        before = dict(item)
        self.assertEqual(for_recent_item(item, MAX).text, "Some Movie")
        self.assertEqual(item, before, "the recent item must not be modified")
        self.assertEqual(for_recent_item({}, MAX).text, "")                       # missing title: empty, the UI supplies its own fallback

    def test_two_different_torrents_with_the_same_cleaned_title_stay_distinct_items(self):
        a, b = {"infohash": "a" * 40, "title": "Crash.2004.1080p.BluRay.x264"}, {"infohash": "b" * 40, "title": "Crash.2004.720p.WEB-DL.x264"}
        self.assertEqual(for_recent_item(a, MAX).text, for_recent_item(b, MAX).text)
        self.assertNotEqual(a["infohash"], b["infohash"])                         # identity is the infohash; display titles never decide it


class Misleading(unittest.TestCase):
    """Names where a four-digit number or a tag could mislead: prefer an imperfect but honest name to a wrong identity."""

    def test_numbers_that_are_not_release_years(self):
        cases = {"Apollo.13.1995.1080p.BluRay.x264.mkv": ("Apollo 13", 1995), "Room.237.2012.1080p.BluRay.x264.mkv": ("Room 237", 2012),
                 "The.2020.Election.1080p.WEB-DL.x264.mkv": ("The 2020 Election", None),          # a year-like number inside the title, no year after it
                 "Bond.007.1080p.x264.mkv": ("Bond 007", None), "DSC_1999.mp4": ("DSC 1999", None), "VID_20240101_120000.mp4": ("VID 20240101 120000", None),
                 "Movie.2020.mkv": ("Movie 2020", None), "Movie.2020.2021.mkv": ("Movie 2020 2021", None)}
        for name, (title, year) in cases.items():
            with self.subTest(name=name):
                r = clean(name, MAX)
                self.assertEqual((r.display, r.year), (title, year))

    def test_a_year_is_never_taken_from_a_name_that_has_no_release_evidence(self):
        for name in ("Holiday 2019.mp4", "Family.Trip.2018.mp4", "Concert_2023_final.mkv"):
            with self.subTest(name=name):
                self.assertIsNone(clean(name, MAX).year)

    def test_a_filename_made_only_of_tags_is_not_shortened_to_nothing(self):
        for name in ("1080p.BluRay.x264.mkv", "x264.mkv", "BluRay.mkv"):
            with self.subTest(name=name):
                self.assertTrue(clean(name, MAX).display)


class Purity(unittest.TestCase):
    def test_no_network_or_io_modules_are_imported_by_the_source(self):
        tree = ast.parse((ROOT / "kino_stream" / "titles.py").read_text())
        imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(imported <= {"__future__", "re", "unicodedata", "dataclasses", "datetime"}, imported)

    def test_importing_and_calling_it_loads_no_qt_and_opens_no_socket(self):
        code = ("import socket, sys\n"
                "def boom(*a, **k): raise AssertionError('network access attempted')\n"
                "socket.socket = boom; socket.create_connection = boom; socket.getaddrinfo = boom\n"
                "from kino_stream.titles import clean_release_name, for_name\n"
                "clean_release_name('Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv', 2026); for_name('IMG_2048.mov', 2026)\n"
                "assert not [m for m in sys.modules if m.startswith(('PyQt', 'libtorrent', 'urllib.request', 'http.client'))], 'unexpected module loaded'\n"
                "print('pure')\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "pure"), r.stderr)


if __name__ == "__main__":
    unittest.main()
