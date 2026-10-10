# SPDX-License-Identifier: GPL-3.0-or-later
"""Continue watching with cleaned titles (Phase 0, offline): presentation only. Identity (infohash), stored titles, positions and files are untouched; no network."""
import copy
import json
import os
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LC_NUMERIC", "C")
os.environ["LUMIERE_REDUCE_MOTION"] = "1"
_xdg = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"] = _xdg
os.environ["XDG_STATE_HOME"] = _xdg

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from lumiere.recent import RecentItems  # noqa: E402
from lumiere.settings import Settings  # noqa: E402

app = QApplication.instance() or QApplication([])
from lumiere_ui import theme as T  # noqa: E402
from lumiere_ui.app import install_theme  # noqa: E402

install_theme(app)
from lumiere_ui.bridge import EngineBridge  # noqa: E402
from lumiere_ui.home import HomeScreen, RecentCard  # noqa: E402
from lumiere_ui.mainwindow import MainWindow  # noqa: E402


def texts(card):
    """The visible label texts of a card: year, title (its wrapped lines joined with a space) and progress. The year row is always reserved, so it may be empty."""
    return [" ".join(lab.text().split()) for lab in card.findChildren(QLabel)]


def item(h, title, pos=0.0, dur=0.0, watched=False, opened=1_700_000_000.0):
    return {"infohash": h * 40, "title": title, "source": f"/x/{h}.torrent", "size": 1_000_000, "position_s": pos, "duration_s": dur, "watched": watched, "last_opened": opened}


class Cards(unittest.TestCase):
    def test_cleaned_title_year_and_progress(self):
        c = RecentCard(item("a", "Some.Movie.2024.1080p.WEB-DL.x264-GROUP", pos=300, dur=6000))
        t = texts(c)
        self.assertIn("Some Movie", t)
        self.assertIn("2024", t)                                                   # the year has its own line above the title
        self.assertIn("Resume at 5:00", t)
        self.assertEqual(c.display.original, "Some.Movie.2024.1080p.WEB-DL.x264-GROUP")

    def test_no_year_when_the_name_gives_no_clear_evidence(self):
        for raw, shown in (("IMG_2048", "IMG 2048"), ("Movie.Night.2024.2025.1080p", "Movie Night 2024 2025"), ("Sintel.2010", "Sintel 2010")):
            with self.subTest(raw=raw):
                t = texts(RecentCard(item("b", raw)))
                self.assertIn(shown, t)
                self.assertIn("Not started", t)                                   # no year prefix, no invented detail
                self.assertEqual([x for x in t if x.isdigit() and len(x) == 4 and x not in shown], [])      # no year line, no invented detail

    def test_episodes_and_season_packs_fall_back_to_a_readable_name(self):
        c = RecentCard(item("c", "Some.Show.S01.Complete.1080p.BluRay.x265-GRP"))
        self.assertEqual(c.display.text, "Some Show S01 Complete 1080p BluRay x265-GRP")        # the readable name, complete (the card elides it visually; the tooltip has it all)
        self.assertEqual((c.display.year, c.display.source), (None, "filename"))
        self.assertIn("Not started", texts(c))

    def test_watched_and_not_started_wording_is_unchanged(self):
        t = texts(RecentCard(item("d", "Film.2020.1080p.WEB-DL", pos=5900, dur=6000, watched=True)))
        self.assertIn("2020", t)
        self.assertIn("Watched", t)
        t = texts(RecentCard(item("d", "Film.2020.1080p.WEB-DL")))
        self.assertIn("2020", t)
        self.assertIn("Not started", t)

    def test_empty_or_missing_title_has_a_fallback_and_never_an_empty_label(self):
        for it in (item("e", ""), {"infohash": "e" * 40}):
            with self.subTest(it=it):
                c = RecentCard(it)
                self.assertIn("Untitled", texts(c))
                self.assertTrue(all(x.strip() for x in texts(c)[1:]), "an empty label is shown")          # [0] is the reserved (possibly empty) year row

    def test_the_stored_name_stays_available_and_last_opened_is_labelled_as_opened(self):
        c = RecentCard(item("f", "Some.Movie.2024.1080p.WEB-DL.x264-GROUP"))
        tip = c.toolTip().replace("\xa0", " ")                                     # Qt encodes plain-text spaces in tooltips as non-breaking
        self.assertIn("Some.Movie.2024.1080p.WEB-DL.x264-GROUP", tip)
        self.assertIn("Last opened:", tip)
        self.assertNotIn("watched", tip.lower())                                  # the timestamp is when it was opened, not when it was watched

    def test_a_hostile_file_name_is_not_interpreted_as_markup(self):
        c = RecentCard(item("g", "<img src='http://evil.example/x.png'><b>Bold</b>.2024.1080p.WEB-DL"))
        tip = c.toolTip()
        self.assertNotIn("<img", tip)
        self.assertIn("&lt;img", tip)
        for lab in c.findChildren(QLabel):
            self.assertEqual(lab.textFormat().name, "PlainText")

    def test_card_size_does_not_depend_on_the_title(self):
        sizes = {(RecentCard(item("h", t)).width(), RecentCard(item("h", t)).height()) for t in ("A", "Some.Movie.2024.1080p.WEB-DL", "x" * 300, "Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p.BluRay.x264")}
        self.assertEqual(sizes, {(RecentCard.WIDTH, RecentCard.HEIGHT)})                                     # a title that arrives later can never move the layout


class HomeList(unittest.TestCase):
    def build(self, items):
        h = HomeScreen()
        h.resize(900, 600)
        h.show()
        h.set_recent(items)
        for _ in range(3):
            app.processEvents()
        self.addCleanup(h.close)
        return h

    def test_two_entries_with_the_same_cleaned_title_stay_two_entries(self):
        a, b = item("a", "Crash.2004.1080p.BluRay.x264"), item("b", "Crash.2004.720p.WEB-DL.x264")
        h = self.build([a, b])
        cards = h.findChildren(RecentCard)
        self.assertEqual(len(cards), 2)
        self.assertEqual({c.item["infohash"] for c in cards}, {"a" * 40, "b" * 40})
        got = []
        h.openRequested.connect(lambda src, title: got.append((src, title)))
        for c in cards:
            c.clicked.emit(c.item)
        # what is opened is the STORED source and the STORED title - the cleaned title never replaces them
        self.assertEqual(sorted(got), sorted([(a["source"], a["title"]), (b["source"], b["title"])]))

    def test_building_the_list_never_modifies_items_or_the_file(self):
        tmp = Path(tempfile.mkdtemp())
        r = RecentItems(tmp / "recent.json")
        r.touch("a" * 40, "Some.Movie.2024.1080p.WEB-DL.x264-GROUP", "x.torrent", 5)
        r.update_position("a" * 40, 300, 6000)
        before_items, before_bytes, before_mtime = copy.deepcopy(r.items), (tmp / "recent.json").read_bytes(), (tmp / "recent.json").stat().st_mtime_ns
        self.build(r.items)
        self.assertEqual(r.items, before_items)
        self.assertEqual((tmp / "recent.json").read_bytes(), before_bytes)
        self.assertEqual((tmp / "recent.json").stat().st_mtime_ns, before_mtime)
        self.assertEqual(json.loads(before_bytes.decode())["items"][0]["title"], "Some.Movie.2024.1080p.WEB-DL.x264-GROUP")

    def test_positions_and_progress_are_preserved_across_reopening(self):
        tmp = Path(tempfile.mkdtemp())
        r = RecentItems(tmp / "recent.json")
        r.touch("a" * 40, "Some.Movie.2024.1080p.WEB-DL.x264-GROUP", "x.torrent", 5)
        r.update_position("a" * 40, 1234.0, 6000.0)
        r.touch("a" * 40, "Some.Movie.2024.1080p.WEB-DL.x264-GROUP", "x.torrent", 5)       # opened again
        it = r.items[0]
        self.assertEqual((it["position_s"], it["duration_s"], it["watched"]), (1234.0, 6000.0, False))
        t = texts(RecentCard(it))
        self.assertIn("2024", t)
        self.assertIn("Resume at 20:34", t)

    def test_no_network_is_touched_when_cards_are_built(self):
        def boom(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), mock.patch.object(socket, "getaddrinfo", boom):
            self.build([item("a", "Some.Movie.2024.1080p.WEB-DL.x264-GROUP"), item("b", "IMG_2048")])


class WithTheWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.recent = RecentItems(self.tmp / "recent.json")
        self.recent.touch("a" * 40, "Some.Movie.2024.1080p.WEB-DL.x264-GROUP", str(self.tmp / "a.torrent"), 5)
        self.win = MainWindow(EngineBridge(Settings(cache_root=str(self.tmp / "c"), tour_done=True), self.tmp / "state", self.recent))
        self.win.resize(1000, 680)
        self.win.show()
        for _ in range(5):
            app.processEvents()
        self.addCleanup(self.win.close)

    def test_updating_the_list_while_a_video_is_open_does_not_disturb_it(self):
        from types import SimpleNamespace
        self.win.player.media = SimpleNamespace(infohash="a" * 40, title="x", url="u", temporary=False)
        self.win.player._active = False
        self.win.stack.setCurrentIndex(self.win.PLAYER)
        before = (self.win.player.media, self.win.stack.currentIndex())
        self.win.home.set_recent([item("a", "Some.Movie.2024.1080p.WEB-DL"), item("b", "Other.Film.1999.720p.HDTV.x264")])
        self.win.home.set_recent([])
        self.win.home.set_recent(self.recent.items)
        self.assertEqual((self.win.player.media, self.win.stack.currentIndex()), before)

    def test_opening_from_a_card_uses_the_existing_workflow_unchanged(self):
        opened = []
        self.win.bridge.open_source = lambda src, **kw: opened.append((src, kw))
        torrent = self.tmp / "a.torrent"
        torrent.write_bytes(b"d4:infod4:name1:xee")
        card = self.win.home.findChildren(RecentCard)[0]
        card.clicked.emit(card.item)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0][0], str(torrent))
        self.assertEqual(opened[0][1].get("title"), "Some.Movie.2024.1080p.WEB-DL.x264-GROUP")   # the stored title, not the cleaned one


if __name__ == "__main__":
    unittest.main()
