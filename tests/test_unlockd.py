"""Runs tests/unlockd_cases.py (aiza-unlockd's window and token rules) with
the daemon's own Python, the one that has fido2; skipped where that is not
installed (a checkout elsewhere).

    python3 -m unittest discover -s tests -v
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = Path(os.environ.get("AIZA_VENV_PYTHON", "/opt/aiza/venv/bin/python3"))


@unittest.skipUnless(VENV.exists(), "the daemon's venv (fido2) is needed")
class UnlockdTest(unittest.TestCase):
    def test_window_and_token_rules(self):
        r = subprocess.run([str(VENV), "-m", "unittest", "-v", "unlockd_cases"], cwd=HERE,
                           capture_output=True, text=True, timeout=300,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(r.returncode, 0, r.stderr[-4000:])
        self.assertRegex(r.stderr, r"Ran \d+ tests")


if __name__ == "__main__":
    unittest.main()
