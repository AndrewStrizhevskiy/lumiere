# SPDX-License-Identifier: GPL-3.0-or-later
"""The publish gate: placeholders block publishing until every value is given explicitly."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "release_config.py"


class ReleaseConfig(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        (self.d / "tools").mkdir()
        shutil.copy(TOOL, self.d / "tools" / "release_config.py")
        (self.d / "SECURITY.md").write_text("mail @@SECURITY_EMAIL@@ repo @@GITHUB_REPO@@ conduct @@CONDUCT_EMAIL@@\n")
        (self.d / "LICENSE").write_text("license text\n")
        for c in (["git", "init", "-q"], ["git", "add", "-A"]):
            subprocess.run(c, cwd=self.d, check=True)

    def run_tool(self, *a):
        return subprocess.run([sys.executable, str(self.d / "tools" / "release_config.py"), *a], cwd=self.d, capture_output=True, text=True)

    def test_blocks_until_every_value_is_given(self):
        r = self.run_tool("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("@@GITHUB_REPO@@", r.stderr)
        self.assertNotEqual(self.run_tool("apply", "--repo", "a/b").returncode, 0)            # missing values are never guessed
        self.assertNotEqual(self.run_tool("apply", "--repo", "bad repo", "--security-email", "x@y.zz", "--conduct-email", "x@y.zz").returncode, 0)
        self.assertNotEqual(self.run_tool("apply", "--repo", "a/b", "--security-email", "nope", "--conduct-email", "x@y.zz").returncode, 0)

    def test_apply_then_check_passes(self):
        r = self.run_tool("apply", "--repo", "owner/name", "--security-email", "sec@example.org", "--conduct-email", "coc@example.org")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sec@example.org", (self.d / "SECURITY.md").read_text())
        self.assertEqual(self.run_tool("check").returncode, 0)

    def test_repo_only_apply_works_when_no_file_needs_an_email_and_never_half_applies_otherwise(self):
        (self.d / "SECURITY.md").write_text("repo @@GITHUB_REPO@@ uses private reporting\n")
        subprocess.run(["git", "add", "-A"], cwd=self.d, check=True)
        self.assertEqual(self.run_tool("apply", "--repo", "owner/name").returncode, 0)
        self.assertEqual(self.run_tool("check").returncode, 0)
        (self.d / "OTHER.md").write_text("repo @@GITHUB_REPO@@ mail @@SECURITY_EMAIL@@\n")
        subprocess.run(["git", "add", "-A"], cwd=self.d, check=True)
        before = (self.d / "SECURITY.md").read_text()
        r = self.run_tool("apply", "--repo", "x/y")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("@@SECURITY_EMAIL@@", r.stderr)
        self.assertEqual((self.d / "SECURITY.md").read_text(), before)          # nothing was written

    def test_missing_license_blocks(self):
        self.run_tool("apply", "--repo", "o/n", "--security-email", "s@e.org", "--conduct-email", "c@e.org")
        (self.d / "LICENSE").unlink()
        self.assertEqual(self.run_tool("check").returncode, 1)


if __name__ == "__main__":
    unittest.main()
