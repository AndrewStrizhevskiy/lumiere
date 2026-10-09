"""Install / uninstall in a throw-away HOME: the packaging promises (only our files, nothing else touched, clean removal) are tested, not assumed."""
import json
import os
import shutil
import subprocess
import tempfile
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
            self.home / ".local/bin/otherapp": "#!/bin/sh\necho kino\n",
            self.home / ".local/share/applications/otherapp.desktop": "[Desktop Entry]\nName=Kino\n",
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
        self.assertIn(f"Exec={gui} %U", text)
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


if __name__ == "__main__":
    unittest.main()
