"""A Google login no account matches gets a short code for that verified
address (aiza-gateway make_email_proof, the root audit S4 2026-11-24), which
`aiza-set-email --code` then ties to the account that runs it: a file per
code, named by the code's hash, private, gone after 15 minutes.

    python3 -m unittest discover -s tests -v
"""
import hashlib
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from test_gateway_login import load_gateway

G = load_gateway()


class EmailProofTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = G.EMAIL_PROOF_DIR
        G.EMAIL_PROOF_DIR = Path(self.tmp.name)

    def tearDown(self):
        G.EMAIL_PROOF_DIR = self.saved
        self.tmp.cleanup()

    def test_a_code_names_a_private_file_holding_the_address(self):
        code = G.make_email_proof("a@example.org")
        self.assertRegex(code, r"^[0-9a-f]{12}$")
        f = Path(self.tmp.name) / hashlib.sha256(code.encode()).hexdigest()
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        rec = json.loads(f.read_text())
        self.assertEqual(rec["email"], "a@example.org")
        self.assertAlmostEqual(rec["exp"], time.time() + G.EMAIL_PROOF_TTL, delta=5)
        self.assertNotIn(code, os.listdir(self.tmp.name))   # the folder does not hold the codes

    def test_each_login_gets_its_own_code_and_old_ones_go(self):
        old = Path(self.tmp.name) / ("0" * 64)
        old.write_text(json.dumps({"email": "x@example.org", "exp": time.time() - 1}))
        a, b = G.make_email_proof("a@example.org"), G.make_email_proof("a@example.org")
        self.assertNotEqual(a, b)
        self.assertFalse(old.exists())
        self.assertEqual(len(os.listdir(self.tmp.name)), 2)

    def test_at_most_so_many_codes_kept_the_oldest_go(self):
        saved = G.EMAIL_PROOF_MAX
        G.EMAIL_PROOF_MAX = 3
        try:
            codes = [G.make_email_proof(f"a{i}@example.org") for i in range(5)]
        finally:
            G.EMAIL_PROOF_MAX = saved
        names = sorted(os.listdir(self.tmp.name))
        self.assertEqual(len(names), 3)
        kept = {hashlib.sha256(c.encode()).hexdigest() for c in codes[-3:]}
        self.assertEqual(set(names), kept)

    def test_no_folder_no_code(self):
        G.EMAIL_PROOF_DIR = Path(self.tmp.name) / "missing"
        self.assertIsNone(G.make_email_proof("a@example.org"))


if __name__ == "__main__":
    unittest.main()
