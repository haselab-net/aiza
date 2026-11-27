"""Sending to a session on a sleeping ssh machine without making the sender
wait (the deployment notes, send_message_waking): talkto's relay answers at once
with 起こしています and the text goes in once, after the machine answers; a
machine that does not wake gets nothing and the sender is told. A machine
that answers, or one that cannot be woken, is sent to at once as before.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_shared_search import B

A, P = "aaaaaaaaaab1", "aaaaaaaaaab2"
MACHINES = {
    "pc": {"tmux": "/usr/bin/tmux", "wol_mac": "02:00:5e:10:20:30", "wol_via": "jump", "wol_broadcast": "10.0.0.255"},
    "other": {"tmux": "/usr/bin/tmux"},   # no wol_*: cannot be woken
}


class HeldThread:
    """threading.Thread whose start() only queues; the test runs it."""
    queue = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        HeldThread.queue.append(self)

    def run_now(self):
        self.target(*self.args, **self.kwargs)


class SshWakeSendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        names = ("LINKS_PATH", "STATE_DIR", "session_dir", "send_message", "append_event",
                 "ssh_reachable", "ssh_reachable_or_wake", "handoff_record")
        self.saved = {n: getattr(B, n) for n in names}
        B.STATE_DIR = self.root
        B.LINKS_PATH = self.root / "links.json"
        B.session_dir = lambda sid: self.root / sid
        self.sent, self.events, self.woken, self.handoffs = [], [], [], []
        B.send_message = lambda sid, text, submit=True, from_user=None: self.sent.append((sid, text, from_user))
        B.append_event = lambda sid, ev: self.events.append((sid, ev))
        B.handoff_record = lambda frm, to, text: self.handoffs.append((frm, to))
        self.awake = {"pc": False, "other": False}
        self.wakes_up = True
        B.ssh_reachable = lambda m, wait=True: self.awake[m]

        def wake(m, wait=B.SSH_WAKE_WAIT):
            self.woken.append(m)
            self.awake[m] = self.wakes_up
            return self.wakes_up
        B.ssh_reachable_or_wake = wake
        p = mock.patch.dict(B.SSH_MACHINES, MACHINES, clear=True)
        p.start()
        self.addCleanup(p.stop)
        t = mock.patch.object(B.threading, "Thread", HeldThread)
        t.start()
        self.addCleanup(t.stop)
        HeldThread.queue = []
        for sid, label, loc, preset in ((A, "box", "container", "claude-tui"),
                                        (P, "ssh の Claude", "ssh:pc", "claude-tui-pc")):
            (self.root / sid).mkdir()
            (self.root / sid / "meta.json").write_text(json.dumps(
                {"id": sid, "label": label, "tmux_location": loc, "preset": preset}))
            (self.root / sid / "events.jsonl").write_text(json.dumps({"seq": 1, "type": "user_message", "text": "x"}) + "\n")
        self.awake["pc"] = True             # linked while awake: the link's own notice is not the test
        B.create_link(A, P, forever=True)
        self.awake["pc"] = False
        self.sent.clear()
        self.events.clear()
        self.assertEqual(HeldThread.queue, [])

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(B, n, v)
        self.tmp.cleanup()

    def to_p(self):
        return [s for s in self.sent if s[0] == P]

    def run_threads(self):
        q, HeldThread.queue = HeldThread.queue, []
        for t in q:
            t.run_now()

    def test_awake_machine_sent_at_once(self):
        self.awake["pc"] = True
        status, msg = B._relay_to_partner(A, B.TalktoText("ラベルを刷って"))
        self.assertEqual(status, "delivered")
        self.assertIn("届きました", msg)
        self.assertEqual(len(self.to_p()), 1)
        self.assertEqual(self.woken, [])
        self.assertEqual(self.handoffs, [(A, P)])

    def test_sleeping_machine_woken_then_sent_once(self):
        status, msg = B._relay_to_partner(A, B.TalktoText("ラベルを刷って"))
        self.assertEqual(status, "delivered")
        self.assertIn("起こしています", msg)
        self.assertEqual(self.to_p(), [])            # not yet: the sender did not wait
        self.assertEqual(self.woken, [])
        self.run_threads()
        self.assertEqual(self.woken, ["pc"])
        self.assertEqual(len(self.to_p()), 1)        # once, after it woke
        self.assertIn("ラベルを刷って", self.to_p()[0][1])
        self.assertEqual(self.handoffs, [(A, P)])
        self.assertEqual([s for s in self.sent if s[0] == A], [])

    def test_not_woken_nothing_sent_sender_told(self):
        self.wakes_up = False
        status, msg = B._relay_to_partner(A, B.TalktoText("ラベルを刷って"))
        self.assertIn("起こしています", msg)
        self.run_threads()
        self.assertEqual(self.to_p(), [])
        told = [s for s in self.sent if s[0] == A]
        self.assertEqual(len(told), 1)
        self.assertIn("起きなかった", told[0][1])
        self.assertEqual(self.handoffs, [])

    def test_unwakeable_machine_sent_at_once_as_before(self):
        meta = json.loads((self.root / P / "meta.json").read_text()) | {"tmux_location": "ssh:other", "preset": "claude-tui-other"}
        (self.root / P / "meta.json").write_text(json.dumps(meta))
        status, msg = B._relay_to_partner(A, B.TalktoText("x"))
        self.assertIn("届きました", msg)
        self.assertEqual(len(self.to_p()), 1)
        self.assertEqual(HeldThread.queue, [])

    def test_notice_default_failure_goes_to_chat(self):
        self.wakes_up = False
        self.assertFalse(B.send_message_waking(P, "Issue が Ready に戻りました"))
        self.run_threads()
        self.assertEqual(self.to_p(), [])
        self.assertEqual(len(self.events), 1)
        sid, ev = self.events[0]
        self.assertEqual(sid, P)
        self.assertIn("起きなかった", ev["text"])

    def test_notice_on_sent_after_wake(self):
        done = []
        self.assertFalse(B.send_message_waking(P, "⏰", on_sent=lambda: done.append(1)))
        self.assertEqual(done, [])
        self.run_threads()
        self.assertEqual(done, [1])
        self.assertEqual(len(self.to_p()), 1)

    def test_container_session_untouched(self):
        self.assertTrue(B.send_message_waking(A, "y"))
        self.assertEqual(self.sent, [(A, "y", None)])
        self.assertEqual(self.woken, [])


if __name__ == "__main__":
    unittest.main()
