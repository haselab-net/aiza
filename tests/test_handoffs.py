"""Handoffs followed until done (the plan's stage 2): a talkto that reached
another session, tracked once the sender ends its turn with
「済み — 〈相手〉へ引き継ぎ」, settled when the receiver declares 済み, closed
only by the sender.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {k: getattr(B, k) for k in ("HANDOFFS_PATH", "session_dir")}
        B.HANDOFFS_PATH = self.root / "handoffs.json"
        B.session_dir = lambda sid: self.root / sid
        for sid, label in (("aaaaaaaaaa01", "A"), ("bbbbbbbbbb01", "B")):
            (self.root / sid).mkdir()
            (self.root / sid / "meta.json").write_text(json.dumps({"id": sid, "label": label}))

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def test_tracked_settled_closed(self):
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "please  fix\\n the build", ts=100)
        self.assertEqual(B.handoffs_open(), [])              # not tracked until the sender says so
        B.handoff_turn_ended("aaaaaaaaaa01", {"state": "done", "text": "Bへ引き継ぎ"}, 90, 110)
        [h] = B.handoffs_open()
        self.assertEqual((h["from_label"], h["to_label"], h["head"], h["done_ts"]), ("A", "B", "please fix\\n the build", None))
        B.handoff_turn_ended("bbbbbbbbbb01", {"state": "snooze", "text": "x"}, 0, 150)
        self.assertIsNone(B.handoffs_open()[0]["done_ts"])   # waiting is not done
        B.handoff_turn_ended("bbbbbbbbbb01", {"state": "done", "text": "直した"}, 0, 200)
        self.assertEqual(B.handoffs_open()[0]["done_ts"], 200)
        self.assertTrue(B.handoff_close(h["id"]))
        self.assertEqual(B.handoffs_open(), [])
        self.assertFalse(B.handoff_close(h["id"]))

    def test_only_this_turn_and_only_a_handoff(self):
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "old", ts=10)
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "new", ts=100)
        B.handoff_turn_ended("aaaaaaaaaa01", {"state": "done", "text": "終わった"}, 90, 110)
        self.assertEqual(B.handoffs_open(), [])              # 済み without 引き継ぎ tracks nothing
        B.handoff_turn_ended("aaaaaaaaaa01", {"state": "done", "text": "Bへ引き継ぎ"}, 90, 110)
        self.assertEqual([h["head"] for h in B.handoffs_open()], ["new"])

    def test_bounded(self):
        for i in range(B.HANDOFF_KEEP + 20):
            B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", f"m{i}", ts=i)
        self.assertEqual(len(B._load_handoffs()), B.HANDOFF_KEEP)


class FakeTree:
    """The work-tree store as far as tree_handoff_branch uses it."""
    def __init__(self, me):
        self.me = me
        self.nodes = [{"id": "nroot", "parent": None, "owner": me, "title": "A's work",
                       "links": {"session": "aaaaaaaaaa01"}, "state": "open", "created_ts": 1}]
        self.n = 0

    def __call__(self, req):
        if req["op"] == "list":
            return {"nodes": [dict(x) for x in self.nodes], "teams": [dict(t) for t in getattr(self, "teams", [])]}
        if req["op"] == "add":
            self.n += 1
            node = {"id": f"n{self.n}", "parent": req["parent"], "owner": self.me, "title": req["title"],
                    "links": req["links"], "ball": req.get("ball"), "state": "open", "created_ts": 10 + self.n}
            self.nodes.append(node)
            return {"node": node}
        if req["op"] == "update":
            node = next(x for x in self.nodes if x["id"] == req["id"])
            node.update({k: v for k, v in req.items() if k not in ("op", "id")})
            return {"node": node}
        raise AssertionError(req)

    def branches(self):
        return [x for x in self.nodes if x["links"].get("handoff")]


class HandoffBranchTest(unittest.TestCase):
    """One branch per receiver (2026-11-18, the user: talkto のたびに木の枝が増える)."""
    def setUp(self):
        import getpass
        import threading
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        sock = self.root / "tree.sock"
        sock.write_text("")
        self.tree = FakeTree(getpass.getuser())
        names = ("HANDOFFS_PATH", "session_dir", "TREE_SOCK", "tree_call", "load_task")
        self.saved = {k: getattr(B, k) for k in names}
        B.HANDOFFS_PATH = self.root / "handoffs.json"
        B.session_dir = lambda sid: self.root / sid
        B.TREE_SOCK = str(sock)
        B.tree_call = self.tree
        B.load_task = lambda sid: None
        for sid, label in (("aaaaaaaaaa01", "A"), ("bbbbbbbbbb01", "B"), ("cccccccccc01", "C")):
            (self.root / sid).mkdir()
            (self.root / sid / "meta.json").write_text(json.dumps({"id": sid, "label": label}))

        class Now:  # run the branch's background thread right away
            def __init__(self, target, args=(), daemon=None):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)
        self.thread = threading.Thread
        threading.Thread = Now

    def tearDown(self):
        import threading
        threading.Thread = self.thread
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def end_turn(self, t0, t1):
        B.handoff_turn_ended("aaaaaaaaaa01", {"state": "done", "text": "Bへ引き継ぎ"}, t0, t1)

    def test_two_in_one_turn_make_one_branch(self):
        self.retitled = []
        saved = B.tree_retitle
        B.tree_retitle = lambda i, text, made_as: self.retitled.append((i, text, made_as))
        self.addCleanup(lambda: setattr(B, "tree_retitle", saved))
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "first message to B, which is quite a long one " * 3, ts=100)
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "second", ts=101)
        B.handoff_record("aaaaaaaaaa01", "cccccccccc01", "to C", ts=102)
        self.end_turn(90, 110)
        br = self.tree.branches()
        self.assertEqual(sorted(x["links"]["session"] for x in br), ["bbbbbbbbbb01", "cccccccccc01"])
        b = next(x for x in br if x["links"]["session"] == "bbbbbbbbbb01")
        self.assertEqual(b["parent"], "nroot")
        # About 20 characters of what it is about (a summary replaces it later);
        # to whom shows beside it in the tree (2026-11-22).
        self.assertTrue(b["title"].startswith("first message"))
        self.assertLessEqual(len(b["title"]), B.SHORT_TITLE + 1)
        self.assertEqual([x for x in self.retitled if x[0] == b["id"]][0][2], b["title"])
        self.assertEqual({h["branch"] for h in B._load_handoffs() if h["to"] == "bbbbbbbbbb01"}, {b["id"]})

    def test_open_branch_is_reused(self):
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "one", ts=100)
        self.end_turn(90, 110)
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "two", ts=200)
        self.end_turn(190, 210)
        [b] = self.tree.branches()
        self.assertEqual({h["branch"] for h in B._load_handoffs()}, {b["id"]})
        # Once that branch is finished, the next handoff gets a new one.
        b["state"] = "done"
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "three", ts=300)
        self.end_turn(290, 310)
        self.assertEqual(len(self.tree.branches()), 2)

    def test_to_a_helper_of_its_team_makes_no_branch(self):
        # 🤝 B helps A (the deployment notes): handing work to B is the team's
        # own (2026-11-27, the user: 細かい枝ができすぎないようにしたい); C is
        # not in the team and gets its branch as before.
        import getpass
        self.tree.nodes[0]["helpers"] = [{"owner": getpass.getuser(), "session": "bbbbbbbbbb01"}]
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "to B", ts=100)
        B.handoff_record("aaaaaaaaaa01", "cccccccccc01", "to C", ts=101)
        self.end_turn(90, 110)
        self.assertEqual([x["links"]["session"] for x in self.tree.branches()], ["cccccccccc01"])

    def test_to_a_helper_while_its_leads_item_is_closed_makes_no_branch(self):
        # The store leaves the helpers off an item closed by its done ball (or
        # someone's その他): the team itself says who helps (2026-11-27: a
        # handoff to the helper 読み上げ made a branch).
        import getpass
        me = getpass.getuser()
        self.tree.nodes[0].update(state="done", ball={"kind": "done"})
        self.tree.teams = [{"lead": {"owner": me, "session": "aaaaaaaaaa01"}, "helpers": [{"owner": me, "session": "bbbbbbbbbb01"}]}]
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "to B", ts=100)
        B.handoff_record("aaaaaaaaaa01", "cccccccccc01", "to C", ts=101)
        self.end_turn(90, 110)
        self.assertEqual([x["links"]["session"] for x in self.tree.branches()], ["cccccccccc01"])

    def test_a_plain_done_makes_no_branch(self):
        B.handoff_record("aaaaaaaaaa01", "bbbbbbbbbb01", "反映しました", ts=100)
        B.handoff_turn_ended("aaaaaaaaaa01", {"state": "done", "text": "反映を知らせた"}, 90, 110)
        self.assertEqual(self.tree.branches(), [])


if __name__ == "__main__":
    unittest.main()
