"""The desk's automatic deploy (aiza-desk-deploy): which of the bot's
changes may go out without a person looking."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("aiza_desk_deploy", str(ROOT / "bin" / "aiza-desk-deploy"))
D = importlib.util.module_from_spec(importlib.util.spec_from_loader("aiza_desk_deploy", _loader))
_loader.exec_module(D)

OLD = """import os

X = 1


def render_row(n):
    a = n + 1
    return a


def share_session(sid, u):
    return sid
"""


PRESETS_SRC = """import os

TMUX_PRESETS = {
    "codex-tui": {"command": ["codex"], "location": "container", "width": 100},
    "host-shell": {"command": ["bash"], "location": "host"},
}


def f():
    return 1
"""


def diff_of(old_line, new_text):
    return f"--- a/bin/aiza-backend\n+++ b/bin/aiza-backend\n@@ -{old_line} +{old_line} @@\n-old\n+{new_text}\n"


class RuleTest(unittest.TestCase):
    def test_links_submodules_and_mode_changes_are_refused_even_under_tests(self):
        z = "0" * 40
        raw = lambda old, new, path, st="M": f":{old} {new} {z} {z} {st}\t{path}\n"
        self.assertIsNone(D.check_modes(raw("100644", "100644", "static/app.js") + raw("000000", "100644", "tests/t.py", "A")))
        self.assertIn("リンク", D.check_modes(raw("000000", "120000", "tests/x", "A")))
        self.assertIn("リンク", D.check_modes(raw("100644", "120000", "tests/t.py", "T")))
        self.assertIn("サブモジュール", D.check_modes(raw("000000", "160000", "tests/m", "A")))
        self.assertIn("モード", D.check_modes(raw("100644", "100755", "static/app.js")))

    def test_tools_that_root_and_host_sessions_run_and_deleted_tests_wait_for_a_person(self):
        for tool in D.BOX_TOOLS:
            self.assertIn("人が配備する", D.check_change([("M", f"bin/{tool}")]))
        self.assertIn("テストを消している", D.check_change([("M", "static/app.js"), ("D", "tests/test_x.py")]))

    def test_renames_out_of_tests_and_odd_lines_wait(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            g = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, text=True).stdout
            g("init", "-q", "-b", "main"); g("config", "user.email", "t@example.org"); g("config", "user.name", "t")
            os.makedirs(f"{d}/tests"); open(f"{d}/tests/x.py", "w").write("print(1)\n" * 20)
            g("add", "."); g("commit", "-qm", "a")
            g("checkout", "-qb", "req"); os.makedirs(f"{d}/.github/workflows")
            g("mv", "tests/x.py", ".github/workflows/x.yml"); g("commit", "-qm", "b")
            saved = D.git
            D.git = lambda *a, cwd=None, check=True: g(*a)
            try:
                files = D.changed_files(d, "req")
            finally:
                D.git = saved
            self.assertEqual(sorted(files), [("A", ".github/workflows/x.yml"), ("D", "tests/x.py")])
            self.assertIsNotNone(D.check_change(files))
        self.assertIn("読めない", D.check_change([("?", "R100\ttests/x\tbin/y")]))
        self.assertIn("標準のモジュール", D.check_change([("M", "static/app.js"), ("A", "tests/json.py")]))
        self.assertIsNone(D.check_change([("M", "static/app.js"), ("A", "tests/test_json_things.py")]))

    def test_ways_around_subprocess_in_the_backend_wait(self):
        for line in ("    os.popen(c)", "    os.execv(p, a)", "    import pty", "    ctypes.CDLL(x)",
                     "    importlib.import_module(m)", "    __import__(m)", "    eval(x)", "    exec(x)", "    compile(x, 'f', 'exec')"):
            new = OLD.replace("a = n + 1", line.strip())
            self.assertIsNotNone(D.check_change([("M", "bin/aiza-backend")], diff_of(7, line), OLD, new), line)

    def test_static_and_tests_go(self):
        self.assertIsNone(D.check_change([("M", "static/app.js"), ("A", "tests/test_x.py"), ("M", "static/i18n.js")]))

    def test_other_places_wait_for_a_person(self):
        for files in ([("M", "bin/aiza-gateway")], [("M", "systemd/aiza-backend@.service")], [("A", "static/new.js")],
                      [("D", "static/app.js")], [("M", "static/vendor/x.js")], [("M", "CLAUDE.md")], []):
            self.assertIsNotNone(D.check_change(files), files)

    def test_backend_inside_an_ordinary_function_goes(self):
        new = OLD.replace("a = n + 1", "a = n + 2")
        self.assertIsNone(D.check_change([("M", "bin/aiza-backend")], diff_of(7, "    a = n + 2"), OLD, new))

    def test_backend_in_a_sharing_function_or_module_level_waits(self):
        new = OLD.replace("return sid", "return sid or u")
        self.assertIn("share_session", D.check_change([("M", "bin/aiza-backend")], diff_of(12, "    return sid or u"), OLD, new))
        new = OLD.replace("X = 1", "X = 2")
        self.assertIn("関数の外", D.check_change([("M", "bin/aiza-backend")], diff_of(3, "X = 2"), OLD, new))

    def test_backend_lines_that_touch_the_edge_wait(self):
        new = OLD.replace("a = n + 1", "a = subprocess.run(n)")
        self.assertIn("subprocess", D.check_change([("M", "bin/aiza-backend")], diff_of(7, "    a = subprocess.run(n)"), OLD, new))

    def test_no_tool_of_bin_goes_but_the_backend(self):
        # the box tools too since 2026-11-24 (root's and the host's sessions run the same files)
        for t in ("talkto", "aiza-tree", "aiza-session", "aiza-board", "aiza-task-hook", "aiza-codex-hook"):
            self.assertIsNotNone(D.check_change([("M", f"bin/{t}")]), t)
        for t in ("aiza-ask-hook", "aiza-gate-hook", "aiza-out", "aiza-codex-mailbox-guard", "aiza-tree-store",
                  "aiza-discord-dm"):
            self.assertIsNotNone(D.check_change([("M", f"bin/{t}")]), t)
        self.assertIsNotNone(D.check_change([("A", "bin/aiza-new-tool")]))
        self.assertIn("bin/aiza-tree)", D.PEER_SCRIPT.replace("|", ")"))

    def test_module_level_comments_go(self):
        new = OLD.replace("X = 1", "# why X\nX = 1")
        self.assertIsNone(D.check_change([("M", "bin/aiza-backend")],
                                         "@@ -2,0 +3 @@\n+# why X\n", OLD, new))

    def test_box_preset_arguments_go_the_rest_waits(self):
        old = PRESETS_SRC
        ok = old.replace('["codex"]', '["codex", "--no-daemon"]')
        self.assertIsNone(D.check_change([("M", "bin/aiza-backend")], diff_of(4, "x"), old, ok))
        for new, why in ((old.replace('["codex"]', '["sh", "-c", "x"]'), "コマンド"),
                         (old.replace('["codex"]', '["codex", X]'), "コマンド"),
                         (old.replace('"location": "container", "width"', '"location": "root", "width"'), "箱の外"),
                         (old.replace('["bash"], "location": "host"', '["bash", "-x"], "location": "host"'), "箱の外"),
                         (old.replace('"width": 100', '"width": 100, "env": ["A=1"]'), "引数以外"),
                         (old.replace('"host"},\n}', '"host"},\n    "new": {"command": ["x"], "location": "container"},\n}'), "足すか")):
            self.assertIn(why, D.check_change([("M", "bin/aiza-backend")], diff_of(4, "x"), old, new) or "", new)

    def test_enclosing_def(self):
        lines = OLD.splitlines()
        self.assertEqual(D.enclosing_def(lines, 6), "render_row")
        self.assertEqual(D.enclosing_def(lines, 5), "render_row")
        self.assertIsNone(D.enclosing_def(lines, 2))
        self.assertIsNone(D.enclosing_def(lines, 99))


class ReadyTest(unittest.TestCase):
    def test_only_reports_whose_bot_handed_back_a_fix(self):
        nodes = [{"id": "r1", "parent": "nd", "report": True, "state": "open"},
                 {"id": "c1", "parent": "r1", "state": "open", "ball": {"kind": "person", "text": "窓口: 直した版の確認"}},
                 {"id": "r2", "parent": "nd", "report": True, "state": "open"},
                 {"id": "c2", "parent": "r2", "state": "open", "ball": {"kind": "person", "text": "窓口: 仕分けた"}},
                 {"id": "r3", "parent": "nd", "report": True, "state": "done"},
                 {"id": "c3", "parent": "r3", "state": "open", "ball": {"kind": "person", "text": "窓口: 直した版の確認"}}]
        self.assertEqual([n["id"] for n in D.ready_reports(nodes, "nd")], ["r1"])


class RequestTest(unittest.TestCase):
    D = {"repo": "/home/alice/sandhome/aiza", "sha": "a" * 40}

    def rep(self, **kw):
        return dict({"id": "r1", "parent": "nd", "report": True, "state": "open", "owner": "alice",
                     "links": {"ref": "host2/alice/devbox/0123456789ab"}, "deploy": self.D,
                     "ball": {"kind": "ai", "text": D.DEPLOY_WAITING}}, **kw)

    def test_only_open_requests_still_waiting(self):
        nodes = [self.rep(), self.rep(id="r2", state="done"), self.rep(id="r3", ball={"kind": "ai", "text": "窓口が読む"}),
                 self.rep(id="r4", deploy=None)]
        self.assertEqual([n["id"] for n in D.deploy_requests(nodes, "nd")], ["r1"])

    def test_where_to_fetch_from(self):
        self.assertEqual(D.request_source(self.rep(), "host1", ["host2.lan"]), ("host2.lan", "alice", self.D["repo"], "a" * 40))
        self.assertEqual(D.request_source(self.rep(), "host2", []), (None, "alice", self.D["repo"], "a" * 40))
        self.assertIsInstance(D.request_source(self.rep(), "host1", []), str)            # no such peer
        self.assertIsInstance(D.request_source(self.rep(owner="bob"), "host2", []), str)  # not the sender's session
        self.assertIsInstance(D.request_source(self.rep(deploy={"repo": "/a/../b", "sha": "a" * 40}), "host2", []), str)

    def test_the_ball_goes_to_the_desks_people(self):
        nodes = [{"id": "nd", "members": ["bot", "alice", "root"]}, self.rep(), {"id": "k", "parent": "r1", "owner": "x"}]
        self.assertEqual(D.desk_people(nodes, {"root": "nd"}, "r1"), ["bot", "alice"])
        self.assertEqual(D.desk_people(nodes, {"root": "nd", "people": ["alice"]}, "r1"), ["alice"])

    def test_fetch_runs_git_as_the_sender(self):
        calls = []
        saved = D.git
        D.git = lambda *a, cwd=None, check=True: calls.append(a) or ""
        try:
            D.fetch_request("/bare", "r1", ("host2", "alice", "/h/a", "a" * 40))
            D.fetch_request("/bare", "r1", (None, "alice", "/h/a", "a" * 40))
        finally:
            D.git = saved
        self.assertIn("--upload-pack=sudo -n -u alice git -c uploadpack.allowAnySHA1InWant=true upload-pack", calls[0])
        self.assertIn("ssh://host2/h/a", calls[0])
        self.assertIn("+" + "a" * 40 + ":refs/req/r1", calls[0])
        self.assertTrue(any(x.startswith("--upload-pack=runuser -u alice --") for x in calls[1]))
        self.assertIn("/h/a", calls[1])

if __name__ == "__main__":
    unittest.main()
