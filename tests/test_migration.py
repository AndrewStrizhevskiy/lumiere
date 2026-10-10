# SPDX-License-Identifier: GPL-3.0-or-later
"""The one-time, recoverable move of the user's folders from the former name (kino-stream) to lumiere, and the legacy cache marker. Temp directories only."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lumiere import caches, migrate
from lumiere.recent import RecentItems
from lumiere.settings import Settings


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ks-mig-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.base = self.root / "base"
        self.base.mkdir()
        self.old, self.new = self.base / "kino-stream", self.base / "lumiere"

    def make_old(self, files=None):
        files = files or {"settings.json": '{"cache_gb": 7.0, "tour_done": true}', "sub/data.bin": "x" * 1000}
        for rel, text in files.items():
            p = self.old / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return files

    def contents(self, d):
        return {str(p.relative_to(d)): p.read_text() for p in d.rglob("*") if p.is_file()}


class MigrateOneFolder(Base):
    def test_nothing_to_do_without_a_former_folder(self):
        self.assertEqual(migrate.migrate_base(self.base), "none")
        self.assertFalse(self.new.exists())

    def test_the_folder_is_renamed_with_all_content_and_a_link_is_left_behind(self):
        files = self.make_old()
        self.assertEqual(migrate.migrate_base(self.base), "migrated")
        self.assertTrue(self.new.is_dir() and not self.new.is_symlink())
        self.assertTrue(self.old.is_symlink())
        self.assertEqual(os.readlink(self.old), "lumiere")                         # relative: survives moving the home folder
        self.assertEqual(self.contents(self.new), files)
        self.assertEqual(self.contents(self.old), files, "the former path must keep working")
        self.assertFalse((self.base / migrate.JOURNAL).exists())

    def test_it_is_idempotent(self):
        self.make_old()
        migrate.migrate_base(self.base)
        self.assertEqual(migrate.migrate_base(self.base), "none")
        self.assertEqual(migrate.migrate_base(self.base), "none")

    def test_when_both_hold_data_nothing_is_touched(self):
        files = self.make_old()
        (self.new).mkdir()
        (self.new / "mine.txt").write_text("new data")
        self.assertEqual(migrate.migrate_base(self.base), "kept-both")
        self.assertEqual(self.contents(self.old), files)
        self.assertEqual(self.contents(self.new), {"mine.txt": "new data"})
        self.assertFalse(self.old.is_symlink())

    def test_an_empty_new_folder_is_replaced_by_the_rename(self):
        files = self.make_old()
        self.new.mkdir()
        self.assertEqual(migrate.migrate_base(self.base), "migrated")
        self.assertEqual(self.contents(self.new), files)

    def test_interrupted_between_rename_and_link_is_completed_at_the_next_start(self):
        files = self.make_old()
        migrate._write_journal(self.base / migrate.JOURNAL, self.old, self.new, "rename")
        os.rename(self.old, self.new)                                              # the process died here
        self.assertFalse(self.old.exists())
        self.assertEqual(migrate.migrate_base(self.base), "recovered")
        self.assertTrue(self.old.is_symlink())
        self.assertEqual(self.contents(self.new), files)
        self.assertFalse((self.base / migrate.JOURNAL).exists())

    def test_interrupted_before_the_rename_simply_runs_again(self):
        files = self.make_old()
        migrate._write_journal(self.base / migrate.JOURNAL, self.old, self.new, "rename")
        self.assertEqual(migrate.migrate_base(self.base), "migrated")
        self.assertEqual(self.contents(self.new), files)

    def test_a_failing_rename_loses_nothing_and_never_raises(self):
        files = self.make_old()
        with mock.patch("os.rename", side_effect=OSError("disk says no")):
            self.assertEqual(migrate.migrate_base(self.base), "failed")
        self.assertEqual(self.contents(self.old), files)
        self.assertFalse(self.new.exists())
        self.assertEqual(migrate.migrate_base(self.base), "migrated")               # the next start succeeds (the stale journal is handled)
        self.assertEqual(self.contents(self.new), files)

    def test_a_failing_link_keeps_the_data_at_the_new_name(self):
        files = self.make_old()
        with mock.patch("os.symlink", side_effect=OSError("no symlinks here")):
            self.assertEqual(migrate.migrate_base(self.base), "failed")
        self.assertEqual(self.contents(self.new), files)                           # moved, not lost
        self.assertEqual(migrate.migrate_base(self.base), "recovered")             # and the link is made when possible
        self.assertTrue(self.old.is_symlink())

    def test_a_folder_the_user_had_relocated_by_a_link_stays_where_they_put_it(self):
        elsewhere = self.root / "bigdisk" / "cache"
        elsewhere.mkdir(parents=True)
        (elsewhere / "payload").write_text("keep me")
        os.symlink(elsewhere, self.old, target_is_directory=True)
        self.assertEqual(migrate.migrate_base(self.base), "linked")
        self.assertTrue(self.new.is_symlink())
        self.assertEqual((self.new / "payload").read_text(), "keep me")
        self.assertEqual((elsewhere / "payload").read_text(), "keep me")
        self.assertEqual(migrate.migrate_base(self.base), "none")

    def test_a_symlink_that_already_stands_for_the_old_name_is_left_alone(self):
        self.new.mkdir()
        os.symlink("lumiere", self.old, target_is_directory=True)
        self.assertEqual(migrate.migrate_base(self.base), "none")


class MigrateUserFolders(Base):
    def env(self):
        return {"XDG_CONFIG_HOME": str(self.root / "c"), "XDG_STATE_HOME": str(self.root / "s"), "XDG_CACHE_HOME": str(self.root / "k")}

    def test_all_three_bases_are_migrated_and_the_application_loads_the_data(self):
        env = self.env()
        for name, content in (("c", {"settings.json": json.dumps({"cache_gb": 7.0, "network": "quick", "tour_done": True, "version": 1})}),
                              ("s", {"recent.json": json.dumps({"version": 1, "items": [{"infohash": "a" * 40, "title": "Some.Movie.2024.1080p", "source": "x.torrent", "position_s": 12.0,
                                                                                        "duration_s": 100.0, "watched": False, "size": 5, "last_opened": 1.0}]})}),
                              ("k", {"abc/.kino-stream-managed": "{}", "abc/data.bin": "payload"})):
            for rel, text in content.items():
                p = self.root / name / "kino-stream" / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
        res = migrate.migrate_user_dirs(env=env, force=True)
        self.assertEqual(res, {"config": "migrated", "state": "migrated", "cache": "migrated"})
        with mock.patch.dict(os.environ, env):
            migrate._done.clear()
            s = Settings.load()
            self.assertEqual((s.cache_gb, s.network, s.tour_done), (7.0, "quick", True))
            r = RecentItems()
            self.assertEqual((r.items[0]["position_s"], r.items[0]["infohash"]), (12.0, "a" * 40))
        self.assertEqual((self.root / "k" / "lumiere" / "abc" / "data.bin").read_text(), "payload")
        self.assertEqual((self.root / "k" / "kino-stream" / "abc" / "data.bin").read_text(), "payload")   # still reachable under the old name

    def test_the_settings_and_state_accessors_trigger_the_migration_once(self):
        env = self.env()
        (self.root / "c" / "kino-stream").mkdir(parents=True)
        (self.root / "c" / "kino-stream" / "settings.json").write_text('{"cache_gb": 3.0}')
        with mock.patch.dict(os.environ, env):
            migrate._done.clear()
            from lumiere.settings import config_dir
            self.assertEqual(config_dir(), self.root / "c" / "lumiere")
            self.assertEqual(json.loads((config_dir() / "settings.json").read_text())["cache_gb"], 3.0)
            self.assertTrue((self.root / "c" / "kino-stream").is_symlink())

    def test_a_settings_file_that_names_the_former_default_cache_maps_to_the_default(self):
        env = self.env()
        with mock.patch.dict(os.environ, env):
            legacy = self.root / "k" / "kino-stream"
            s = Settings(cache_root=str(legacy)).normalized()
            self.assertEqual(s.cache_root, "")
            self.assertEqual(Settings(cache_root=str(self.root / "elsewhere")).normalized().cache_root, str(self.root / "elsewhere"))


class LegacyMarker(Base):
    def test_a_cache_made_before_the_rename_is_still_managed_and_deletable(self):
        h = "b" * 40
        root = self.root / "cache"
        d = root / h
        d.mkdir(parents=True)
        (d / ".kino-stream-managed").write_text(json.dumps({"infohash": h, "temporary": False, "created": 1.0}))
        (d / "data.bin").write_bytes(b"0" * 4096)
        self.assertEqual(caches.read_marker(d)["infohash"], h)
        self.assertEqual(caches.prepare_cache_dir(root, h), d)                       # reused, not refused as foreign
        self.assertFalse((d / ".lumiere-managed").exists(), "an existing legacy marker is not duplicated")
        caches.delete_managed_cache(root, d, None)
        self.assertFalse(d.exists())

    def test_new_caches_get_the_current_marker_and_foreign_folders_are_still_refused(self):
        h = "c" * 40
        root = self.root / "cache"
        d = caches.prepare_cache_dir(root, h)
        self.assertTrue((d / ".lumiere-managed").exists() and not (d / ".kino-stream-managed").exists())
        foreign = root / ("d" * 40)
        foreign.mkdir()
        (foreign / "someone-elses-file").write_text("x")
        with self.assertRaises(Exception):
            caches.prepare_cache_dir(root, "d" * 40)


if __name__ == "__main__":
    unittest.main()
