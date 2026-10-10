# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the libtorrent crash (root cause: wait_for_alert() hands out a pointer into the live alert queue)."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NoWaitForAlert(unittest.TestCase):
    def test_application_and_test_support_never_call_wait_for_alert(self):
        offenders = []
        for p in list((ROOT / "lumiere").rglob("*.py")) + [ROOT / "tests" / "support.py"]:
            for n, line in enumerate(p.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if re.search(r"\.wait_for_alert\s*\(", code):
                    offenders.append(f"{p.relative_to(ROOT)}:{n}")
        self.assertEqual(offenders, [], "wait_for_alert() returns a dangling pointer under load: use pop_alerts() only")


class AlertStorm(unittest.TestCase):
    def test_reading_alerts_with_pop_alerts_survives_an_alert_storm(self):
        """Same storm that kills the wait_for_alert() reader 3 times out of 3 (diag/alert_stress.py wait): all categories,
        ~35k alerts/s, 3 seeders. Run in a subprocess so that a crash fails this test instead of the runner."""
        r = subprocess.run([sys.executable, str(ROOT / "diag" / "alert_stress.py"), "poll", "20"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, f"rc={r.returncode} {r.stderr[-300:]}")
        self.assertIn("survived", r.stdout)

    def test_reading_alerts_with_pop_alerts_from_a_second_thread_also_survives(self):
        r = subprocess.run([sys.executable, str(ROOT / "diag" / "alert_stress.py"), "tpoll", "20"], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, f"rc={r.returncode} {r.stderr[-300:]}")


if __name__ == "__main__":
    unittest.main()
