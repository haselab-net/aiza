"""A devbox session linked to a work-tree node is shared read-only with
those who may see the node (plan stage 14).

    python3 -m unittest discover -s tests -v
"""
import getpass
import unittest

from test_shared_search import B


class TreeShareTest(unittest.TestCase):
    def setUp(self):
        self.me = getpass.getuser()
        self.nodes = []
        self.saved = (B.tree_call, B._in_lab_group)
        B.tree_call = lambda req: {"ok": True, "user": self.me, "nodes": self.nodes}
        B._in_lab_group = lambda u: u in ("bob", "carol")
        B._tree_share_cache["ts"] = 0.0

    def tearDown(self):
        B.tree_call, B._in_lab_group = self.saved
        B._tree_share_cache["ts"] = 0.0

    def node(self, **kw):
        n = dict({"id": "n000000000001", "owner": self.me, "members": [], "visibility": "self",
                  "links": {"session": "aaaaaaaaaa01"}}, **kw)
        self.nodes.append(n)
        B._tree_share_cache["ts"] = 0.0
        return n

    def meta(self, **kw):
        return dict({"id": "aaaaaaaaaa01", "preset": "claude-tui"}, **kw)

    def test_lab_node_shares_read_only(self):
        self.node(visibility="lab")
        self.assertEqual(B.share_mode(self.meta(), "bob"), "read")
        self.assertIsNone(B.share_mode(self.meta(), "mallory"))       # not in the lab

    def test_self_node_shares_with_members_only(self):
        self.node(members=["dave"])
        self.assertEqual(B.share_mode(self.meta(), "dave"), "read")
        self.assertIsNone(B.share_mode(self.meta(), "bob"))

    def test_never_host_root_or_mail(self):
        self.node(visibility="lab")
        for preset in ("host-shell", "root-shell") + tuple(B.MAIL_TREE_PRESETS):
            self.assertIsNone(B.share_mode(self.meta(preset=preset), "bob"), preset)
        self.assertIsNone(B.share_mode(self.meta(tmux_location="host"), "bob"))

    def test_someone_elses_session_id(self):
        # The same id linked by someone else is their session, not mine.
        self.node(visibility="lab", session_owner="zed")
        self.assertIsNone(B.share_mode(self.meta(), "bob"))

    def test_unlinked_session(self):
        self.node(visibility="lab", links={"session": "bbbbbbbbbb02"})
        self.assertIsNone(B.share_mode(self.meta(), "bob"))


class TakeTest(unittest.TestCase):
    """Taking someone's work on (plan stage 14, second half)."""

    def setUp(self):
        self.me = getpass.getuser()
        self.calls, self.made, self.sent, self.archived, self.shared = [], [], [], [], []
        self.nodes = [{"id": "n000000000001", "owner": "alice", "title": "解析", "visibility": "lab",
                       "links": {"session": "aaaaaaaaaa01"}, "session_owner": "alice"}]
        names = ("tree_call", "create_session", "send_initial_message", "archive_session", "stop_session",
                 "session_ref_from_session", "share_session", "send_push_notification", "append_event",
                 "load_meta", "send_message", "_in_lab_group")
        self.saved = {k: getattr(B, k) for k in names}

        def tree(req):
            self.calls.append(req)
            if req["op"] == "list":
                return {"ok": True, "user": self.me, "nodes": self.nodes}
            if req["op"] in ("take", "untake"):
                return {"ok": True, "node": {"id": req["id"]}}
            if req["op"] == "taken_for":
                return {"ok": True, "nodes": self.taken}
            return {"ok": True}
        B.tree_call = tree
        B.create_session = lambda preset, label, **kw: self.made.append((preset, label)) or {"id": "dddddddddd01"}
        B.send_initial_message = lambda sid, text, unlock_key=None: self.sent.append((sid, text))
        B.archive_session = lambda sid, flag: self.archived.append((sid, flag))
        B.stop_session = lambda sid: None
        B.session_ref_from_session = lambda sid, req: ("ok", "目的: 解析")
        B.share_session = lambda sid, user, mode="write": self.shared.append((sid, user, mode))
        B.send_push_notification = lambda sid, text: None
        B.append_event = lambda sid, ev: None
        B.send_message = lambda sid, text, **kw: self.sent.append((sid, text))
        B._in_lab_group = lambda u: True
        B._tree_share_cache["ts"] = 0.0
        self.taken = []

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        B._tree_share_cache["ts"] = 0.0

    def test_take_makes_a_session_with_a_note(self):
        import threading
        r = B.tree_take("n000000000001")
        for th in threading.enumerate():
            if th is not threading.current_thread() and th.daemon:
                th.join(timeout=1)
        self.assertEqual(r["session"], "dddddddddd01")
        self.assertEqual(self.made, [("claude-tui", "解析")])
        self.assertIn({"op": "take", "id": "n000000000001", "session": "dddddddddd01"}, self.calls)
        self.assertTrue(any("alice/aaaaaaaaaa01" in t and "目的: 解析" in t for _, t in self.sent))

    def test_take_uses_the_start_screens_choices(self):
        # the deployment notes 段3: what runs where and its name, from the start screen.
        import threading
        made = []
        B.create_session = lambda preset, label, **kw: made.append((preset, label, kw)) or {"id": "dddddddddd02"}
        B.tree_take("n000000000001", "codex-tui", "引き取りの名前", "proj", False)
        for th in threading.enumerate():
            if th is not threading.current_thread() and th.daemon:
                th.join(timeout=1)
        self.assertEqual(made, [("codex-tui", "引き取りの名前", {"cwd": "proj", "skip_permissions": False})])

    def test_untake_archives_the_new_session(self):
        self.nodes[0].update(links={"session": "dddddddddd01"}, taken={"by": self.me, "state": "taken"})
        B.load_meta = lambda sid: {"id": sid}
        B.tree_untake("n000000000001")
        self.assertEqual(self.archived, [("dddddddddd01", True)])

    def test_join_write_only_for_tree_readers(self):
        self.nodes[0].update(owner=self.me, session_owner=self.me)
        B.load_meta = lambda sid: {"id": sid, "preset": "claude-tui"}
        B.tree_join_write("aaaaaaaaaa01", "bob")
        self.assertEqual(self.shared, [("aaaaaaaaaa01", "bob", "write")])
        B.load_meta = lambda sid: {"id": sid, "preset": "root-shell"}
        with self.assertRaises(LookupError):
            B.tree_join_write("aaaaaaaaaa01", "bob")

    def test_previous_holder_is_told_once(self):
        self.taken = [{"id": "n000000000001", "title": "解析",
                       "taken": {"by": "carol", "state": "taken", "from_session": "aaaaaaaaaa01"}}]
        B.load_meta = lambda sid: {"id": sid, "alive": True}
        B.tree_taken_notify()
        self.assertTrue(self.sent and "carol" in self.sent[0][1] and "push" in self.sent[0][1])
        self.assertIn({"op": "ack_taken", "id": "n000000000001"}, self.calls)


if __name__ == "__main__":
    unittest.main()
