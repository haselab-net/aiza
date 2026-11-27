"""The work tree's store (aiza-tree-store): who sees and changes which node,
the history, and the ball that follows a session.

    python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(data_dir):
    os.environ["AIZA_TREE_DIR"] = data_dir
    os.environ["AIZA_TREE_NOTIFY_HELPER"] = ""   # never the real Discord helper
    os.environ["AIZA_DISCORD_TREE_LINKS"] = os.path.join(data_dir, "discord-links.json")   # never the real one
    loader = importlib.machinery.SourceFileLoader("aiza_tree_store", str(ROOT / "bin" / "aiza-tree-store"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("aiza_tree_store", loader))
    loader.exec_module(mod)
    return mod


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.lab = {"alice", "bob"}
        self.S.in_lab = lambda u: u in self.lab
        self.told = []
        self.S.notify_members = lambda user, nid, added: self.told.append((user, nid, list(added)))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, user, **kw):
        return self.S.handle(user, dict({"op": "add"}, **kw))["node"]

    def test_list_hands_a_nodes_discord_link_to_who_sees_it(self):
        n = self.add("alice", title="shared", visibility="lab")
        m = self.add("alice", title="mine")
        good = "https://discord.com/channels/900000000000000001/800000000000000001"
        with open(self.S.DISCORD_LINKS, "w") as f:
            json.dump({n["id"]: good, m["id"]: "javascript:alert(1)"}, f)
        got = {x["id"]: x for x in self.S.handle("bob", {"op": "list"})["nodes"]}
        self.assertEqual(got[n["id"]]["discord"], good)
        self.assertNotIn(m["id"], got)
        mine = {x["id"]: x for x in self.S.handle("alice", {"op": "list"})["nodes"]}
        self.assertNotIn("discord", mine[m["id"]])   # not a Discord link: left out
        # handed, not stored
        self.assertNotIn("discord", self.S.load()[n["id"]])

    def ids(self, user):
        return {n["title"] for n in self.S.handle(user, {"op": "list"})["nodes"]}

    def test_self_and_lab(self):
        mine = self.add("alice", title="論文投稿")
        self.add("alice", title="共有", visibility="lab")
        self.assertEqual(self.ids("alice"), {"論文投稿", "共有"})
        self.assertEqual(self.ids("bob"), {"共有"})
        self.assertEqual(self.ids("carol"), set())          # not in the lab group
        with self.assertRaises(LookupError):
            self.S.handle("bob", {"op": "update", "id": mine["id"], "title": "x"})
        with self.assertRaises(LookupError):
            self.S.handle("bob", {"op": "history", "id": mine["id"]})

    def test_order_among_siblings(self):
        # ↕ drags set a node's place among its siblings (2026-11-23).
        p = self.S.handle("alice", {"op": "add", "title": "親"})["node"]
        a = self.S.handle("alice", {"op": "add", "title": "A", "parent": p["id"]})["node"]
        r = self.S.handle("alice", {"op": "update", "id": a["id"], "order": 12.5})
        self.assertEqual(r["node"]["order"], 12.5)
        for bad in ("x", True, float("nan"), 1e13):
            with self.assertRaises(ValueError):
                self.S.handle("alice", {"op": "update", "id": a["id"], "order": bad})
        with self.assertRaises((PermissionError, LookupError)):        # not bob's
            self.S.handle("bob", {"op": "update", "id": a["id"], "order": 1})

    def test_newly_named_members_are_told(self):
        n = self.add("alice", title="t")
        self.S.handle("alice", {"op": "update", "id": n["id"], "members": ["bob"]})
        self.S.handle("alice", {"op": "update", "id": n["id"], "members": ["bob", "carol"]})
        self.S.handle("alice", {"op": "update", "id": n["id"], "members": ["carol"]})
        self.S.handle("alice", {"op": "update", "id": n["id"], "visibility": "lab"})
        self.assertEqual(self.told, [("alice", n["id"], ["bob"]), ("alice", n["id"], ["carol"])])

    def test_members_write_owner_decides(self):
        n = self.add("alice", title="実験", visibility="lab")
        with self.assertRaises(PermissionError):
            self.S.handle("bob", {"op": "update", "id": n["id"], "state": "done"})
        self.S.handle("alice", {"op": "update", "id": n["id"], "members": ["bob"]})
        self.S.handle("bob", {"op": "update", "id": n["id"], "state": "done"})
        with self.assertRaises(PermissionError):
            self.S.handle("bob", {"op": "update", "id": n["id"], "visibility": "self"})
        with self.assertRaises(PermissionError):
            self.S.handle("bob", {"op": "remove", "id": n["id"]})

    def test_children_and_loops(self):
        a = self.add("alice", title="親")
        b = self.add("alice", title="子", parent=a["id"])
        with self.assertRaises(ValueError):
            self.S.handle("alice", {"op": "update", "id": a["id"], "parent": b["id"]})
        with self.assertRaises(ValueError):
            self.S.handle("alice", {"op": "remove", "id": a["id"]})
        with self.assertRaises(LookupError):
            self.add("bob", title="よその子", parent=a["id"])
        self.S.handle("alice", {"op": "remove", "id": b["id"]})
        self.S.handle("alice", {"op": "remove", "id": a["id"]})
        self.assertEqual(self.ids("alice"), set())

    def test_ball_follows_the_owners_session(self):
        n = self.add("alice", title="解析", links={"session": "aaaaaaaaaa01"})
        other = self.add("bob", title="別", links={"session": "aaaaaaaaaa01"})
        r = self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "ai"}})
        self.assertEqual(r["changed"], [n["id"]])
        self.assertEqual(self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "ai"}})["changed"], [])
        nodes = {x["id"]: x for x in self.S.load().values()}
        self.assertEqual(nodes[n["id"]]["ball"]["kind"], "ai")
        self.assertIsNone(nodes[other["id"]]["ball"])

    def test_member_links_own_session(self):
        # bob (a member) links his own session into alice's node: the ball
        # follows bob's session, and the gateway learns to ask bob.
        n = self.add("alice", title="共同", visibility="lab")
        self.S.handle("alice", {"op": "update", "id": n["id"], "members": ["bob"]})
        self.S.handle("bob", {"op": "update", "id": n["id"], "links": {"session": "bbbbbbbbbb01"}})
        self.assertEqual(self.S.load()[n["id"]]["session_owner"], "bob")
        self.assertEqual(self.S.handle("alice", {"op": "ball", "session": "bbbbbbbbbb01", "ball": {"kind": "ai"}})["changed"], [])
        self.assertEqual(self.S.handle("bob", {"op": "ball", "session": "bbbbbbbbbb01", "ball": {"kind": "ai"}})["changed"], [n["id"]])
        self.lab.add("carol")
        self.assertEqual(self.S.handle("aiza", {"op": "owners_for", "user": "carol"})["owners"], ["bob"])
        with self.assertRaises(PermissionError):
            self.S.handle("carol", {"op": "owners_for", "user": "carol"})

    def test_take_and_undo(self):
        n = self.add("alice", title="解析", visibility="lab", links={"session": "aaaaaaaaaa01", "issue": "o/r#1"})
        self.lab.add("carol")
        r = self.S.handle("carol", {"op": "take", "id": n["id"], "session": "cccccccccc01"})["node"]
        self.assertEqual((r["links"]["session"], r["session_owner"], r["links"]["issue"]), ("cccccccccc01", "carol", "o/r#1"))
        self.assertIn("carol", r["members"])                          # may change it from now on
        self.S.handle("carol", {"op": "update", "id": n["id"], "title": "解析(続き)"})
        told = self.S.handle("alice", {"op": "taken_for"})["nodes"]
        self.assertEqual([(x["taken"]["from_session"], x["taken"]["by"]) for x in told], [("aaaaaaaaaa01", "carol")])
        self.S.handle("alice", {"op": "ack_taken", "id": n["id"]})
        self.assertEqual(self.S.handle("alice", {"op": "taken_for"})["nodes"], [])
        with self.assertRaises(LookupError):
            self.S.handle("bob", {"op": "untake", "id": n["id"]})      # only the taker
        back = self.S.handle("carol", {"op": "untake", "id": n["id"]})["node"]
        self.assertEqual((back["links"]["session"], back["members"]), ("aaaaaaaaaa01", []))
        self.assertEqual(self.S.handle("alice", {"op": "taken_for"})["nodes"][0]["taken"]["state"], "undone")
        with self.assertRaises(LookupError):
            self.S.handle("carol", {"op": "untake", "id": n["id"]})

    def test_take_needs_sight(self):
        n = self.add("alice", title="私的", links={"session": "aaaaaaaaaa01"})
        with self.assertRaises(LookupError):
            self.S.handle("bob", {"op": "take", "id": n["id"], "session": "bbbbbbbbbb01"})

    def test_history_and_files_are_private(self):
        n = self.add("alice", title="題")
        self.S.handle("alice", {"op": "update", "id": n["id"], "title": "新しい題"})
        h = self.S.handle("alice", {"op": "history", "id": n["id"]})["history"]
        self.assertEqual([(e["op"], e["user"]) for e in h], [("add", "alice"), ("update", "alice")])
        for f in (self.S.NODES, self.S.HISTORY):
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)

    def test_recent_only_what_the_caller_sees(self):
        a = self.add("alice", title="私の")
        self.add("bob", title="ボブの")
        self.S.handle("alice", {"op": "update", "id": a["id"], "state": "done"})
        r = self.S.handle("alice", {"op": "recent", "since": 0})["history"]
        self.assertEqual({e["id"] for e in r}, {a["id"]})
        self.assertEqual(self.S.handle("alice", {"op": "recent", "since": 9e9})["history"], [])

    def test_bad_input(self):
        for kw in ({"title": ""}, {"title": "x", "visibility": "public"}, {"title": "x", "links": {"session": "../x"}},
                   {"title": "x", "ball": {"kind": "boss"}}, {"title": "x", "links": {"issue": "a b#1"}}):
            with self.assertRaises(ValueError, msg=kw):
                self.add("alice", **kw)
        self.assertEqual(len(self.add("alice", title="x" * 500)["title"]), self.S.TITLE_MAX)


class TeamTest(unittest.TestCase):
    """🧭 担当 and 🤝 協力 (the deployment notes, 2026-11-27): a helper writes
    nothing into the tree and goes wherever its lead goes."""
    LEAD, HELP, OTHER = "aaaaaaaaaa01", "aaaaaaaaaa02", "aaaaaaaaaa03"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.S.in_lab = lambda u: u in {"alice", "bob"}
        self.S.notify_members = lambda *a: None
        self.n = self.S.handle("alice", {"op": "add", "title": "画面", "links": {"session": self.LEAD}})["node"]

    def tearDown(self):
        self.tmp.cleanup()

    def helpers(self, user="alice"):
        return {n["id"]: n.get("helpers") for n in self.S.handle(user, {"op": "list"})["nodes"]}

    def help(self, sid=None, user="alice", node=None):
        return self.S.handle(user, {"op": "help", "id": (node or self.n)["id"], "session": sid or self.HELP})

    def test_a_helper_shows_on_its_leads_item_and_writes_nothing(self):
        self.help()
        self.assertEqual(self.helpers()[self.n["id"]], [{"owner": "alice", "session": self.HELP}])
        r = self.S.handle("alice", {"op": "ball", "session": self.HELP, "ball": {"kind": "person"}})
        self.assertEqual(r["changed"], [])
        self.assertEqual(len(self.S.load()), 1)   # no node for the helper

    def test_a_helper_goes_where_its_lead_goes(self):
        self.help()
        m = self.S.handle("alice", {"op": "add", "title": "次", "links": {"session": self.LEAD}})["node"]
        got = self.helpers()
        self.assertEqual(got[m["id"]], [{"owner": "alice", "session": self.HELP}])
        self.assertIsNone(got[self.n["id"]])

    def test_a_lead_helps_no_one(self):
        self.S.handle("alice", {"op": "add", "title": "別", "links": {"session": self.OTHER}})
        with self.assertRaises(ValueError):
            self.help(self.OTHER)
        # and a helper that takes an item on is a lead from then on
        self.help()
        self.S.handle("alice", {"op": "add", "title": "自分の", "links": {"session": self.HELP}})
        self.assertIsNone(self.helpers()[self.n["id"]])

    def test_a_lead_lets_its_item_go_then_helps_a_split_items_lead(self):
        # The page's 「はい」 (2026-11-27, the user: すでに担当を持つセッションを
        # 協力にすると、はいを選んでもエラーになります): the session lets its
        # item go (treeRelease), then helps. The 担当 there works on the
        # item's own part, its その他 child, once the item has branches.
        self.S.handle("alice", {"op": "add", "parent": self.n["id"], "title": "枝"})
        self.S.handle("alice", {"op": "ball", "session": self.LEAD, "ball": {"kind": "person", "who": "alice", "text": "見てほしい"}})
        rest = next(n for n in self.S.load().values() if n.get("rest"))
        self.assertEqual(rest["links"].get("session"), self.LEAD)
        m = self.S.handle("alice", {"op": "add", "title": "別", "links": {"session": self.OTHER}})["node"]
        with self.assertRaises(ValueError):   # a 担当 helps no one ...
            self.help(self.OTHER, node=rest)
        self.S.handle("alice", {"op": "update", "id": m["id"], "links": {}, "ball": None})
        self.help(self.OTHER, node=rest)       # ... once it has let its item go
        self.assertEqual(self.helpers()[rest["id"]], [{"owner": "alice", "session": self.OTHER}])

    def done(self, sid=None):
        return self.S.handle("alice", {"op": "ball", "session": sid or self.LEAD, "ball": {"kind": "done", "text": "済み — 引き継ぎ"}})

    def test_a_lead_with_helpers_is_not_closed_by_its_done(self):
        # 2026-11-27, the user: このセッションが木からよく消えます. Its done
        # ball waits for its team: open, 🤖, the done text kept.
        self.help()
        self.done()
        n = self.S.load()[self.n["id"]]
        self.assertEqual((n["state"], n["ball"]["kind"], n["ball"]["text"], n["ball"]["wait"]), ("open", "ai", "済み — 引き継ぎ", "team"))
        self.assertEqual(self.helpers()[self.n["id"]], [{"owner": "alice", "session": self.HELP}])
        # Its last helper gone: it closes as its done said.
        self.S.handle("alice", {"op": "unhelp", "session": self.HELP})
        n = self.S.load()[self.n["id"]]
        self.assertEqual((n["state"], n.get("closed_by"), n["ball"]["kind"]), ("done", "ball", "done"))
        self.assertNotIn("wait", n["ball"])
        # Working again opens it, as before.
        self.S.handle("alice", {"op": "ball", "session": self.LEAD, "ball": {"kind": "ai"}})
        self.assertEqual(self.S.load()[self.n["id"]]["state"], "open")

    def test_a_lead_with_an_open_handoff_branch_is_not_closed(self):
        # Its その他 (rest): the handoff branches are its parent's children.
        self.S.handle("alice", {"op": "add", "parent": self.n["id"], "title": "枝"})
        self.S.handle("alice", {"op": "ball", "session": self.LEAD, "ball": {"kind": "person", "who": "alice", "text": "見て"}})
        rest = next(n for n in self.S.load().values() if n.get("rest"))
        h = self.S.handle("alice", {"op": "add", "parent": self.n["id"], "title": "Bへ",
                                    "links": {"session": self.OTHER, "handoff": "h0123456789ab"}})["node"]
        self.done()
        r = self.S.load()[rest["id"]]
        self.assertEqual((r["state"], r["ball"]["kind"]), ("open", "ai"))
        # The branch done: the 担当's その他 closes as its done said.
        self.S.handle("alice", {"op": "update", "id": h["id"], "state": "done"})
        nodes = self.S.load()
        self.assertEqual((nodes[rest["id"]]["state"], nodes[rest["id"]]["ball"]["kind"]), ("done", "done"))

    def test_a_lead_with_nothing_out_closes_as_before(self):
        self.done()
        self.assertEqual(self.S.load()[self.n["id"]]["state"], "done")

    def test_one_team_at_a_time(self):
        m = self.S.handle("alice", {"op": "add", "title": "別", "links": {"session": self.OTHER}})["node"]
        self.help()
        self.help(node=m)
        got = self.helpers()
        self.assertIsNone(got[self.n["id"]])
        self.assertEqual(got[m["id"]], [{"owner": "alice", "session": self.HELP}])

    def test_only_who_may_change_the_item(self):
        self.S.handle("alice", {"op": "update", "id": self.n["id"], "visibility": "lab"})
        with self.assertRaises(PermissionError):
            self.help("bbbbbbbbbb01", user="bob")
        self.S.handle("alice", {"op": "update", "id": self.n["id"], "members": ["bob"]})
        self.help("bbbbbbbbbb01", user="bob")
        self.assertEqual(self.helpers("bob")[self.n["id"]], [{"owner": "bob", "session": "bbbbbbbbbb01"}])

    def test_unhelp_and_team_left(self):
        self.help()
        with self.assertRaises(PermissionError):
            self.S.handle("bob", {"op": "unhelp", "session": self.HELP, "owner": "alice"})
        self.S.handle("alice", {"op": "unhelp", "session": self.HELP})
        self.assertIsNone(self.helpers()[self.n["id"]])
        self.help()
        self.S.handle("alice", {"op": "team_left", "session": self.LEAD})   # the lead's link is gone
        self.assertIsNone(self.helpers()[self.n["id"]])
        self.help()
        self.S.handle("alice", {"op": "team_left", "session": self.HELP})
        self.assertIsNone(self.helpers()[self.n["id"]])

    def test_no_helpers_on_a_finished_item(self):
        self.help()
        self.S.handle("alice", {"op": "update", "id": self.n["id"], "state": "done"})
        self.assertIsNone(self.helpers()[self.n["id"]])


class RestTest(unittest.TestCase):
    """その他: made only when a parent's session goes on working on it after it has children."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.S.in_lab = lambda u: u in {"alice", "bob"}

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, user, **kw):
        return self.S.handle(user, dict({"op": "add"}, **kw))["node"]

    def nodes(self, user="alice"):
        return {n["id"]: n for n in self.S.handle(user, {"op": "list"})["nodes"]}

    def kids(self, pid):
        return [n for n in self.nodes().values() if n.get("parent") == pid]

    def test_children_leave_the_session_on_the_parent_until_it_works_on(self):
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa01"}, ball={"kind": "ai"})
        self.add("alice", title="子", parent=p["id"])
        self.add("alice", title="子2", parent=p["id"])
        self.assertFalse(any(k.get("rest") for k in self.kids(p["id"])))
        self.assertEqual(self.nodes()[p["id"]]["links"], {"session": "aaaaaaaaaa01"})
        # Working (🤖) or done stays on the parent.
        r = self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "ai"}})
        self.assertEqual(self.nodes()[p["id"]]["ball"]["kind"], "ai")
        # A status that hands the turn over: its own work becomes a child, named by it.
        r = self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01",
                                    "ball": {"kind": "person", "who": "alice", "text": "鍵穴プーリーの試験結果"}})
        rest = next(k for k in self.kids(p["id"]) if k.get("rest"))
        self.assertEqual(r["changed"], [rest["id"]])
        self.assertEqual(rest["title"], "鍵穴プーリーの試験結果")
        self.assertEqual((rest["links"], rest["ball"]["kind"]), ({"session": "aaaaaaaaaa01"}, "person"))
        parent = self.nodes()[p["id"]]
        self.assertNotIn("session", parent["links"])
        self.assertIsNone(parent["ball"])
        # Only one.
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "sleep", "text": "x"}})
        self.assertEqual(sum(1 for k in self.kids(p["id"]) if k.get("rest")), 1)

    def test_parent_settles_from_children(self):
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa01"})
        a = self.add("alice", title="A", parent=p["id"])
        self.S.handle("alice", {"op": "update", "id": a["id"], "state": "done"})
        # A done, but its own work (the rest) is still open.
        self.assertEqual(self.nodes()[p["id"]]["state"], "open")
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "done"}})
        self.assertEqual(self.nodes()[p["id"]]["state"], "done")
        # A new child opens it again.
        self.add("alice", title="B", parent=p["id"])
        self.assertEqual(self.nodes()[p["id"]]["state"], "open")

    def test_nested_settle(self):
        top = self.add("alice", title="上")
        mid = self.add("alice", title="中", parent=top["id"])
        leaf = self.add("alice", title="葉", parent=mid["id"])
        for n in self.nodes().values():
            if n.get("rest"):
                self.S.handle("alice", {"op": "update", "id": n["id"], "state": "done"})
        self.assertEqual(self.nodes()[top["id"]]["state"], "open")
        self.S.handle("alice", {"op": "update", "id": leaf["id"], "state": "done"})
        self.assertEqual(self.nodes()[mid["id"]]["state"], "done")
        self.assertEqual(self.nodes()[top["id"]]["state"], "done")

    def test_by_hand_on_a_split_node(self):
        p = self.add("alice", title="親")
        a = self.add("alice", title="A", parent=p["id"])
        self.S.handle("alice", {"op": "update", "id": p["id"], "state": "done"})
        ns = self.nodes()
        self.assertEqual(ns[a["id"]]["state"], "done")
        self.assertEqual(ns[p["id"]]["state"], "done")
        self.S.handle("alice", {"op": "update", "id": p["id"], "state": "open"})
        ns = self.nodes()
        rest = next(k for k in self.kids(p["id"]) if k.get("rest"))
        self.assertEqual(rest["state"], "open")
        self.assertEqual(ns[a["id"]]["state"], "done")
        self.assertEqual(ns[p["id"]]["state"], "open")

    def test_by_hand_on_a_split_node_with_a_sleeping_session(self):
        # Its session is asleep on it and its children are all done: done by
        # hand stays done (2026-11-23, settle opened it again).
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa05"})
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa05",
                                "ball": {"kind": "sleep", "until": 1e10, "text": "待ち"}})
        a = self.add("alice", title="A", parent=p["id"])
        self.S.handle("alice", {"op": "update", "id": a["id"], "state": "done"})
        ns = self.nodes()
        self.assertEqual(ns[p["id"]]["state"], "open")
        self.assertFalse(any(k.get("rest") for k in self.kids(p["id"])))
        self.S.handle("alice", {"op": "update", "id": p["id"], "state": "done"})
        self.assertEqual(self.nodes()[p["id"]]["state"], "done")

    def test_short_title(self):
        st = self.S.short_title
        self.assertEqual(st("鍵穴プーリーの試験結果"), "鍵穴プーリーの試験結果")
        self.assertEqual(st("了解です。フォルダの件は作り直していません(6dd35bd を確かめ、利用者が想定した形)"), "了解です")
        long = st("フォルダの件は作り直していません、6dd35bd を確かめて利用者が想定した形にしました")
        self.assertTrue(long.endswith("…") and len(long) <= 21, long)
        # A rest made from a long status: about 20 characters.
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa01"})
        self.add("alice", title="子", parent=p["id"])
        r = self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "person", "who": "alice",
                                    "text": "置き去りの対策案2つと既存11件の整理を進めるか、それとも先に見るか"}})
        rest = next(k for k in self.kids(p["id"]) if k.get("rest"))
        self.assertLessEqual(len(rest["title"]), 21)
        # Cut short for now: the backend is asked to put a summary in its place.
        self.assertEqual(r["retitle"], [{"id": rest["id"], "title": rest["title"],
                                         "text": "置き去りの対策案2つと既存11件の整理を進めるか、それとも先に見るか"}])
        self.S.handle("alice", {"op": "update", "id": rest["id"], "title": "置き去り対策の進め方"})
        self.assertNotIn("title_src", self.nodes()[rest["id"]])

    def test_linking_a_split_node_links_its_rest(self):
        p = self.add("alice", title="親")
        self.add("alice", title="A", parent=p["id"])
        self.S.handle("alice", {"op": "update", "id": p["id"], "links": {"session": "aaaaaaaaaa02"}})
        self.assertEqual(self.nodes()[p["id"]]["links"], {"session": "aaaaaaaaaa02"})   # no rest yet
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa02", "ball": {"kind": "person", "who": "alice"}})
        rest = next(k for k in self.kids(p["id"]) if k.get("rest"))
        self.assertEqual(rest["title"], "その他")                                       # no text
        self.S.handle("alice", {"op": "update", "id": p["id"], "links": {"session": "aaaaaaaaaa04"}})
        self.assertEqual(self.nodes()[rest["id"]]["links"], {"session": "aaaaaaaaaa04"})
        t = self.S.handle("alice", {"op": "take", "id": p["id"], "session": "aaaaaaaaaa03"})["node"]
        self.assertEqual(t["id"], rest["id"])

    def test_rest_stays_and_folds_back(self):
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa01"})
        a = self.add("alice", title="A", parent=p["id"])
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "person", "who": "alice"}})
        rest = next(k for k in self.kids(p["id"]) if k.get("rest"))
        with self.assertRaises(ValueError):
            self.S.handle("alice", {"op": "remove", "id": rest["id"]})
        other = self.add("alice", title="別")
        with self.assertRaises(ValueError):
            self.S.handle("alice", {"op": "update", "id": rest["id"], "parent": other["id"]})
        self.S.handle("alice", {"op": "remove", "id": a["id"]})
        self.assertEqual(self.kids(p["id"]), [])
        self.assertEqual(self.nodes()[p["id"]]["links"], {"session": "aaaaaaaaaa01"})

    def test_moving_a_node_in_makes_no_rest(self):
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa01"})
        x = self.add("alice", title="X")
        self.S.handle("alice", {"op": "update", "id": x["id"], "parent": p["id"]})
        self.assertEqual(sum(1 for k in self.kids(p["id"]) if k.get("rest")), 0)

    def test_moving_down_takes_the_work_along(self):
        # The parent's session splits and takes the child on: the parent is
        # neither left nor given a rest; it is done when the child is.
        p = self.add("alice", title="親", links={"session": "aaaaaaaaaa01"}, ball={"kind": "ai"})
        c = self.add("alice", title="子", parent=p["id"])
        self.S.handle("alice", {"op": "update", "id": c["id"], "links": {"session": "aaaaaaaaaa01"}})
        ns = self.nodes()
        self.assertNotIn("session", ns[p["id"]]["links"])
        self.assertIsNone(ns[p["id"]].get("left"))
        self.assertFalse(any(k.get("rest") for k in self.kids(p["id"])))
        self.assertEqual(ns[p["id"]]["state"], "open")
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": "done"}})
        ns = self.nodes()
        self.assertEqual((ns[c["id"]]["state"], ns[p["id"]]["state"]), ("done", "done"))

    def test_github_nodes_get_no_rest(self):
        root = self.add("alice", title="repo", links={"repo": "o/r"})
        self.add("alice", title="#1", parent=root["id"], links={"issue": "o/r#1"})
        self.assertFalse(any(k.get("rest") for k in self.kids(root["id"])))

    def test_migrate(self):
        S = self.S
        nodes = {}
        now = 1.0
        def mk(i, parent, **kw):
            nodes[i] = dict({"id": i, "parent": parent, "title": i, "owner": "alice", "members": [],
                             "visibility": "self", "state": "open", "ball": None, "links": {},
                             "created_ts": now, "updated_ts": now}, **kw)
        mk("n000000000001", None, links={"session": "aaaaaaaaaa01"}, ball={"kind": "person", "who": "alice"})
        mk("n000000000002", "n000000000001", state="done")
        mk("n000000000003", None)
        mk("n000000000004", "n000000000003", state="done")
        mk("n000000000005", None)
        self.assertEqual(S.migrate(nodes), 0)
        self.assertFalse(any(n.get("rest") for n in nodes.values()))     # no rest for every parent any more
        # Its session still on it, waiting for a person: open.
        self.assertEqual(nodes["n000000000001"]["state"], "open")
        # No session: its children were its whole work.
        self.assertEqual(nodes["n000000000003"]["state"], "done")

class OnePlaceTest(unittest.TestCase):
    """A session may hold several nodes; its state goes to the one it took on last."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.S.in_lab = lambda u: u in {"alice", "bob"}
        import types
        self.t = 1000.0

        def clock():
            self.t += 1
            return self.t
        self.S.time = types.SimpleNamespace(time=clock)   # this module's own copy only

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, user, **kw):
        return self.S.handle(user, dict({"op": "add"}, **kw))["node"]

    def nodes(self):
        return {n["id"]: n for n in self.S.handle("alice", {"op": "list"})["nodes"]}

    def ball(self, kind):
        return self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01", "ball": {"kind": kind}})["changed"]

    def test_state_goes_to_the_last_one(self):
        a = self.add("alice", title="A", links={"session": "aaaaaaaaaa01"})
        self.assertEqual(self.ball("ai"), [a["id"]])
        b = self.add("alice", title="B", links={"session": "aaaaaaaaaa01", "handoff": "h000000000001"})
        self.assertEqual(self.ball("sleep"), [b["id"]])
        ns = self.nodes()
        self.assertEqual(ns[a["id"]]["ball"]["kind"], "ai")        # A keeps what it had,
        self.assertTrue(ns[a["id"]]["left"])                       # marked left behind
        self.assertNotIn("left", ns[b["id"]])
        # Linked again by hand: A is where it goes now.
        self.S.handle("alice", {"op": "update", "id": a["id"], "relink": True, "links": {"session": "aaaaaaaaaa01"}})
        self.assertEqual(self.ball("person"), [a["id"]])
        # A plain change of A's links (no relink, same session) does not move it.
        self.S.handle("alice", {"op": "update", "id": b["id"], "links": {"session": "aaaaaaaaaa01", "repo": "o/r"}})
        self.assertEqual(self.ball("ai"), [a["id"]])
        # One closed by hand: the state goes nowhere (not back to B, which A left).
        self.S.handle("alice", {"op": "update", "id": a["id"], "state": "done"})
        self.assertEqual(self.ball("person"), [])
        ns = self.nodes()
        self.assertEqual((ns[a["id"]]["state"], ns[a["id"]]["closed_by"]), ("done", "hand"))
        # B was waiting (💤) when A was taken on again: still waiting, not left.
        self.assertEqual((ns[b["id"]]["ball"]["kind"], ns[b["id"]].get("left")), ("sleep", None))

    def test_split_keeps_it_on_the_parent(self):
        a = self.add("alice", title="A", links={"session": "aaaaaaaaaa01"})
        b = self.add("alice", title="B", links={"session": "aaaaaaaaaa01"})
        self.add("alice", title="B1", parent=b["id"])
        self.assertEqual(self.ball("ai"), [b["id"]])
        self.assertNotEqual(b["id"], a["id"])

    def test_back_to_before_the_turn(self):
        # 🙋 asked, then a new message (🤖) and another node taken on elsewhere:
        # the first goes back to 🙋, not left.
        a = self.add("alice", title="A", links={"session": "aaaaaaaaaa01"})
        self.S.handle("alice", {"op": "ball", "session": "aaaaaaaaaa01",
                                "ball": {"kind": "person", "who": "alice", "text": "数を教えて"}})
        self.ball("ai")
        self.add("alice", title="B", links={"session": "aaaaaaaaaa01"})
        n = self.nodes()[a["id"]]
        self.assertEqual((n["ball"]["kind"], n["ball"]["text"], n.get("left"), n["state"]), ("person", "数を教えて", None, "open"))
        # ✓, then a new message and another node: closed again.
        self.ball("done")
        ns = self.nodes()
        b = next(x for x in ns.values() if x["title"] == "B")
        self.assertEqual(ns[b["id"]]["state"], "done")
        self.ball("ai")
        self.assertEqual(self.nodes()[b["id"]]["state"], "open")
        self.add("alice", title="C", links={"session": "aaaaaaaaaa01"})
        self.assertEqual(self.nodes()[b["id"]]["state"], "done")
        # Waiting for a person when taken off: stays so.
        self.ball("person")
        self.add("alice", title="C2", links={"session": "aaaaaaaaaa01"})
        c2 = next(x for x in self.nodes().values() if x["title"] == "C")
        self.assertEqual((c2["ball"]["kind"], c2.get("left")), ("person", None))
        self.S.handle("alice", {"op": "update", "id": c2["id"], "links": {"session": "aaaaaaaaaa01"}, "relink": True})
        # Worked on for real (a status after the message): left, as before.
        self.ball("sleep"); self.ball("ai"); self.ball("person")
        self.ball("ai")
        self.t += self.S.BEFORE_TURN_KEEP + 10                  # ...and long ago
        c = next(x for x in self.nodes().values() if x["title"] == "C")
        self.add("alice", title="D", links={"session": "aaaaaaaaaa01"})
        self.assertIsNotNone(self.nodes()[c["id"]].get("left"))

    def test_taking_another_closes_a_done_one(self):
        a = self.add("alice", title="A", links={"session": "aaaaaaaaaa01"})
        self.ball("done")
        ns = self.nodes()
        self.assertEqual((ns[a["id"]]["state"], ns[a["id"]]["closed_by"]), ("done", "ball"))
        # Working again on it opens it again.
        self.assertEqual(self.ball("ai"), [a["id"]])
        self.assertEqual(self.nodes()[a["id"]]["state"], "open")
        # A done ball left open (from before): taking another closes it, not leaves it.
        nodes = self.S.load()
        nodes[a["id"]]["ball"] = {"kind": "done", "since": 1.0}
        self.S.save(nodes)
        b = self.add("alice", title="B", links={"session": "aaaaaaaaaa01"})
        ns = self.nodes()
        self.assertEqual((ns[a["id"]]["state"], ns[a["id"]].get("left")), ("done", None))
        self.assertEqual(self.ball("sleep"), [b["id"]])

    def test_relinked_is_no_longer_left(self):
        a = self.add("alice", title="A", links={"session": "aaaaaaaaaa01"})
        b = self.add("alice", title="B", links={"session": "aaaaaaaaaa01"})
        self.S.handle("alice", {"op": "update", "id": a["id"], "relink": True, "links": {"session": "aaaaaaaaaa01"}})
        ns = self.nodes()
        self.assertNotIn("left", ns[a["id"]])
        self.assertTrue(ns[b["id"]]["left"])
        # Linking a closed one again opens it (the session's state goes there).
        self.S.handle("alice", {"op": "update", "id": a["id"], "state": "done"})
        self.S.handle("alice", {"op": "update", "id": a["id"], "relink": True, "links": {"session": "aaaaaaaaaa01"}})
        self.assertEqual(self.nodes()[a["id"]]["state"], "open")
        self.assertEqual(self.ball("sleep"), [a["id"]])
        # Another session's nodes are not touched.
        c = self.add("alice", title="C", links={"session": "aaaaaaaaaa02"})
        self.assertNotIn("left", self.nodes()[a["id"]])
        self.assertNotIn("left", self.nodes()[c["id"]])

    def test_split_parent_closes_when_the_rest_is_done(self):
        p = self.add("alice", title="P", links={"session": "aaaaaaaaaa01"})
        k = self.add("alice", title="K", parent=p["id"])
        self.S.handle("alice", {"op": "update", "id": k["id"], "state": "done"})
        self.assertEqual(self.nodes()[p["id"]]["state"], "open")
        self.ball("done")
        self.assertEqual(self.nodes()[p["id"]]["state"], "done")
        self.ball("ai")
        self.assertEqual(self.nodes()[p["id"]]["state"], "open")

    def test_migrate_closes_and_leaves_old_nodes(self):
        S = self.S
        mk = lambda i, sid, ts, ball, state="open": {
            "id": i, "parent": None, "title": i, "owner": "alice", "members": [], "visibility": "self",
            "state": state, "ball": ball and {"kind": ball, "since": 1.0}, "links": {"session": sid} if sid else {},
            "session_owner": "alice", "linked_ts": ts, "created_ts": ts, "updated_ts": ts}
        nodes = {n["id"]: n for n in (
            mk("n000000000001", "aaaaaaaaaa01", 1.0, "ai"),            # held before: left
            mk("n000000000002", "aaaaaaaaaa01", 2.0, "done"),          # done ball, open: closed
            mk("n000000000003", "aaaaaaaaaa01", 3.0, "ai"),            # the last one: kept
            mk("n000000000004", "aaaaaaaaaa01", 0.5, "ai", "done"),   # closed by hand before
            mk("n000000000005", None, 1.0, None))}
        S.migrate(nodes)
        self.assertTrue(nodes["n000000000001"]["left"])
        self.assertEqual((nodes["n000000000002"]["state"], nodes["n000000000002"]["closed_by"]), ("done", "ball"))
        self.assertNotIn("left", nodes["n000000000003"])
        self.assertEqual(nodes["n000000000004"]["closed_by"], "hand")
        self.assertNotIn("left", nodes["n000000000005"])
        once = json.dumps(nodes, sort_keys=True)
        S.migrate(nodes)
        self.assertEqual(json.dumps(nodes, sort_keys=True), once)

    def test_old_nodes_take_their_time_from_the_history(self):
        S = self.S
        nodes = {}
        for i, created in (("n000000000001", 1.0), ("n000000000002", 2.0)):
            nodes[i] = {"id": i, "parent": None, "title": i, "owner": "alice", "members": [], "visibility": "self",
                        "state": "open", "ball": None, "links": {"session": "aaaaaaaaaa01"},
                        "created_ts": created, "updated_ts": created}
        S.record("alice", "update", "n000000000001", {"links": {"session": "aaaaaaaaaa01"}})
        self.assertEqual(S.fill_linked_ts(nodes), 2)
        self.assertGreater(nodes["n000000000001"]["linked_ts"], nodes["n000000000002"]["linked_ts"])
        self.assertEqual(S.current_of(nodes, "alice", "aaaaaaaaaa01")["id"], "n000000000001")


if __name__ == "__main__":
    unittest.main()


class DeskTest(unittest.TestCase):
    """The desk (the deployment notes): reports from anyone in the lab, seen by
    the lab, each session a link only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.S = load(self.tmp.name)
        self.S.in_lab = lambda u: u in {"alice", "bob", "root"}
        self.desk = self.S.handle("root", {"op": "add", "title": "aiza の窓口"})["node"]
        self.S.handle("root", {"op": "desk", "id": self.desk["id"]})

    def tearDown(self):
        self.tmp.cleanup()

    def report(self, user, **kw):
        return self.S.handle(user, dict({"op": "report", "desk": self.desk["id"], "title": "x"}, **kw))["node"]

    def test_only_root_makes_a_desk(self):
        n = self.S.handle("alice", {"op": "add", "title": "mine"})["node"]
        with self.assertRaises(LookupError):
            self.S.handle("alice", {"op": "desk", "id": n["id"]})
        with self.assertRaises(LookupError):
            self.S.handle("root", {"op": "desk", "id": n["id"]})   # not root's own

    def test_a_report_is_the_reporters_and_seen_by_the_lab(self):
        r = self.report("alice", title="画面が崩れる", ref="host1/alice/devbox/0123456789ab")
        self.assertEqual((r["owner"], r["parent"], r["visibility"]), ("alice", self.desk["id"], "lab"))
        self.assertEqual(r["links"], {"ref": "host1/alice/devbox/0123456789ab"})
        self.assertNotIn("session", r["links"])                  # never shared like a node's session
        seen = {n["id"] for n in self.S.handle("bob", {"op": "list"})["nodes"]}
        self.assertIn(r["id"], seen)
        with self.assertRaises(PermissionError):
            self.S.handle("bob", {"op": "update", "id": r["id"], "title": "y"})
        self.S.handle("alice", {"op": "update", "id": r["id"], "title": "画面が崩れる(スマホ)"})

    def test_no_rest_child_and_the_desk_stays_open(self):
        r = self.report("alice")
        kids = [n for n in self.S.handle("root", {"op": "list"})["nodes"] if n.get("parent") == self.desk["id"]]
        self.assertEqual([n["id"] for n in kids], [r["id"]])
        self.S.handle("root", {"op": "update", "id": r["id"], "state": "done"})
        desk = next(n for n in self.S.handle("root", {"op": "list"})["nodes"] if n["id"] == self.desk["id"])
        self.assertEqual(desk["state"], "open")

    def test_the_reports_time_and_log_position_are_kept(self):
        r = self.report("alice", ref="host1/alice/email/0123456789ab",
                        pos={"at": 1700000000, "events": 12, "seq": 15, "conv": "abcdefgh-1234", "conv_line": 80})
        self.assertEqual(r["report_pos"]["conv_line"], 80)
        for bad in ({"text": "x"}, {"events": "12"}, {"events": True}, {"conv": "../x"}, [1]):
            with self.assertRaises(ValueError):
                self.report("alice", ref="host1/alice/email/0123456789ab", pos=bad)
        self.assertNotIn("report_pos", self.report("alice", pos={"events": 1}))   # no session, no position

    def test_a_deploy_request_keeps_the_commit_and_the_bot_does_not_take_it(self):
        d = {"repo": "/home/alice/sandhome/aiza", "sha": "a" * 40}
        r = self.report("alice", ref="host2/alice/devbox/0123456789ab", deploy=d)
        self.assertEqual(r["deploy"], d)
        self.assertEqual(r["ball"]["text"], self.S.DEPLOY_WAITING)
        self.assertNotIn("deploy", self.report("alice", ref="host2/alice/devbox/0123456789ab"))
        with self.assertRaises(ValueError):   # someone else's session
            self.report("alice", ref="host2/bob/devbox/0123456789ab", deploy=d)
        with self.assertRaises(ValueError):   # no session
            self.report("alice", deploy=d)
        for bad in ({"repo": "x", "sha": "a" * 40}, {"repo": "/a/../b", "sha": "a" * 40},
                    {"repo": "/a b", "sha": "a" * 40}, {"repo": "/a", "sha": "abc"},
                    {"repo": "/a", "sha": "a" * 40, "x": 1}, "x"):
            with self.assertRaises(ValueError):
                self.report("alice", ref="host2/alice/devbox/0123456789ab", deploy=bad)

    def test_a_session_under_a_report_leaves_no_rest_child(self):
        self.S.in_lab = lambda u: u in {"alice", "bob", "root", "bot"}
        self.S.handle("root", {"op": "update", "id": self.desk["id"], "members": ["bot"]})
        r = self.report("alice")
        self.S.handle("bot", {"op": "update", "id": r["id"], "ball": {"kind": "ai", "text": "ボットが調べている"}})
        c = self.S.handle("bot", {"op": "add", "parent": r["id"], "title": "窓口: x",
                                  "links": {"session": "0123456789ab"}})["node"]
        kids = [n["id"] for n in self.S.handle("root", {"op": "list"})["nodes"] if n.get("parent") == r["id"]]
        self.assertEqual(kids, [c["id"]])

    def test_a_report_goes_back_to_its_sender_when_the_work_under_it_ends(self):
        self.S.in_lab = lambda u: u in {"alice", "bob", "root", "bot"}
        self.S.handle("root", {"op": "update", "id": self.desk["id"], "members": ["bot"]})
        r = self.report("alice")
        self.S.handle("bot", {"op": "update", "id": r["id"], "ball": {"kind": "ai", "text": "ボットが調べている"}})
        self.S.handle("bot", {"op": "add", "parent": r["id"], "title": "窓口: x",
                              "links": {"session": "0123456789ab"}})
        get = lambda: next(n for n in self.S.handle("root", {"op": "list"})["nodes"] if n["id"] == r["id"])
        self.S.handle("bot", {"op": "ball", "session": "0123456789ab", "ball": {"kind": "ai", "text": "調べている"}})
        self.assertEqual(get()["ball"]["kind"], "ai")              # still at work under it
        self.S.handle("bot", {"op": "ball", "session": "0123456789ab", "ball": {"kind": "done", "text": "直った"}})
        b = get()["ball"]
        self.assertEqual((b["kind"], b["who"], b["text"]), ("person", "alice", "直ったか確かめて済みに"))
        self.assertEqual(get()["state"], "open")                    # the sender closes it

    def test_bad_ref_and_outsiders(self):
        with self.assertRaises(ValueError):
            self.report("alice", ref="host1/alice/devbox/../../x")
        with self.assertRaises(LookupError):
            self.report("carol")                                 # not in the lab
        n = self.S.handle("alice", {"op": "add", "title": "mine", "visibility": "lab"})["node"]
        with self.assertRaises(LookupError):
            self.S.handle("bob", {"op": "report", "desk": n["id"], "title": "x"})
