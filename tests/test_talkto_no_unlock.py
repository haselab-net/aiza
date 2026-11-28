"""A talkto goes in whatever the passkey window (the deployment notes,
2026-11-28, the user: 「ルート同士だけでなく鍵に関係なく届くようにしてください。
開発の箱、メールの箱を含めてです。」): from any kind of session to any kind
(devbox, host, Email, root), and the notices back to its sender. Why these
tests: the window is lifted only around the relay's own typing, so they
show (1) every pair goes through with the window closed, (2) the same
send outside a relay -- the page's send, open, card answer -- is still
refused, (3) the lift does not leak past the relay (also when it fails),
(4) the line still says who sent it, and only a linked member gets it.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

DEV, HOST, MAIL, ROOT, OUT = "bbbbbbbbbbb1", "bbbbbbbbbbb2", "bbbbbbbbbbb3", "bbbbbbbbbbb4", "bbbbbbbbbbb5"
KINDS = {DEV: ("devbox", "container", "claude-tui"), HOST: ("host", "host", "claude-tui-host"),
         MAIL: ("mail", "host", "mail-tui"), ROOT: ("root", "root", "root-shell"),
         OUT: ("outsider", "root", "root-shell")}


def to(name, text):
    t = B.TalktoText(text)
    t.to = name
    return t


class TalktoNoUnlockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        names = ("LINKS_PATH", "STATE_DIR", "session_dir", "send_message", "append_event", "_unlockd_call", "load_meta")
        self.saved = {n: getattr(B, n) for n in names}
        B.STATE_DIR = self.root
        B.LINKS_PATH = self.root / "links.json"
        B.session_dir = lambda sid, *a, **kw: self.root / sid
        # host/root metas live in the host-only store; here, all in one place
        B.load_meta = lambda sid: (json.loads((self.root / sid / "meta.json").read_text())
                                   if (self.root / sid / "meta.json").is_file() else None)
        # The window is closed: aiza-unlockd says no to every touch.
        B._unlockd_call = lambda verb, **kw: {"ok": False, "error": "locked"}
        self.sent = []

        def send_message(sid, text, submit=True, from_user=None):
            # What the real send_message does first, for the target's place.
            B.require_unlock_if_outside_sandbox(B.load_meta(sid)["tmux_location"])
            self.sent.append((sid, text, from_user))
        B.send_message = send_message
        self.events = []
        B.append_event = lambda sid, ev: self.events.append((sid, ev))
        for sid, (label, loc, preset) in KINDS.items():
            (self.root / sid).mkdir()
            (self.root / sid / "meta.json").write_text(json.dumps(
                {"id": sid, "label": label, "tmux_location": loc, "preset": preset}))
            (self.root / sid / "events.jsonl").write_text(
                json.dumps({"seq": 1, "type": "user_message", "text": "x"}) + "\n")
        B.create_link(DEV, HOST, forever=True)
        for sid in (MAIL, ROOT):
            B.create_link(sid, DEV)
        self.sent.clear()
        self.events.clear()

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(B, n, v)
        B._REQ.talkto_relay = False
        self.tmp.cleanup()

    def test_every_kind_reaches_every_kind_with_the_window_closed(self):
        members = (DEV, HOST, MAIL, ROOT)
        for a in members:
            for b in members:
                if a == b:
                    continue
                self.sent.clear()
                status, msg = B._relay_to_partner(a, to(KINDS[b][0], f"{a}→{b}"))
                self.assertEqual(status, "delivered", (KINDS[a][0], KINDS[b][0], msg))
                self.assertEqual([s for s, _, _ in self.sent], [b])
        self.assertFalse(getattr(B._REQ, "talkto_relay", False))  # nothing left lifted

    def test_the_line_says_who_sent_it(self):
        B._relay_to_partner(ROOT, to("mail", "root から"))
        (sid, text, who), = self.sent
        self.assertEqual((sid, who), (MAIL, "🔗 root"))
        self.assertTrue(text.startswith("[🔗「root」から(あなただけに)] "))

    def test_only_a_linked_member_gets_it(self):
        status, _ = B._relay_to_partner(OUT, to("root", "つながっていない"))
        self.assertEqual(status, "no_link")
        status, _ = B._relay_to_partner(ROOT, to("outsider", "つながっていない相手へ"))
        self.assertEqual(status, "no_target")
        self.assertEqual(self.sent, [])

    def test_the_page_still_needs_the_window(self):
        # Outside a relay (the page's send, open, card answer) nothing changed.
        for loc in ("host", "root"):
            with self.assertRaises(B.UnlockRequired):
                B.require_unlock_if_outside_sandbox(loc)
        B.require_unlock_if_outside_sandbox("container")  # never needed one

    def test_the_lift_ends_with_the_relay_even_when_it_fails(self):
        with self.assertRaises(RuntimeError):
            with B._talkto_relaying():
                B.require_unlock_if_outside_sandbox("root")
                raise RuntimeError("pane gone")
        with self.assertRaises(B.UnlockRequired):
            B.require_unlock_if_outside_sandbox("root")

    def test_the_sender_is_told_in_its_pane_with_the_window_closed(self):
        B._tell_sender_undelivered(ROOT, "mail", "入力に入れられなかった", "もう一度")
        B._tell_sender_not_woken(HOST, "winbox", "応答なし")
        self.assertEqual([s for s, _, _ in self.sent], [ROOT, HOST])
        self.assertEqual(self.events, [])  # not the chat-line fallback


if __name__ == "__main__":
    unittest.main()
