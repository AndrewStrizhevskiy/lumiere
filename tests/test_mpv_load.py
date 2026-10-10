# SPDX-License-Identifier: GPL-3.0-or-later
"""The title of a video comes from a torrent's file name (untrusted): it must never reach mpv as a loadfile option string (python-mpv joins options with commas)."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lumiere_ui.mpvwidget import MpvWidget  # noqa: E402


class Recorder:
    def __init__(self):
        self.props, self.loaded = {}, []

    def __setitem__(self, key, value):
        self.props[key] = value

    def loadfile(self, url, **opts):
        self.loaded.append((url, opts))


class LoadKeepsTheTitleOutOfTheOptionString(unittest.TestCase):
    def load(self, title, start=0.0):
        rec = Recorder()
        MpvWidget.load(SimpleNamespace(mpv=rec), "http://127.0.0.1:1/x/v.mkv", start, title)
        return rec

    def test_a_hostile_title_is_only_ever_a_property_value(self):
        for title in ("x,script=/tmp/evil.lua", "a=b,ytdl-raw-options=c", "line1\nline2", "100%,start=9999"):
            with self.subTest(title=title):
                rec = self.load(title)
                self.assertEqual(rec.props["force-media-title"], title)
                self.assertEqual(rec.loaded, [("http://127.0.0.1:1/x/v.mkv", {})])        # no option derived from the title

    def test_start_position_is_still_passed_and_an_empty_title_clears_the_property(self):
        rec = self.load("", start=12.34)
        self.assertEqual(rec.loaded[0][1], {"start": "12.3"})
        self.assertEqual(rec.props["force-media-title"], "")

    def test_without_an_mpv_instance_nothing_happens(self):
        MpvWidget.load(SimpleNamespace(mpv=None), "u", 5.0, "t")


if __name__ == "__main__":
    unittest.main()
