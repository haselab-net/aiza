"""A repository's issues as branches of the work tree (the plan's stage 4).

    python3 -m unittest discover -s tests -v
"""
import getpass
import tempfile
import unittest

from test_shared_search import B
from test_tree_store import load


def issue(n, title, state="OPEN", parent=None, assignees=(), **fields):
    return {"number": n, "title": title, "state": state, "parent": {"number": parent} if parent else None,
            "assignees": {"nodes": [{"login": a} for a in assignees]},
            "projectItems": {"nodes": [{"fieldValues": {"nodes": [
                {"name": v, "field": {"name": k}} for k, v in fields.items()]}}] if fields else []}}


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.S.in_lab = lambda u: True
        self.me = getpass.getuser()
        self.issues = [
            issue(1, "Stage 1"),
            issue(7, "第5段", parent=1),
            issue(12, "TTS", parent=7, assignees=["example-bot"], Status="In progress", Worker="Claude"),
            issue(13, "実機テスト", parent=7, Status="Blocked"),
            issue(3, "第1段", state="CLOSED"),
        ]
        self.saved = (B.tree_call, B._repo_issues, B._issue_sessions, B.BOT_LOGINS)
        B.BOT_LOGINS = ("example-bot",)
        B.tree_call = lambda req: self.S.handle(self.me, req)
        B._repo_issues = lambda o, r: self.issues
        B._issue_sessions = lambda ref, alive_only=True: []
        self.root = B.tree_call({"op": "add", "title": "webapp", "links": {"repo": "example-org/webapp"}})["node"]

    def tearDown(self):
        B.tree_call, B._repo_issues, B._issue_sessions, B.BOT_LOGINS = self.saved
        self.tmp.cleanup()

    def nodes(self):
        return {(n.get("links") or {}).get("issue"): n for n in B.tree_call({"op": "list"})["nodes"]}

    def test_branches_follow_sub_issues_and_fields(self):
        self.assertEqual(B.tree_sync_repo(self.root), 5)
        n = self.nodes()
        ref = lambda i: f"example-org/webapp#{i}"
        self.assertEqual(n[ref(1)]["parent"], self.root["id"])
        self.assertEqual(n[ref(12)]["parent"], n[ref(7)]["id"])
        self.assertEqual(n[ref(12)]["ball"]["kind"], "ai")
        self.assertEqual((n[ref(13)]["ball"]["kind"], n[ref(13)]["ball"]["who"]), ("person", self.me))
        self.assertEqual(n[ref(3)]["state"], "done")
        self.assertEqual(n[ref(7)]["title"], "#7 第5段")
        self.assertEqual(B.tree_sync_repo(self.root), 0)            # nothing changed: nothing written

    def test_changes_and_members_follow(self):
        B.tree_sync_repo(self.root)
        self.root = B.tree_call({"op": "update", "id": self.root["id"], "members": ["carol"]})["node"]
        self.issues[2] = issue(12, "TTS", state="CLOSED", parent=7)
        B.tree_sync_repo(self.root)
        n = self.nodes()
        self.assertEqual(n["example-org/webapp#12"]["state"], "done")
        self.assertEqual(n["example-org/webapp#7"]["members"], ["carol"])

    def test_a_session_on_the_issue_holds_the_ball(self):
        B._issue_sessions = lambda ref, alive_only=True: [{"id": "aaaaaaaaaa01", "created_ts": 1}] if ref.endswith("#13") else []
        B.tree_sync_repo(self.root)
        n = self.nodes()["example-org/webapp#13"]
        self.assertEqual(n["links"]["session"], "aaaaaaaaaa01")
        self.assertIsNone(n["ball"])                                # left to the session's own state


class FromSessionTest(unittest.TestCase):
    """aiza-tree find / link from inside a session, and the start rule."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.me = getpass.getuser()
        self.saved = (B.tree_call, B.load_meta, B.load_task)
        B.tree_call = lambda req: self.S.handle(self.me, req)
        B.load_meta = lambda sid: {"id": sid, "label": "セッション"}
        B.load_task = lambda sid: {"state": "working"}
        self.plan = B.tree_call({"op": "add", "title": "aiza の改善"})["node"]
        self.st4 = B.tree_call({"op": "add", "title": "段 4: Robot を入れる", "parent": self.plan["id"]})["node"]

    def tearDown(self):
        B.tree_call, B.load_meta, B.load_task = self.saved
        self.tmp.cleanup()

    def test_find_and_take_on(self):
        st, msg = B.tree_from_session("aaaaaaaaaa01", {"cmd": "find", "q": "robot 改善"})
        self.assertEqual(st, "ok")
        self.assertIn(self.st4["id"], msg)                     # matched through its parent's title
        st, msg = B.tree_from_session("aaaaaaaaaa01", {"cmd": "link", "id": self.st4["id"]})
        n = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}[self.st4["id"]]
        self.assertEqual((n["links"]["session"], n["ball"]["kind"]), ("aaaaaaaaaa01", "ai"))
        # Another session on the same item: a child of its own.
        B.tree_from_session("bbbbbbbbbb01", {"cmd": "link", "id": self.st4["id"]})
        kids = [x for x in B.tree_call({"op": "list"})["nodes"] if x.get("parent") == self.st4["id"]]
        # ...and the first session stays on the item itself (no その他 until
        # it goes on working on it, 2026-11-22).
        self.assertEqual(sorted((bool(k.get("rest")), k["links"]["session"]) for k in kids),
                         [(False, "bbbbbbbbbb01")])
        n = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}[self.st4["id"]]
        self.assertEqual(n["links"]["session"], "aaaaaaaaaa01")

    def test_split_from_the_rest_goes_under_its_parent(self):
        B.tree_from_session("aaaaaaaaaa01", {"cmd": "link", "id": self.st4["id"]})
        B.tree_from_session("aaaaaaaaaa01", {"cmd": "split", "title": "A"})
        st, msg = B.tree_from_session("aaaaaaaaaa01", {"cmd": "split", "title": "B"})
        self.assertIn("段 4", msg)
        kids = [x for x in B.tree_call({"op": "list"})["nodes"] if x.get("parent") == self.st4["id"]]
        self.assertEqual(sorted(k["title"] for k in kids), ["A", "B"])     # no その他 (2026-11-22)
        st, msg = B.tree_from_session("aaaaaaaaaa01", {})
        self.assertIn("段 4", msg.splitlines()[0])                       # the session holds it itself
        # done without an id: only the session's own part; the node waits for A and B.
        B.tree_from_session("aaaaaaaaaa01", {"cmd": "done"})
        ns = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}
        self.assertEqual((ns[self.st4["id"]]["state"], ns[self.st4["id"]]["ball"]["kind"]), ("open", "done"))
        self.assertTrue(all(k["state"] == "open" for k in ns.values() if k.get("parent") == self.st4["id"]))
        for k in [k for k in ns.values() if k.get("parent") == self.st4["id"]]:
            B.tree_call({"op": "update", "id": k["id"], "state": "done"})
        n = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}[self.st4["id"]]
        self.assertEqual(n["state"], "done")

    def test_split_under_another_parent(self):
        # A different job goes under the parent named with --under, not under
        # the item the session is on (2026-11-22); its その他 means its parent.
        B.tree_from_session("aaaaaaaaaa01", {"cmd": "link", "id": self.st4["id"]})
        st, msg = B.tree_from_session("aaaaaaaaaa01", {"cmd": "split", "title": "別の仕事", "under": self.plan["id"]})
        self.assertEqual(st, "ok")
        ns = B.tree_call({"op": "list"})["nodes"]
        kid = next(x for x in ns if x["title"] == "別の仕事")
        self.assertEqual(kid["parent"], self.plan["id"])
        st, msg = B.tree_from_session("aaaaaaaaaa01", {"cmd": "split", "title": "X", "under": "nnope"})
        self.assertEqual(st, "failed")
        # Moving a branch by hand takes its subtree along; not below itself.
        sub = B.tree_call({"op": "add", "title": "孫", "parent": kid["id"]})["node"]
        B.tree_call({"op": "update", "id": kid["id"], "parent": self.st4["id"]})
        ns = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}
        self.assertEqual((ns[kid["id"]]["parent"], ns[sub["id"]]["parent"]), (self.st4["id"], kid["id"]))
        with self.assertRaises(ValueError):
            self.S.handle(self.me, {"op": "update", "id": kid["id"], "parent": sub["id"]})
        B.tree_call({"op": "update", "id": kid["id"], "parent": None})
        self.assertIsNone({x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}[kid["id"]]["parent"])

    def test_reopen_a_node_closed_by_mistake(self):
        B.tree_from_session("aaaaaaaaaa01", {"cmd": "link", "id": self.st4["id"]})
        # Closed through its session's done ball, and by hand.
        B.tree_call({"op": "update", "id": self.st4["id"], "state": "done", "ball": {"kind": "done"}})
        st, msg = B.tree_from_session("aaaaaaaaaa01", {"cmd": "reopen"})
        self.assertEqual(st, "ok")
        n = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}[self.st4["id"]]
        self.assertEqual((n["state"], n["ball"]["kind"]), ("open", "ai"))
        # Someone else's node by id: opened, its done ball cleared.
        B.tree_call({"op": "update", "id": self.plan["id"], "state": "done", "ball": {"kind": "done"}})
        B.tree_from_session("aaaaaaaaaa01", {"cmd": "reopen", "id": self.plan["id"]})
        n = {x["id"]: x for x in B.tree_call({"op": "list"})["nodes"]}[self.plan["id"]]
        self.assertEqual((n["state"], n.get("ball")), ("open", None))
        self.assertEqual(B.tree_from_session("aaaaaaaaaa01", {"cmd": "reopen", "id": "nope"})[0], "failed")

    def test_rule_only_for_tree_users(self):
        import os
        import aiza_status
        os.environ.pop("AIZA_TREE", None)
        self.assertNotIn("aiza-tree", aiza_status.rule())
        os.environ["AIZA_TREE"] = "1"
        try:
            self.assertIn("aiza-tree find", aiza_status.rule())
        finally:
            os.environ.pop("AIZA_TREE", None)


if __name__ == "__main__":
    unittest.main()
