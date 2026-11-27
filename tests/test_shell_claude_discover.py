"""_watch_shell_claude for a `claude` typed by hand in a shell pane, when
aiza does not know its conversation id (no pre-assigned id, no SessionStart
hook): which log it takes (one written in the last 3 minutes when the
backend finds Claude already running, else the next new one), that Claude
leaving the pane turns the chat back to the screen, and what a log it
cannot read does (root: ask for the permission fix-up on a schedule, then
say so once).

    python3 -m unittest discover -s tests -v

The stand-ins (tmux, the pane's $HOME) are test_shell_claude_watcher's;
here the pane's foreground command is the test's to set.
"""
import json
import os
import subprocess
import threading
import time
import unittest

import test_shell_claude_watcher as W
from test_shared_search import B
from test_shell_claude_watcher import CWD, NEW, OLD, assistant

THIRD = "0c000000-0000-4000-8000-000000000003"


class ShellClaudeDiscoverTest(unittest.TestCase):
    _n = 0
    write, chat, shown, settle = W.WatcherTest.write, W.WatcherTest.chat, W.WatcherTest.shown, W.WatcherTest.settle

    def setUp(self):
        W.WatcherTest.setUp(self)
        self.addCleanup(W.WatcherTest.tearDown, self)
        meta = self.root / self.sid / "meta.json"
        m = json.loads(meta.read_text())
        del m["claude_session_id"]                        # a `claude` aiza did not start
        meta.write_text(json.dumps(m))
        self.command, self.query_fails = "claude", None
        self.saved_more = {n: getattr(B, n) for n in ("tmux_query", "_conv_hooked", "_claude_foreground")}
        self.addCleanup(lambda: [setattr(B, n, v) for n, v in self.saved_more.items()])
        B.tmux_query = self.query
        B._conv_hooked = set()
        B._claude_foreground = {}

    def query(self, location, args, timeout=15):
        if self.query_fails == "timeout":
            raise subprocess.TimeoutExpired(args, timeout)
        if self.query_fails == "error":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="no pane")
        if self.query_fails == "garbled":
            return subprocess.CompletedProcess(args, 0, stdout="claude\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=f"{self.command}|{CWD}\n", stderr="")

    def start(self):
        self.thread = threading.Thread(target=B._watch_shell_claude, args=(self.sid,), daemon=True)
        self.thread.start()

    def age(self, conv, seconds):
        p = self.proj / f"{conv}.jsonl"
        t = time.time() - seconds
        os.utime(p, (t, t))

    def foreground(self):
        return bool(B._claude_foreground.get(self.sid))

    # -- tests --
    def test_claude_already_running_takes_the_recent_log_without_replaying_it(self):
        self.write(OLD, assistant("ずっと前の会話"))
        self.age(OLD, 3600)
        self.write(NEW, assistant("さっきの返事"))      # written a minute ago: Claude was mid-conversation
        self.age(NEW, 60)
        self.start()
        self.settle(self.foreground)
        self.write(NEW, assistant("続き"))
        self.write(OLD, assistant("古い方"))
        self.settle(lambda: self.shown())
        self.assertEqual(self.shown(), ["続き"])

    def test_with_nothing_recent_the_next_new_log_is_taken(self):
        self.write(OLD, assistant("ずっと前の会話"))
        self.age(OLD, 3600)
        self.start()
        self.settle(self.foreground)
        time.sleep(0.1)
        self.write(NEW, assistant("新しい会話"))
        self.settle(lambda: self.shown())
        self.write(NEW, assistant("その続き"))
        self.settle(lambda: len(self.shown()) >= 2)
        self.assertEqual(self.shown(), ["新しい会話", "その続き"])

    def test_a_log_another_session_holds_is_passed_over(self):
        self.start()
        self.settle(self.foreground)
        B._claimed_transcripts[(str(self.proj), f"{THIRD}.jsonl")] = "someone-else"
        self.write(THIRD, assistant("あちらの会話"))
        time.sleep(0.1)
        self.write(NEW, assistant("こちらの会話"))
        self.settle(lambda: self.shown())
        self.assertEqual(self.shown(), ["こちらの会話"])

    def test_with_the_hook_known_it_waits_for_the_hook_instead(self):
        B._conv_hooked.add(self.sid)
        self.start()
        self.settle(self.foreground)
        self.write(NEW, assistant("フックがまだ"))
        time.sleep(0.3)
        self.assertEqual(self.shown(), [])

    def test_claude_leaving_the_pane_hands_the_chat_back_to_the_screen(self):
        self.start()
        self.settle(self.foreground)
        self.assertTrue(self.foreground())
        self.command = "bash"
        self.settle(lambda: not self.foreground())
        self.assertFalse(self.foreground())
        self.command = "claude"
        self.settle(self.foreground)
        self.assertTrue(self.foreground())

    def test_a_pane_that_does_not_answer_is_skipped(self):
        for how in ("timeout", "error", "garbled"):
            self.query_fails = how
            if self.thread is None:
                self.start()
            time.sleep(0.1)
            self.assertFalse(self.foreground(), how)
        self.query_fails = None
        self.settle(self.foreground)
        self.assertTrue(self.foreground())

    def test_a_stopped_session_clears_the_mark(self):
        self.start()
        self.settle(self.foreground)
        meta = self.root / self.sid / "meta.json"
        m = json.loads(meta.read_text())
        m["stopped"] = True
        meta.write_text(json.dumps(m))
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(self.foreground())
        self.thread = None

    def test_an_error_ends_it_and_clears_the_mark(self):
        self.write(NEW, assistant("x"))
        self.age(NEW, 10)
        saved = B._split_assistant_text_events
        B._split_assistant_text_events = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        self.addCleanup(setattr, B, "_split_assistant_text_events", saved)
        self.start()
        self.settle(self.foreground, timeout=0.5)
        self.write(NEW, assistant("y"))
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())
        self.assertFalse(self.foreground())
        self.thread = None


class UnreadableLogTest(unittest.TestCase):
    """_note_transcript_read_failure: a root `claude`'s new log can start out
    unreadable to the backend until its ACL is fixed (aiza-unlockd regrant)."""

    def setUp(self):
        self.now = 1000.0
        self.regrants, self.said = [], []
        stubs = {"time": type("T", (), {"time": lambda _: self.now})(),
                 "_request_acl_regrant": lambda: self.regrants.append(self.now) or True,
                 "append_event": lambda sid, ev: self.said.append(ev["text"])}
        self.saved = {n: getattr(B, n) for n in stubs}
        for n, v in stubs.items():
            setattr(B, n, v)

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(B, n, v)

    def fail_for(self, location, seconds, step=1.0):
        state = (None, 0, False)
        end = self.now + seconds
        while self.now <= end:
            state = B._note_transcript_read_failure("s", location, *state)
            self.now += step
        return state

    def test_root_asks_on_a_schedule_then_says_so_once(self):
        self.fail_for("root", 400)
        self.assertEqual([t - 1000.0 for t in self.regrants], list(B.ACL_SELF_HEAL_SCHEDULE))
        self.assertEqual(len(self.said), 1)
        self.assertIn("会話ログを読み取れません", self.said[0])

    def test_a_short_stretch_asks_once_and_says_nothing(self):
        self.fail_for("root", 10)
        self.assertEqual(len(self.regrants), 1)
        self.assertEqual(self.said, [])

    def test_elsewhere_nothing_to_fix(self):
        self.fail_for("host", 400)
        self.assertEqual((self.regrants, self.said), ([], []))


if __name__ == "__main__":
    unittest.main()
