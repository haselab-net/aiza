"""The desk's stage 2 (the deployment notes): the bot's dispatcher starts one
session per new report, on a branch of its own, and never reads a session
other than a devbox one."""
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


def report(nid, ref="h1/alice/devbox/0123456789ab", text="窓口が読む", **kw):
    return dict({"id": nid, "parent": "nd", "report": True, "state": "open", "title": "画面が崩れる",
                 "ball": {"kind": "ai", "text": text}, "links": {"ref": ref} if ref else {},
                 "report_pos": {"at": 1700000000, "events": 42, "seq": 50, "conv_line": 9}}, **kw)


class DeskDispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "sock").touch()
        self.nodes, self.sessions, self.started, self.calls = [], [], [], []

        def tree_call(req):
            self.calls.append(req)
            return {"nodes": self.nodes} if req["op"] == "list" else {"ok": True}

        def create_session(preset, label, cwd=None, auto=False, desk=None, **kw):
            self.started.append((preset, label, cwd, auto, desk))
            return {"id": "s%011d" % len(self.started)}

        stubs = {
            "DISPATCHER_LOG": tmp / "log.json",
            "TREE_SOCK": str(tmp / "sock"),
            "desk_conf": lambda: {"root": "nd"},
            "tree_call": tree_call,
            "list_sessions": lambda: self.sessions,
            "create_session": create_session,
            "prepare_branch_worktree": lambda o, r, b: f"{r}-wt/{b}",
            "share_session": lambda *a: None,
            "send_push_payload": lambda *a: None,
        }
        self.saved = {k: getattr(B, k) for k in stubs}
        for k, v in stubs.items():
            setattr(B, k, v)
        self.cfg = {"desk": {"repo": "o/aiza-priv"}}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def test_one_new_report_gets_a_session_on_its_own_branch(self):
        self.nodes = [report("n000000000001"), report("n000000000002")]
        r = B.dispatch_desk_once(self.cfg)
        self.assertIn("started", r)
        preset, label, cwd, auto, desk = self.started[0]
        self.assertEqual((preset, cwd, auto, desk["node"]), ("claude-tui", "aiza-priv-wt/desk-n000000000001", True, "n000000000001"))
        self.assertIn("aiza-session show alice/0123456789ab", desk["prompt"])
        self.assertIn("42 行目", desk["prompt"])
        self.assertIn("書き写さず", desk["prompt"])
        self.assertIn({"op": "update", "id": "n000000000001", "ball": {"kind": "ai", "text": "ボットが調べている"}}, self.calls)
        # the same report is never started twice, even after its session ended
        self.assertIn("n000000000002", B.dispatch_desk_once(self.cfg))
        self.started.clear()
        self.nodes = [report("n000000000001")]
        self.assertEqual(B.dispatch_desk_once(self.cfg), "nothing to do")

    def test_a_non_devbox_session_is_not_read(self):
        self.nodes = [report("n000000000003", ref="h1/alice/email/0123456789ab")]
        B.dispatch_desk_once(self.cfg)
        p = self.started[0][4]["prompt"]
        self.assertNotIn("aiza-session show", p)
        self.assertIn("読みません", p)

    def test_taken_done_or_others_are_left_alone(self):
        self.nodes = [report("n000000000004", text="ボットが調べている"), report("n000000000005", state="done"),
                      report("n000000000006", report=False), dict(report("n000000000007"), parent="nx")]
        self.assertEqual(B.dispatch_desk_once(self.cfg), "nothing to do")

    def test_limits(self):
        self.nodes = [report("n000000000008")]
        self.sessions = [{"id": "x", "desk": "n000000000009", "alive": True}]
        self.assertEqual(B.dispatch_desk_once(self.cfg), "desk: at max_concurrent")
        self.sessions = []
        self.cfg["desk"]["daily_limit"] = 0
        self.assertEqual(B.dispatch_desk_once(self.cfg), "desk: daily limit reached")
        self.assertEqual(B.dispatch_desk_once({}), "no desk")
        self.assertEqual(B.dispatch_desk_once({"desk": {}}), "desk: no repo")


class DeskSessionTest(unittest.TestCase):
    def test_only_the_dispatchers_own(self):
        for kw in ({}, {"auto": True}, {"auto": True, "cwd": "x", "desk": {"node": "bad", "prompt": "p"}}):
            with self.assertRaises(ValueError):
                B.create_session("claude-tui", "x", desk=kw.pop("desk", {"node": "n000000000001", "prompt": "p"}), **kw)


if __name__ == "__main__":
    unittest.main()
