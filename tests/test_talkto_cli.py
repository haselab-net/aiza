"""talkto and talkto-remote (the deployment notes), 2026-10-28: --help and
unknown options never send anything; words are joined; stdin works; and
each line's outcome, written back by the backend (_poll_talkto_file ->
_write_talkto_status), is waited for and printed.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_shared_search import B

BIN = Path(__file__).resolve().parent.parent / "bin"
SCRIPTS = {"talkto": [sys.executable, str(BIN / "talkto")], "talkto-remote": ["bash", str(BIN / "talkto-remote")]}


class TalktoCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "talkto_out.jsonl"
        self.env = dict(os.environ, AIZA_TALKTO=str(self.path))
        self.env.pop("AIZA_TALKTO_ID", None)
        self.saved = B._relay_to_partner

    def tearDown(self):
        B._relay_to_partner = self.saved
        self.tmp.cleanup()

    def run_cli(self, script, *args, stdin=""):
        return subprocess.run(SCRIPTS[script] + list(args), input=stdin, capture_output=True,
                              text=True, env=self.env, timeout=30)

    def lines(self):
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l]

    def test_help_and_bad_options_send_nothing(self):
        for script in SCRIPTS:
            for args in (["--help"], ["-h"], ["-help"], ["--help", "x"]):
                r = self.run_cli(script, *args)
                self.assertEqual(r.returncode, 0, (script, args, r.stderr))
                self.assertIn("talkto", r.stdout)
            r = self.run_cli(script, "-v", "x")
            self.assertEqual(r.returncode, 2, script)
            self.assertIn("-v", r.stderr)
            self.assertEqual(self.lines(), [], script)

    def test_words_dashes_and_stdin(self):
        for script in SCRIPTS:
            self.path.unlink(missing_ok=True)
            self.run_cli(script, "--all", "--no-wait", "hello", "world")
            self.run_cli(script, "--no-wait", "--all", "--", "-v は文")
            self.run_cli(script, "--no-wait", "--all", stdin="複数行の\n`文` $HOME 'x'\n")
            self.run_cli(script, "--all", "--no-wait", "-", stdin="ハイフンから")
            got = [l.get("text") or B.base64.b64decode(l["b64"]).decode() for l in self.lines()]
            self.assertEqual(got, ["hello world", "-v は文", "複数行の\n`文` $HOME 'x'\n", "ハイフンから"], script)
            self.assertTrue(all(l.get("id") for l in self.lines()), script)
            self.assertTrue(all(l.get("all") is True for l in self.lines()), script)

    def relay_once(self, outcome):
        """Plays the backend: waits for one line, relays it, writes its outcome."""
        B._relay_to_partner = lambda sid, text: outcome

        def run():
            deadline = time.time() + 10
            while time.time() < deadline and not self.path.exists():
                time.sleep(0.05)
            time.sleep(0.2)
            B._poll_talkto_file("s", self.path, 0)

        t = threading.Thread(target=run)
        t.start()
        return t

    def test_reports_outcome(self):
        for script in SCRIPTS:
            for outcome, code in ((("delivered", "届きました(相手「X」)"), 0),
                                  (("no_link", "つながっている相手がいない"), 1)):
                self.path.unlink(missing_ok=True)
                self.path.with_name("talkto_out.jsonl.offset").unlink(missing_ok=True)
                t = self.relay_once(outcome)
                r = self.run_cli(script, "--to", "X", "やあ")
                t.join()
                self.assertEqual(r.returncode, code, (script, r.stdout, r.stderr))
                self.assertIn(outcome[1], r.stdout, script)

    def test_list_asks_and_prints_the_members(self):
        # `talkto --list` (2026-11-25): a {"list": true} line, nothing sent; the backend's answer printed as is
        saved = B.link_list_from_session
        B.link_list_from_session = lambda sid: ("list", "つながっている相手(1人):\n「X」 Claude・devbox・動いている")
        try:
            for script in SCRIPTS:
                self.path.unlink(missing_ok=True)
                self.path.with_name("talkto_out.jsonl.offset").unlink(missing_ok=True)
                t = self.relay_once(("delivered", "relayed: must not happen"))
                r = self.run_cli(script, "--list")
                t.join()
                self.assertEqual(r.returncode, 0, (script, r.stdout, r.stderr))
                self.assertEqual(r.stdout, "つながっている相手(1人):\n「X」 Claude・devbox・動いている\n", script)
                [line] = self.lines()
                self.assertIs(line["list"], True, script)
                self.assertNotIn("text", line)
                self.assertNotIn("b64", line)
                r = self.run_cli(script, "--list", "x")
                self.assertEqual(r.returncode, 2, script)
                self.assertIn("--list", self.run_cli(script, "--help").stdout, script)
        finally:
            B.link_list_from_session = saved

    def test_needs_to_or_all(self):
        # 2026-11-27 (the user): no broadcast by accident -- a bare `talkto "…"`
        # sends nothing and exits 1; --to and --all together are a usage error
        saved = B.link_list_from_session
        B.link_list_from_session = lambda sid: ("list", "つながっている相手(1人):\n「X」 Claude・devbox・動いている")
        try:
            for script in SCRIPTS:
                self.path.unlink(missing_ok=True)
                self.path.with_name("talkto_out.jsonl.offset").unlink(missing_ok=True)
                t = self.relay_once(("delivered", "relayed: must not happen")) if script == "talkto" else None
                r = self.run_cli(script, "やあ")
                if t:
                    t.join()
                self.assertEqual(r.returncode, 1, (script, r.stdout, r.stderr))
                self.assertIn("--all", r.stderr, script)
                self.assertFalse(any("text" in l or "b64" in l for l in self.lines()), script)
                if script == "talkto":
                    self.assertIn("「X」", r.stderr)  # who could be named
                for args in (["--to", "X", "--all", "x"], ["--all", "--to", "X", "x"]):
                    self.assertEqual(self.run_cli(script, *args).returncode, 2, (script, args))
                self.assertIn("--all", self.run_cli(script, "--help").stdout, script)
        finally:
            B.link_list_from_session = saved

    def test_backend_refuses_unaddressed_and_reads_remote_to(self):
        lines = [json.dumps({"id": "a1", "text": "x"}),
                 json.dumps({"id": "a2", "b64": B.base64.b64encode("y".encode()).decode(),
                             "to_b64": B.base64.b64encode("相手".encode()).decode()}),
                 json.dumps({"id": "a3", "text": "z", "all": True})]
        got = [t for _, t in B._parse_talkto_lines([l.encode() for l in lines])]
        self.assertEqual([(str(t), t.to, t.all) for t in got], [("x", None, False), ("y", "相手", False), ("z", None, True)])
        saved = B._load_links, B.load_meta
        B._load_links = lambda: {"L": {"members": ["s", "t"], "expires_ts": None}}
        B.load_meta = lambda sid: {"label": sid}
        try:
            status, msg = B._relay_to_partner("s", got[0])
            self.assertEqual(status, "need_to")
            self.assertIn("「t」", msg)
        finally:
            B._load_links, B.load_meta = saved

    def test_real_relay_without_link_says_so(self):
        saved = B._load_links
        B._load_links = lambda: {}
        try:
            self.assertEqual(B._relay_to_partner("s", "x")[0], "no_link")
        finally:
            B._load_links = saved


if __name__ == "__main__":
    unittest.main()
