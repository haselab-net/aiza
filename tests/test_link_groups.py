"""Session links as groups that survive a stop (the deployment notes,
2026-11-08): three or more sessions in one link, talkto to everyone or
`--to` one, a stopped member stays linked and is told so when resumed.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

A, B2, C, D = "aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa4"


class LinkGroupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = {n: getattr(B, n) for n in ("LINKS_PATH", "STATE_DIR", "session_dir", "send_message", "append_event")}
        B.STATE_DIR = self.root
        B.LINKS_PATH = self.root / "links.json"
        B.session_dir = lambda sid: self.root / sid
        self.sent = []
        B.send_message = lambda sid, text, submit=True, from_user=None: self.sent.append((sid, text))
        self.events = []
        B.append_event = lambda sid, ev: self.events.append((sid, ev))
        for sid, label in ((A, "aizaE"), (B2, "root"), (C, "devbox"), (D, "other")):
            (self.root / sid).mkdir()
            self.meta(sid, label=label)
            self.had_a_turn(sid)

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(B, n, v)
        self.tmp.cleanup()

    def meta(self, sid, **kw):
        p = self.root / sid / "meta.json"
        m = json.loads(p.read_text()) if p.exists() else {"id": sid, "tmux_location": "container", "preset": "claude-tui"}
        m.update(kw)
        p.write_text(json.dumps(m))

    def had_a_turn(self, sid):
        (self.root / sid / "events.jsonl").write_text(json.dumps({"seq": 1, "type": "user_message", "text": "x"}) + "\n")

    def fresh(self, sid, **kw):
        """A new session: its screen shown, nothing sent to it yet."""
        (self.root / sid / "events.jsonl").write_text(json.dumps({"seq": 1, "type": "agent_output", "text": "Claude Code"}) + "\n")
        self.meta(sid, **kw)

    def test_third_joins_and_broadcast(self):
        B.create_link(A, B2, forever=True)
        self.sent.clear()
        rec = B.create_link(C, A)  # C joins A's link
        self.assertEqual(rec["members"], [A, B2, C])
        self.assertIsNone(rec["expires_ts"])  # keeps the link's own limit
        # only the newcomer gets a turn (2026-11-25, the user via aiza3: 加わるたびに
        #全員にアナウンスのターンが入る); the others see it in the chat and with talkto --list
        self.assertEqual([sid for sid, _ in self.sent], [C])
        self.assertIn("`talkto`", self.sent[0][1])
        self.assertTrue(all(any(s == m and "加わりました" in ev["text"] for s, ev in self.events) for m in (A, B2, C)))
        self.sent.clear()
        status, msg = B._relay_to_partner(A, B.TalktoText("こんにちは"))
        self.assertEqual(status, "delivered")
        self.assertEqual(sorted(s for s, _ in self.sent), [B2, C])
        self.assertTrue(all(t.startswith("[🔗「aizaE」から] ") for _, t in self.sent))

    def test_a_stopped_session_can_be_linked_not_an_archived_one(self):
        # 2026-11-20, the user: 停止してるセッションも talkto のリンクに加えられるように
        self.meta(C, stopped=True)
        rec = B.create_link(A, C, forever=True)
        self.assertEqual(rec["members"], [A, C])
        self.meta(D, stopped=True)
        self.assertEqual(B.create_link(D, A)["members"], [A, C, D])         # joins too
        self.meta(B2, stopped=True, archived=True)
        with self.assertRaises(ValueError):
            B.create_link(B2, A)

    def test_to_one(self):
        B.create_link(A, B2)
        B.create_link(A, C)
        self.sent.clear()
        t = B.TalktoText("だけに")
        t.to = "devbox"
        self.assertEqual(B._relay_to_partner(A, t)[0], "delivered")
        self.assertEqual([s for s, _ in self.sent], [C])
        t.to = "nobody"
        status, msg = B._relay_to_partner(A, t)
        self.assertEqual(status, "no_target")
        self.assertIn("「root」", msg)

    def test_stopped_member_stays(self):
        B.create_link(A, B2)
        self.meta(B2, stopped=True)
        status, msg = B._relay_to_partner(A, B.TalktoText("x"))
        self.assertEqual(status, "stopped")
        self.assertTrue(B._session_is_linked(A) and B._session_is_linked(B2))
        self.meta(B2, stopped=False)
        # it was told when the link was made, and remembers (2026-11-18): nothing on resume
        self.assertIsNone(B.link_resumed_note(B2))
        self.assertIsNone(B.link_resumed_note(D))

    def test_resumed_member_hears_only_news(self):
        self.meta(B2, stopped=True)
        B.create_link(A, B2)  # linked while stopped: told when resumed
        B.create_link(A, C)
        self.assertNotIn(B2, [s for s, _ in self.sent])
        self.meta(B2, stopped=False)
        note = B.link_resumed_note(B2)
        self.assertEqual(note, "[AI座 セッション連携] 他のAIと`talkto`コマンドで通信できます。")
        self.assertIsNone(B.link_resumed_note(B2))  # once only
        self.meta(C, stopped=True)
        B.create_link(D, A)  # a newcomer is no news for a member already told
        self.meta(C, stopped=False)
        self.assertIsNone(B.link_resumed_note(C))

    def test_stopped_member_is_resumed(self):
        # 2026-11-18, the user: "talk to 先が止まってるときは自動再開させる仕組みを入れたい"
        B.create_link(A, B2)
        self.meta(B2, stopped=True, claude_session_id="c0ffee", cwd="/w", label="root")
        made, sent_later = [], []
        saved = {n: getattr(B, n) for n in ("create_session", "_send_when_ready", "handoff_record")}

        def create_session(preset, label, cwd=None, resume=None, skip_permissions=True, replace_session=None, **kw):
            made.append((preset, label, cwd, resume, replace_session))
            self.meta(replace_session, stopped=False)
            return {"id": replace_session}
        B.create_session = create_session
        B._send_when_ready = lambda sid, text, who, origin=None: sent_later.append((sid, text, who))
        B.handoff_record = lambda *a: None
        try:
            status, msg = B._relay_to_partner(A, B.TalktoText("起きて"))
            import time
            time.sleep(0.1)
        finally:
            for n, v in saved.items():
                setattr(B, n, v)
        self.assertEqual(status, "delivered")
        self.assertIn("再開しました", msg)
        self.assertEqual(made, [("claude-tui", "root", "/w", "c0ffee", B2)])
        self.assertEqual(len(sent_later), 1)
        sid, text, who = sent_later[0]
        self.assertEqual(sid, B2)
        self.assertTrue(text.endswith("起きて"))
        self.assertNotIn("[AI座 セッション連携]", text)  # it was told when linked
        # one with nothing to resume (a shell where claude never ran) is left stopped, and says so
        self.meta(B2, stopped=True, preset="shell", claude_session_id=None)
        status, msg = B._relay_to_partner(A, B.TalktoText("x"))
        self.assertEqual(status, "stopped")
        self.assertIn("再開できない", msg)

    def test_host_resume_skips_the_window_only_for_a_resume(self):
        # 2026-11-18, the user: "相手が root や mailboxでも再開させたい" "再開は問題ありません"
        saved = B._unlockd_call
        B._unlockd_call = lambda verb, **kw: {"ok": False}
        try:
            B._REQ.talkto_wake = True
            B._REQ.creating_new = False
            B.require_unlock_if_outside_sandbox("host")  # a resume: passes
            B._REQ.creating_new = True
            with self.assertRaises(B.UnlockRequired):
                B.require_unlock_if_outside_sandbox("host")  # a new session: not
            B._REQ.creating_new = False
            with self.assertRaises(B.UnlockRequired):
                B.require_unlock_if_outside_sandbox("root")  # never the root tier
            B._REQ.talkto_wake = False
            with self.assertRaises(B.UnlockRequired):
                B.require_unlock_if_outside_sandbox("host")  # nor outside a talkto resume
        finally:
            B._unlockd_call = saved
            B._REQ.talkto_wake = False
            B._REQ.creating_new = False

    def test_root_shell_is_left_to_root(self):
        B.create_link(A, B2)
        self.sent.clear()
        self.meta(B2, stopped=True, preset="root-shell", claude_session_id="c0ffee", claude_cwd="/root")
        saved = {n: getattr(B, n) for n in ("create_session", "WAKE_DIR", "load_meta")}
        real_load = B.load_meta

        def create_session(*a, **kw):
            raise B.UnlockRequired("locked", tier="root")
        B.create_session = create_session
        B.WAKE_DIR = str(self.root / "wake")
        (self.root / "wake").mkdir()
        # a root session's meta lives in the host-only store; here, as if read from there
        B.load_meta = lambda sid: (json.loads((self.root / sid / "meta.json").read_text()) | {"tmux_location": "root"}
                                   if sid == B2 else real_load(sid))
        try:
            status, msg = B._relay_to_partner(A, B.TalktoText("root へ"))
        finally:
            for n, v in saved.items():
                setattr(B, n, v)
        self.assertEqual(status, "unlock")
        self.assertIn("root に再開を頼みました", msg)
        self.assertEqual(sorted(p.name for p in (self.root / "wake").iterdir()), [B2])
        self.assertEqual(self.sent, [])

    def test_leave_and_dissolve(self):
        B.create_link(A, B2)
        B.create_link(C, B2)
        B.break_link(C)
        self.assertEqual(B.list_links()[0]["members"], [A, B2])
        B.break_link(A)
        self.assertEqual(B.list_links(), [])

    def test_two_links_merge(self):
        # 2026-11-25, the user via aiza3: グループ同士をつなぎたいときがある
        import time
        B.create_link(A, B2, duration_sec=3600)
        self.meta(D, stopped=True)
        B.create_link(C, D, duration_sec=7200)                       # D is told when resumed
        self.sent.clear()
        rec = B.create_link(A, C)
        self.assertEqual(rec["members"], [A, B2, C, D])
        self.assertAlmostEqual(rec["expires_ts"], time.time() + 7200, delta=5)   # the longer one
        self.assertEqual(rec["untold"], [D])
        self.assertEqual(len(B.list_links()), 1)
        self.assertEqual(self.sent, [])                               # no turn for anyone
        self.assertTrue(all(any(s == m and "まとめました" in ev["text"] for s, ev in self.events) for m in (A, B2, C, D)))
        with self.assertRaises(ValueError):
            B.create_link(B2, D)                                      # now the same link

    def test_merge_with_a_forever_link_is_forever(self):
        B.create_link(A, B2, duration_sec=3600)
        B.create_link(C, D, forever=True)
        self.assertIsNone(B.create_link(B2, D)["expires_ts"])

    def test_list(self):
        self.assertEqual(B.link_list_from_session(A)[0], "no_link")
        self.meta(B2, preset="root-shell", launch="claude", tmux_location="root")
        self.meta(C, preset="codex-tui", stopped=True)
        self.meta(D, preset="shell")
        B.create_link(A, B2, forever=True)
        B.create_link(C, A)
        B.create_link(D, A)
        self.sent.clear()
        status, msg = B.link_list_from_session(A)
        self.assertEqual(status, "list")
        self.assertEqual(self.sent, [])                               # sends nothing
        lines = msg.splitlines()
        self.assertIn("3人", lines[0])
        self.assertIn("自動では切れません", lines[0])
        self.assertEqual(lines[1:], ["「root」 Claude・root・動いている",
                                     "「devbox」 Codex・devbox・止まっている(talkto で再開することがあります)",
                                     "「other」 シェル・devbox・動いている"])
        self.assertEqual(B._member_kind({"preset": "shell", "tmux_location": "ssh:winbox-a"}), "シェル・ssh 機 winbox-a")
        self.assertEqual(B._member_kind({"preset": "host-shell", "launch": "codex", "tmux_location": "host"}), "Codex・ホスト")
        # claude typed by hand in a root shell
        self.assertEqual(B._member_kind({"preset": "root-shell", "tmux_location": "root", "claude_session_id": "c0ffee"}), "Claude・root")
        (self.root / D / "codex-active.json").write_text(json.dumps({"session_id": "019a0000-0000-7000-8000-000000000001"}))
        self.assertEqual(B._member_kind({"preset": "shell"}, D), "Codex・devbox")       # codex typed by hand
        self.assertNotIn("「aizaE」", msg)                            # not itself
        line = json.dumps({"id": "abc", "list": True}).encode()
        self.assertEqual(B._parse_talkto_lines([line]), [("abc", ("list", None))])
        t = B.TalktoText("x")
        t.to = "nobody"
        self.assertIn("talkto --list", B._relay_to_partner(A, t)[1])

    def test_old_record_and_replaced_id(self):
        B.LINKS_PATH.write_text(json.dumps({"x1": {"a": A, "b": B2, "created_ts": 1, "expires_ts": None}}))
        self.assertEqual(B.list_links()[0]["members"], [A, B2])
        B.link_replace_member(B2, C)
        self.assertEqual(B.list_links()[0]["members"], [A, C])

    def test_talkto_to_field(self):
        line = json.dumps({"id": "abc", "text": "hi", "to": "root"}).encode()
        [(item_id, text)] = B._parse_talkto_lines([line])
        self.assertEqual((item_id, str(text), text.to), ("abc", "hi", "root"))


if __name__ == "__main__":
    unittest.main()
