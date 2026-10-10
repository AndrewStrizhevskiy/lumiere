# SPDX-License-Identifier: GPL-3.0-or-later
"""Install / uninstall in a throw-away HOME: the packaging promises (only our files, nothing else touched, clean removal) are tested, not assumed."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"


class Packaging(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="ks-home-"))
        self.addCleanup(shutil.rmtree, self.home, True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_") and k != "KINO_STREAM_BIN"}
        self.env.update(HOME=str(self.home), QT_QPA_PLATFORM="offscreen", KINO_REDUCE_MOTION="1")
        # things that belong to other applications and must survive untouched
        self.sentinels = {
            self.home / ".local/bin/otherapp": "#!/bin/sh\necho other\n",
            self.home / ".local/share/applications/otherapp.desktop": "[Desktop Entry]\nName=Other\n",
            self.home / ".local/share/applications/org.qbittorrent.qBittorrent.desktop": "[Desktop Entry]\nName=qBittorrent\n",
            self.home / ".config/qBittorrent/qBittorrent.conf": "[BitTorrent]\n",
            self.home / ".config/mimeapps.list": "[Default Applications]\nx-scheme-handler/magnet=org.qbittorrent.qBittorrent.desktop\n",
            self.home / ".config/otherapp/conf.json": "{}\n",
        }
        for p, text in self.sentinels.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
            os.chmod(p, 0o755 if p.parent.name == "bin" else 0o644)

    def sh(self, *args, env=None, check=True):
        r = subprocess.run(list(map(str, args)), env=env or self.env, capture_output=True, text=True, timeout=120)
        if check and r.returncode:
            self.fail(f"{args} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def assert_sentinels_untouched(self):
        for p, text in self.sentinels.items():
            self.assertTrue(p.exists(), f"{p} was removed")
            self.assertEqual(p.read_text(), text, f"{p} was modified")

    def files_under(self, base: Path) -> set[str]:
        return {str(p.relative_to(self.home)) for p in base.rglob("*") if p.is_file() or p.is_symlink()}

    def install(self):
        return self.sh(PKG / "install.sh", "--no-desktop-db")

    def test_check_mode_writes_nothing(self):
        before = self.files_under(self.home)
        r = self.sh(PKG / "install.sh", "--check")
        self.assertIn("dependencies: OK", r.stdout)
        self.assertEqual(self.files_under(self.home), before)

    def test_install_creates_only_our_files_and_they_work(self):
        before = self.files_under(self.home)
        self.install()
        created = self.files_under(self.home) - before
        for f in created:
            self.assertTrue(f.startswith((".local/share/kino-stream/app/", ".local/bin/kino-stream", ".local/share/applications/kino-stream.desktop",
                                          ".local/share/icons/hicolor/scalable/apps/kino-stream.svg")), f)
        self.assert_sentinels_untouched()
        gui, cli = self.home / ".local/bin/kino-stream-gui", self.home / ".local/bin/kino-stream"
        self.assertIn("kino-stream 0.", self.sh(gui, "--version").stdout)
        self.assertIn("usage", self.sh(cli, "--help").stdout.lower())
        self.assertIn("kino-stream 0.", self.sh(cli, "--version").stdout)
        # the installed copy (not the checkout) is what runs
        self.sh(gui, "--smoke")
        desk = self.home / ".local/share/applications/kino-stream.desktop"
        text = desk.read_text()
        self.assertIn(f'Exec="{gui}" -- %U', text)   # executable quoted; "--": a file name can never be read as an option
        self.assertIn("MimeType=application/x-bittorrent;x-scheme-handler/magnet;", text)
        if shutil.which("desktop-file-validate"):
            self.sh("desktop-file-validate", desk)
        # default handlers are the user's choice: mimeapps.list is untouched (checked above); the launcher only declares support

    def test_reinstall_is_idempotent(self):
        self.install()
        a = self.files_under(self.home)
        self.install()
        self.assertEqual(self.files_under(self.home), a)

    def test_uninstall_removes_everything_it_made_and_keeps_user_data(self):
        before = self.files_under(self.home)
        self.install()
        data = self.home / ".config/kino-stream/settings.json"
        data.parent.mkdir(parents=True)
        data.write_text("{}")
        self.sh(PKG / "uninstall.sh", "--no-desktop-db")
        self.assertEqual(self.files_under(self.home) - before, {".config/kino-stream/settings.json"})
        self.assert_sentinels_untouched()

    def test_purge_removes_only_kino_stream_dirs_and_never_a_custom_cache(self):
        self.install()
        custom = self.home / "Videos" / "my-cache"
        custom.mkdir(parents=True)
        (custom / "keep.bin").write_text("x")
        conf = self.home / ".config/kino-stream"
        conf.mkdir(parents=True)
        (conf / "settings.json").write_text(json.dumps({"cache_root": str(custom)}))
        for d in (".local/state/kino-stream", ".cache/kino-stream/abc"):
            (self.home / d).mkdir(parents=True)
            (self.home / d / "f").write_text("x")
        other = self.home / ".cache/other-app/data"
        other.parent.mkdir(parents=True)
        other.write_text("keep")
        r = self.sh(PKG / "uninstall.sh", "--purge-data", "--no-desktop-db")
        self.assertFalse(conf.exists())
        self.assertFalse((self.home / ".local/state/kino-stream").exists())
        self.assertFalse((self.home / ".cache/kino-stream").exists())
        self.assertTrue((custom / "keep.bin").exists())
        self.assertIn(str(custom), r.stdout)
        self.assertEqual(other.read_text(), "keep")
        self.assert_sentinels_untouched()

    def test_dry_run_changes_nothing(self):
        self.install()
        before = self.files_under(self.home)
        self.sh(PKG / "uninstall.sh", "--purge-data", "--dry-run", "--no-desktop-db")
        self.assertEqual(self.files_under(self.home), before)

    def test_installer_refuses_to_overwrite_a_foreign_launcher(self):
        foreign = self.home / ".local/bin/kino-stream"
        foreign.write_text("#!/bin/sh\necho mine\n")
        r = self.sh(PKG / "install.sh", "--no-desktop-db", check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(foreign.read_text(), "#!/bin/sh\necho mine\n")
        self.sh(PKG / "uninstall.sh", "--no-desktop-db")
        self.assertTrue(foreign.exists(), "uninstall must not remove a launcher it did not create")

    def test_missing_dependency_is_explained_not_guessed(self):
        # a Python that cannot import PyQt6: simulate with a shim directory first on PATH
        shim = self.home / "shim"
        shim.mkdir()
        real = shutil.which("python3")
        (shim / "python3").write_text(f'#!/bin/sh\ncase "$*" in *PyQt6.QtSvg*) exit 1;; esac\nexec {real} "$@"\n')
        os.chmod(shim / "python3", 0o755)
        env = dict(self.env, PATH=f"{shim}:{self.env['PATH']}")
        r = self.sh(PKG / "install.sh", "--no-desktop-db", env=env, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("python3-pyqt6.qtsvg", r.stderr)
        self.assertIn("sudo apt install", r.stderr)


class PathHandling(unittest.TestCase):
    """The install path is user-controlled and ends up in a shell script and in a .desktop file: every character that can be escaped must work
    (verified end to end by launching the entry through GIO), the two that cannot be expressed ("%" for GNOME, control characters) must be refused cleanly."""

    WORKING = ["plain", "with space", "two  spaces", "sq'uote", 'dq"uote', "dollar$HOME", "back`tick", "back\\slash", "double\\\\slash",
               "amp&pipe|semi;", "star*q?hash#", "paren(x)<>~", "ünï-çødé", "mix a\"b$c`d\\e'g"]

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ks-paths-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def env_for(self, name):
        home = self.root / name
        home.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_") and k != "KINO_STREAM_BIN"}
        env.update(HOME=str(home), QT_QPA_PLATFORM="offscreen")
        return home, env

    def run_script(self, script, env, *args):
        return subprocess.run([str(PKG / script), *args], env=env, capture_output=True, text=True, timeout=120)

    def test_every_escapable_character_installs_validates_launches_and_uninstalls(self):
        try:
            from gi.repository import Gio
        except Exception:
            Gio = None
        for i, name in enumerate(self.WORKING):
            with self.subTest(path=name):
                home, env = self.env_for(f"{i}-{name}")
                before = {str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()}
                r = self.run_script("install.sh", env, "--no-desktop-db")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                gui = home / ".local/bin/kino-stream-gui"
                desk = home / ".local/share/applications/kino-stream.desktop"
                self.assertIn("kino-stream 0.", subprocess.run([str(gui), "--version"], env=env, capture_output=True, text=True).stdout)      # generated launcher quoting
                self.assertIn("kino-stream 0.", subprocess.run([str(home / ".local/bin/kino-stream"), "--version"], env=env, capture_output=True, text=True).stdout)
                if shutil.which("desktop-file-validate"):
                    v = subprocess.run(["desktop-file-validate", str(desk)], capture_output=True, text=True)
                    self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
                if Gio is not None:                              # what the desktop would really run: replace the launcher by a stub that records its argv
                    out = self.root / f"argv-{i}.txt"                # clean path: the stub itself must not depend on quoting
                    gui.write_text(f'#!/bin/sh\n# kino-stream installer: test stub\nprintf "%s\\n" "$0" "$@" > "{out}"\n')
                    info = Gio.DesktopAppInfo.new_from_filename(str(desk))
                    self.assertIsNotNone(info, "GIO must accept the entry")
                    info.launch_uris(["file:///tmp/x%20y.torrent"], None)      # %U: GIO hands local files over as paths
                    for _ in range(60):
                        if out.exists() and out.read_text().count("\n") >= 3:
                            break
                        time.sleep(0.1)
                    self.assertEqual(out.read_text().split("\n")[:3], [str(gui), "--", "/tmp/x y.torrent"])
                    out.unlink()
                u = self.run_script("uninstall.sh", env, "--no-desktop-db")
                self.assertEqual(u.returncode, 0, u.stderr)
                self.assertEqual({str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()} - before, set(), "uninstall must leave no file behind")

    def test_percent_and_control_characters_are_refused_without_writing_anything(self):
        for name, expect in (("pct%U", "'%'"), ("tab\there", "control character"), ("new\nline", "control character")):
            with self.subTest(path=name):
                home, env = self.env_for(name)
                r = self.run_script("install.sh", env, "--no-desktop-db")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(expect, r.stderr)
                self.assertEqual([p for p in home.rglob("*") if p.is_file()], [], "a refused install must not create files")

    def test_percent_in_another_directory_than_the_launchers_is_fine(self):
        # only the launcher directory goes into the desktop entry; the app directory is single-quoted in the launcher script
        home, env = self.env_for("data%dir")
        env["XDG_DATA_HOME"] = str(home / "share%x")
        env["KINO_STREAM_BIN"] = str(self.root / "cleanbin")
        r = self.run_script("install.sh", env, "--no-desktop-db")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("kino-stream 0.", subprocess.run([str(self.root / "cleanbin" / "kino-stream-gui"), "--version"], env=env, capture_output=True, text=True).stdout)

    def test_custom_launcher_directory_with_a_space(self):
        home, env = self.env_for("home")
        env["KINO_STREAM_BIN"] = str(home / "my bin")
        r = self.run_script("install.sh", env, "--no-desktop-db")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'Exec="{home}/my bin/kino-stream-gui" -- %U', (home / ".local/share/applications/kino-stream.desktop").read_text())
        self.assertEqual(self.run_script("uninstall.sh", env, "--no-desktop-db").returncode, 0)
        self.assertFalse((home / "my bin/kino-stream-gui").exists())


if __name__ == "__main__":
    unittest.main()
