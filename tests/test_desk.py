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

    def _gh(self, sha, state="OPEN"):
        """A stand-in gh on PATH: one open pull request, #7, at `sha`."""
        bindir = Path(self.tmp.name) / "bin"
        bindir.mkdir(exist_ok=True)
        gh = bindir / "gh"
        pr = {"number": 7, "title": "直した", "headRefName": "fix", "headRefOid": sha}
        gh.write_text("#!/bin/sh\n"
                      f"if [ \"$2\" = list ]; then echo '{json.dumps([pr])}'; else echo '{json.dumps({'headRefOid': sha, 'state': state})}'; fi\n")
        gh.chmod(0o755)
        self.saved_path = os.environ["PATH"]
        os.environ["PATH"] = f"{bindir}:{self.saved_path}"
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self.saved_path))
        B._desk_gh_env = lambda meta: dict(os.environ, GH_CONFIG_DIR=str(bindir))
        self.addCleanup(lambda: setattr(B, "_desk_gh_env", self.saved_gh_env))

    def setUp_gh_env(self):
        self.saved_gh_env = B._desk_gh_env

    def test_a_deploy_request_names_a_branch_resolved_here(self):
        d, sha = self._repo()
        self.metas["0123456789ab"]["cwd"] = str(d)
        self.metas["0123456789ab"]["tmux_location"] = "host"
        self.write(root="nd", readers=["desk1"])
        branch = B.subprocess.run(["git", "-C", str(d), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        B.desk_report("直した", "0123456789ab", what="deploy", pick={"branch": branch})
        self.assertEqual(self.calls[0]["deploy"], {"repo": str(d.resolve()), "sha": sha})
        for bad in ({"branch": "no-such"}, {"branch": "-x"}, {"branch": "a..b"}, {}, {"branch": "x", "pull": 1}, "main", None):
            with self.assertRaises(ValueError):
                B.desk_report("直した", "0123456789ab", what="deploy", pick=bad)
        with self.assertRaises(ValueError):   # a typed sha is not taken any more
            B.desk_report("直した", "0123456789ab", commit=sha[:8])

    def test_a_deploy_request_names_an_open_pull_request(self):
        self.setUp_gh_env()
        d, sha = self._repo()
        self.metas["0123456789ab"].update(cwd=str(d), tmux_location="host")
        self.write(root="nd")
        self._gh(sha)
        got = B.desk_choices("0123456789ab")
        self.assertEqual([p["number"] for p in got["pulls"]], [7])
        self.assertEqual(len(got["branches"]), 1)
        B.desk_report("直した", "0123456789ab", what="deploy", pick={"pull": 7})
        self.assertEqual(self.calls[0]["deploy"]["sha"], sha)
        for bad in ({"pull": "7"}, {"pull": 0}, {"pull": True}):
            with self.assertRaises(ValueError):
                B.desk_report("直した", "0123456789ab", what="deploy", pick=bad)

    def test_a_closed_pull_request_is_refused(self):
        self.setUp_gh_env()
        d, sha = self._repo()
        self.metas["0123456789ab"].update(cwd=str(d), tmux_location="host")
        self.write(root="nd")
        self._gh(sha, state="MERGED")
        with self.assertRaises(ValueError):
            B.desk_report("直した", "0123456789ab", what="deploy", pick={"pull": 7})
        self.assertEqual(self.calls, [])

    def test_without_a_gh_login_only_branches_are_offered(self):
        self.setUp_gh_env()
        d, sha = self._repo()
        self.metas["0123456789ab"].update(cwd=str(d), tmux_location="host")
        B._desk_gh_env = lambda meta: {"PATH": os.environ["PATH"]}
        self.addCleanup(lambda: setattr(B, "_desk_gh_env", self.saved_gh_env))
        got = B.desk_choices("0123456789ab")
        self.assertEqual(got["pulls"], [])
        self.assertTrue(got["pulls_note"])
        self.assertEqual(got["branches"][0]["sha"], sha)

    def test_not_a_repository_offers_nothing(self):
        self.metas["0123456789ab"].update(cwd=self.tmp.name, tmux_location="host")
        got = B.desk_choices("0123456789ab")
        self.assertEqual((got["repo"], got["branches"], got["pulls"]), (None, [], []))

    def test_a_report_carries_no_commit(self):
        self.write(root="nd")
        B.desk_report("動かない", "0123456789ab", what="report")
        self.assertNotIn("deploy", self.calls[0])

    def test_a_deploy_request_rides_along_to_the_other_hosts_desk(self):
        d, sha = self._repo()
        self.metas["0123456789ab"].update(cwd=str(d), tmux_location="host")
        self.write(url="https://desk.example/agents/")
        branch = B.subprocess.run(["git", "-C", str(d), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
        r = B.desk_report("直した", "0123456789ab", what="deploy", pick={"branch": branch})
        self.assertIn("c=", r["desk_url"])
        self.assertIn("l=", r["desk_url"])     # what was picked, shown on the desk's page
        self.write(root="nd")
        me = B.getpass.getuser()
        c = json.dumps({"repo": "/home/x/aiza", "sha": sha})
        B.desk_report("直した", ref=f"other/{me}/devbox/0123456789ab", commit=c, what="deploy")
        self.assertEqual(self.calls[0]["deploy"], {"repo": "/home/x/aiza", "sha": sha})
        with self.assertRaises(ValueError):   # someone else's session
            B.desk_report("直した", ref="other/zz-nobody/devbox/0123456789ab", commit=c)
        with self.assertRaises(ValueError):   # a deploy request with nothing to deploy
            B.desk_report("直した", ref=f"other/{me}/devbox/0123456789ab", what="deploy")
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
