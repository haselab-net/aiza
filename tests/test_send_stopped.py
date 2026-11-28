"""A text sent to a stopped session is never dropped (2026-11-27, the user:
停止中のセッションに送ると、メッセージが捨てられることがあります。再開してから
送るようにしてください。できなければ、入力欄に戻るようにしてください).

POST /messages to a stopped session answers 409 {stopped} and writes and
sends nothing (the page resumes it and sends again with wait_ready, or puts
the text back in the box); with wait_ready, a session whose input is not up
in time gets nothing (503 not_ready). A talkto to a member it resumed goes
in only once the member takes input; if it does not, the sender is told in
its input, with the text. A menu's cursor is not an input line.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from test_shared_search import B

RUN, STOPPED, HEADLESS = "cccc000000000001", "cccc000000000002", "cccc000000000003"


class SendToStoppedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sent, self.ready = [], True
        self.make(RUN, "claude-tui")
        self.make(STOPPED, "claude-tui", stopped=True, alive=False)
        self.make(HEADLESS, "claude", stopped=True, alive=False)
        stubs = {
            "session_roots": lambda: [self.root],
            "_meta_fits_root": lambda sdir, meta: True,
            "_unlockd_call": lambda verb, **f: {"ok": True, "unlocked": True, "tier": "root", "expires_at": 9e9},
            "list_tmux_sessions": lambda: [], "list_host_tmux_sessions": lambda: [], "list_root_tmux_sessions": lambda: [],
            "ensure_watcher": lambda sid: None, "_load_links": lambda: {}, "expire_links": lambda: None,
            "send_message": lambda sid, text, submit=True, from_user=None: self.sent.append((sid, text, from_user)),
            "_wait_prompt": lambda sid, wait=None: self.ready,
            "task_user_sent": lambda sid: None,
        }
        self.saved = {n: getattr(B, n) for n in stubs if hasattr(B, n)}
        for n, fn in stubs.items():
            setattr(B, n, fn)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), B.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for n, fn in self.saved.items():
            setattr(B, n, fn)
        self.tmp.cleanup()

    def make(self, sid, preset, **more):
        d = self.root / sid
        d.mkdir()
        meta = {"id": sid, "label": sid, "preset": preset, "tmux_location": "container", "tmux_name": sid, **more}
        (d / "meta.json").write_text(json.dumps(meta))
        (d / "events.jsonl").write_text(json.dumps({"type": "user_message", "seq": 1, "ts": 1, "text": "hi"}) + "\n")

    def events(self, sid):
        return (self.root / sid / "events.jsonl").read_text()

    def last_text(self, sid):
        return json.loads(self.events(sid).splitlines()[-1]).get("text", "")

    def post(self, sid, body):
        url = f"http://127.0.0.1:{self.server.server_port}/sessions/{sid}/messages"
        r = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_a_stopped_session_is_said_and_nothing_is_written_or_sent(self):
        before = self.events(STOPPED)
        code, body = self.post(STOPPED, {"text": "作りもの", "typed": True})
        self.assertEqual(code, 409)
        self.assertTrue(body.get("stopped") and body.get("not_sent"))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.events(STOPPED), before)

    def test_a_headless_session_is_not_refused_for_being_stopped(self):
        self.assertEqual(self.post(HEADLESS, {"text": "作りもの"})[0], 202)

    def test_wait_ready_sends_only_once_its_input_is_up(self):
        self.ready = False
        code, body = self.post(RUN, {"text": "作りもの", "wait_ready": True})
        self.assertEqual(code, 503)
        self.assertTrue(body.get("not_ready") and body.get("not_sent"))
        self.assertEqual(self.sent, [])
        self.ready = True
        self.assertEqual(self.post(RUN, {"text": "作りもの", "wait_ready": True})[0], 202)
        self.assertEqual([s[:2] for s in self.sent], [(RUN, "作りもの")])

    def test_a_pane_that_refuses_it_leaves_a_note_under_it(self):
        def refuse(sid, text, submit=True, from_user=None):
            raise RuntimeError("tmux send-keys failed: can't find session")
        B.send_message = refuse
        self.assertEqual(self.post(RUN, {"text": "作りもの"})[0], 502)
        self.assertIn("届いていません", self.last_text(RUN))

    def test_a_talkto_to_a_resumed_member_that_does_not_come_up_goes_back_to_the_sender(self):
        self.ready = False
        self.assertFalse(B._send_when_ready(STOPPED, "前置き\n[🔗] 作りもの", "🔗 RUN", RUN, "作りもの"))
        self.assertEqual(len(self.sent), 1)
        to, text, who = self.sent[0]
        self.assertEqual(to, RUN)                 # the sender, not the member
        self.assertIn("届いていません", text)
        self.assertTrue(text.endswith("作りもの"))   # with the text, to send again
        self.sent.clear()
        self.ready = True
        self.assertTrue(B._send_when_ready(STOPPED, "作りもの", "🔗 RUN", RUN, "作りもの"))
        self.assertEqual([s[0] for s in self.sent], [STOPPED])

    def test_with_no_sender_the_text_stays_in_that_sessions_chat(self):
        self.ready = False
        self.assertFalse(B._send_when_ready(RUN, "作りもの", "🔐 AI座"))
        self.assertEqual(self.sent, [])
        self.assertIn("作りもの", self.last_text(RUN))


class InputReadyTest(unittest.TestCase):
    def ready(self, screen):
        B._latest_screen["cccc0000000000ff"] = screen
        B._screen_waiting.pop("cccc0000000000ff", None)
        try:
            return B._input_ready("cccc0000000000ff")
        finally:
            B._latest_screen.pop("cccc0000000000ff", None)

    def test_an_input_line_is_ready_and_a_menu_is_not(self):
        self.assertTrue(self.ready("──\n❯ \n──\n  ⏵⏵ bypass permissions on"))
        self.assertTrue(self.ready("──\n❯ \n──"))
        self.assertTrue(self.ready("› \n  ? for shortcuts"))
        self.assertFalse(self.ready("Resume?\n❯ 1. Resume from summary\n  2. Resume full session"))
        self.assertFalse(self.ready(" ❯ 1. Yes, proceed\n   2. No"))
        self.assertFalse(self.ready("Resuming conversation…"))
        self.assertFalse(self.ready(""))


if __name__ == "__main__":
    unittest.main()
