"""The desk's intake in the backend (the deployment notes): a report with a link
to one's session; only a devbox session is shared, read-only, with the desk."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


class DeskIntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conf = Path(self.tmp.name) / "desk.json"
        self.calls, self.shared = [], []
        self.metas = {"0123456789ab": {"preset": "claude-tui", "tmux_location": "container"},
                      "abcdef012345": {"preset": "mail-tui", "tmux_location": "host"}}
        stubs = {
            "DESK_CONF": self.conf,
            "tree_call": lambda req: self.calls.append(req) or {"ok": True, "node": {"id": "n1"}},
            "load_meta": lambda sid: self.metas.get(sid),
            "share_session": lambda sid, u, mode="write": self.shared.append((sid, u, mode)),
            "session_pos": lambda sid, meta: {"at": 1700000000, "events": 42, "seq": 50},
            "append_event": lambda sid, ev: self.events.append((sid, ev)),
        }
        self.events = []
        self.saved = {k: getattr(B, k) for k in stubs}
        for k, v in stubs.items():
            setattr(B, k, v)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def write(self, **conf):
        self.conf.write_text(json.dumps(conf))

    def test_devbox_report_is_shared_with_the_readers_only(self):
        self.write(root="nd", readers=["desk1"])
        B.desk_report("画面が崩れる", "0123456789ab")
        req = self.calls[0]
        self.assertEqual((req["op"], req["desk"], req["title"]), ("report", "nd", "画面が崩れる"))
        self.assertTrue(req["ref"].endswith("/devbox/0123456789ab"))
        self.assertEqual(self.shared, [("0123456789ab", "desk1", "read")])

    def test_email_session_is_a_link_only(self):
        self.write(root="nd", readers=["desk1"])
        B.desk_report("届かない", "abcdef012345")
        self.assertTrue(self.calls[0]["ref"].endswith("/email/abcdef012345"))
        self.assertEqual(self.shared, [])

    def test_the_time_and_log_position_go_with_the_report_and_the_spot_is_marked(self):
        self.write(root="nd", readers=["desk1"])
        B.desk_report("届かない", "abcdef012345")
        self.assertEqual(self.calls[0]["pos"], {"at": 1700000000, "events": 42, "seq": 50})
        sid, ev = self.events[0]
        self.assertEqual((sid, ev["type"]), ("abcdef012345", "system"))
        self.assertIn("n1", ev["text"])
        self.assertNotIn("届かない", ev["text"])

    def test_the_position_rides_along_to_the_other_hosts_desk(self):
        self.write(url="https://desk.example/agents/")
        r = B.desk_report("直したい", "0123456789ab")
        self.assertIn("pos=", r["desk_url"])
        self.write(root="nd")
        B.desk_report("直したい", ref="other/alice/devbox/0123456789ab", pos='{"at":1,"events":3,"conv":"abcdefgh-1234"}')
        self.assertEqual(self.calls[0]["pos"], {"at": 1, "events": 3, "conv": "abcdefgh-1234"})
        for bad in ('{"text":"x"}', '{"events":"3"}', '{"conv":"../x"}', "[1]", "{"):
            with self.assertRaises(ValueError):
                B.desk_report("x", ref="other/alice/devbox/0123456789ab", pos=bad)

    def test_without_the_tree_the_report_goes_to_the_desks_page(self):
        self.write(url="https://desk.example/agents/")
        r = B.desk_report("直したい", "0123456789ab")
        self.assertTrue(r["desk_url"].startswith("https://desk.example/agents/#desk&"))
        self.assertIn("devbox%2F0123456789ab", r["desk_url"])
        self.assertEqual(self.calls, [])

    def test_a_ref_from_the_other_host_is_kept_as_is(self):
        self.write(root="nd", readers=["desk1"])
        B.desk_report("x", ref="other/alice/devbox/0123456789ab")
        self.assertEqual(self.calls[0]["ref"], "other/alice/devbox/0123456789ab")
        self.assertEqual(self.shared, [])
        with self.assertRaises(ValueError):
            B.desk_report("x", ref="../etc")

    def _repo(self):
        import subprocess
        d = Path(self.tmp.name) / "repo"
        d.mkdir()
        env = dict(os.environ, GIT_AUTHOR_NAME="a", GIT_AUTHOR_EMAIL="a@x", GIT_COMMITTER_NAME="a",
                   GIT_COMMITTER_EMAIL="a@x", GIT_CONFIG_GLOBAL="/dev/null")
        subprocess.run(["git", "init", "-q", str(d)], check=True, env=env)
        subprocess.run(["git", "-C", str(d), "commit", "-q", "--allow-empty", "-m", "fix"], check=True, env=env)
        sha = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=True, env=env).stdout.strip()
        return d, sha

    def test_a_deploy_request_names_the_commit_in_the_sessions_folder(self):
        d, sha = self._repo()
        self.metas["0123456789ab"]["cwd"] = str(d)
        self.write(root="nd", readers=["desk1"])
        B.desk_report("直した", "0123456789ab", commit=sha[:8])
        self.assertEqual(self.calls[0]["deploy"], {"repo": str(d.resolve()), "sha": sha})
        self.calls.clear()
        B.desk_report("直した", "0123456789ab", commit=f"{d} {sha[:10]}")
        self.assertEqual(self.calls[0]["deploy"]["sha"], sha)
        for bad in ("zzzz", f"{d} {sha} x", "deadbeef0"):
            with self.assertRaises(ValueError):
                B.desk_report("直した", "0123456789ab", commit=bad)

    def test_a_deploy_request_rides_along_to_the_other_hosts_desk(self):
        d, sha = self._repo()
        self.metas["0123456789ab"]["cwd"] = str(d)
        self.write(url="https://desk.example/agents/")
        r = B.desk_report("直した", "0123456789ab", commit=sha)
        self.assertIn("c=", r["desk_url"])
        self.write(root="nd")
        me = B.getpass.getuser()
        c = json.dumps({"repo": "/home/x/aiza", "sha": sha})
        B.desk_report("直した", ref=f"other/{me}/devbox/0123456789ab", commit=c)
        self.assertEqual(self.calls[0]["deploy"], {"repo": "/home/x/aiza", "sha": sha})
        with self.assertRaises(ValueError):   # someone else's session
            B.desk_report("直した", ref="other/zz-nobody/devbox/0123456789ab", commit=c)
        for bad in ('{"repo":"/a/../b","sha":"%s"}' % sha, '{"repo":"/a","sha":"abc"}', "{"):
            with self.assertRaises(ValueError):
                B.desk_report("直した", ref=f"other/{me}/devbox/0123456789ab", commit=bad)

    def test_no_desk_no_text_no_session(self):
        with self.assertRaises(ValueError):
            B.desk_report("x")
        self.write(root="nd")
        with self.assertRaises(ValueError):
            B.desk_report("  ")
        with self.assertRaises(ValueError):
            B.desk_report("x", "ffffffffffff")


class SessionPosTest(unittest.TestCase):
    """Counts and ids only: never a line's content."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "s").mkdir()
        (root / "s" / "events.jsonl").write_text('{"seq": 1}\n{"seq": 7}\n{"seq": 3}\n')
        proj = root / "home" / ".claude" / "projects" / "-x"
        proj.mkdir(parents=True)
        (proj / "abcdefgh-1234.jsonl").write_text("a\nb\n")
        stubs = {
            "session_dir": lambda sid, *a, **k: root / "s",
            "sb_open": lambda path, mode="r", perm=None, **k: open(path, mode, **k),
            "_claude_home_for_location": lambda loc: root / "home",
        }
        self.saved = {k: getattr(B, k) for k in stubs}
        for k, v in stubs.items():
            setattr(B, k, v)
        B._next_seq.pop("0123456789ab", None)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def test_counts_lines_of_the_chat_and_claudes_log(self):
        p = B.session_pos("0123456789ab", {"tmux_location": "container", "claude_session_id": "abcdefgh-1234"})
        self.assertEqual((p["events"], p["seq"], p["conv"], p["conv_line"]), (3, 7, "abcdefgh-1234", 2))
        self.assertIsInstance(p["at"], int)

    def test_no_claude_log(self):
        p = B.session_pos("0123456789ab", {"tmux_location": "container"})
        self.assertEqual(set(p), {"at", "events", "seq"})


if __name__ == "__main__":
    unittest.main()
