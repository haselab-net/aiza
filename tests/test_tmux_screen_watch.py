"""The chat of a pane without a conversation log of its own (a shell, an
attached tmux session) comes from its screen (_watch_tmux_session): a line
is settled into the chat once something is printed after it, the last line
is the live one, the screen panel gets every change, a backend restart does
not post the screen again, and the session ends with the pane (its exit
status, the last lines, the tmux session killed) or with the tmux session.

    python3 -m unittest discover -s tests -v

tmux is a stand-in pane whose lines and state the test sets; the watcher
runs in its own thread as in the backend, with a short poll and a clock
that can be moved ahead (its 5-second check, the 2-second wait for a dead
pane's status).
"""
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_shared_search import B


class Clock:
    def __init__(self):
        self.ahead = 0.0
        self.sleep = time.sleep

    def time(self):
        return time.time() + self.ahead


class Pane:
    """What `capture-pane ; display-message` says of the pane."""
    def __init__(self):
        self.lines, self.dead, self.status, self.height = [], False, "", 24
        self.alive = True        # the tmux session itself
        self.timeout = False
        self.frames = []         # screens to show one per capture, then the last stays

    def query(self, location, args, timeout=15):
        if self.timeout:
            self.timeout = False
            raise subprocess.TimeoutExpired(args, timeout)
        if self.frames:
            self.lines = self.frames.pop(0)
        state = f"{1 if self.dead else 0}|{self.status}|{self.height}|1|/work"
        return subprocess.CompletedProcess(args, 0, stdout="\n".join(self.lines) + "\n" + state + "\n", stderr="")


class ScreenWatchTest(unittest.TestCase):
    _n = 0

    def setUp(self):
        ScreenWatchTest._n += 1
        self.sid = f"dddd{ScreenWatchTest._n:08d}"
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "sessions"
        (self.root / self.sid).mkdir(parents=True)
        (self.root / self.sid / "events.jsonl").write_text("")
        self.clock, self.pane = Clock(), Pane()
        self.screens, self.tmux_calls, self.deleted = [], [], []
        stubs = {
            "session_roots": lambda: [self.root], "time": self.clock, "TMUX_POLL_INTERVAL": 0.02,
            "tmux_query": self.pane.query,
            "live_tmux_names": lambda location: [self.sid] if self.pane.alive else [],
            "tmux_exec": lambda location, args: self.tmux_calls.append(args),
            "_start_screen_pipe": lambda *a: False,          # no pipe: capture every poll
            "_screen_log_path": lambda *a: None,
            "push_ephemeral": lambda sid, ev: self.screens.append(ev["text"]),
            "delete_session": lambda sid: self.deleted.append(sid),
            "_latest_screen": {}, "_screen_backlog": {}, "_screen_waiting": {},
            "_claude_foreground": {}, "_codex_rollout_active": {},
        }
        self.saved = {n: getattr(B, n) for n in stubs}
        for n, v in stubs.items():
            setattr(B, n, v)
        self.thread = None

    def tearDown(self):
        if self.thread is not None:
            self.set_meta(stopped=True)
            self.clock.ahead += 10
            self.thread.join(3)
            self.assertFalse(self.thread.is_alive(), "the watcher did not stop with the session")
        for n, v in self.saved.items():
            setattr(B, n, v)
        self.tmp.cleanup()

    # -- helpers --
    def set_meta(self, **kw):
        p = self.root / self.sid / "meta.json"
        m = json.loads(p.read_text()) if p.exists() else {
            "id": self.sid, "label": "t", "preset": "shell", "tmux_name": self.sid, "tmux_location": "container",
            "cwd": "/work", "created_ts": time.time()}
        m.update(kw)
        p.write_text(json.dumps(m))

    def meta(self):
        return json.loads((self.root / self.sid / "meta.json").read_text())

    def chat(self, types=("agent_output", "live_tail", "session_ended")):
        out = []
        for raw in (self.root / self.sid / "events.jsonl").read_text().splitlines():
            ev = json.loads(raw)
            if ev["type"] in types:
                out.append((ev["type"], ev.get("text", ev.get("exit_status"))))
        return out

    def start(self, **meta):
        self.set_meta(**meta)
        self.thread = threading.Thread(target=B._watch_tmux_session, args=(self.sid,), daemon=True)
        self.thread.start()
        self.wait()

    def show(self, *lines):
        self.pane.lines = list(lines)
        self.wait()

    def wait(self, n=6):
        time.sleep(B.TMUX_POLL_INTERVAL * n)

    def ended(self, timeout=3):
        self.thread.join(timeout)
        self.assertFalse(self.thread.is_alive())
        self.thread = None

    # -- tests --
    def test_a_line_settles_once_something_follows_it(self):
        self.pane.lines = ["$ "]
        self.start()
        self.show("$ ls", "a.txt")
        self.show("$ ls", "a.txt", "b.txt")
        self.show("$ ls", "a.txt", "b.txt", "$ ")
        self.assertEqual([t for k, t in self.chat() if k == "agent_output"], ["$ ls", "a.txt", "b.txt"])
        self.assertEqual(self.chat()[-1], ("live_tail", "$"))         # (trailing blanks are dropped)
        self.assertEqual(self.screens[-1], "$ ls\na.txt\nb.txt\n$")   # the panel: the screen as it is

    def test_the_last_line_changing_in_place_stays_live(self):
        self.pane.lines = ["start", "50%"]
        self.start()
        self.show("start", "80%")
        self.show("start", "100%")
        self.assertEqual([t for k, t in self.chat() if k == "agent_output"], ["start"])   # "50%" followed it
        self.assertEqual([t for k, t in self.chat() if k == "live_tail"][-2:], ["80%", "100%"])

    def test_a_line_still_being_redrawn_is_not_settled_yet(self):
        # a progress line above new output keeps changing: settled as it ends, not as first seen
        self.pane.frames = [["get", "50%"], ["get", "60%", "log 1"], ["get", "100%", "log 1", "log 2"]]
        self.start()
        self.show("get", "100%", "log 1", "log 2", "$")
        out = "\n".join(t for k, t in self.chat() if k == "agent_output")
        self.assertNotIn("60%", out)
        self.assertEqual(out, "get\n100%\nlog 1\nlog 2")

    def test_a_restart_does_not_post_the_screen_again(self):
        self.pane.lines = ["old output", "more old", "$ "]
        self.start(created_ts=B._BACKEND_STARTED_TS - 60)   # the session was there before this backend
        self.show("old output", "more old", "$ echo hi", "hi", "$ ")
        self.assertEqual([t for k, t in self.chat() if k == "agent_output"], ["$ echo hi\nhi"])

    def test_a_cleared_screen_starts_over(self):
        self.pane.lines = ["a", "b", "c", "$ "]
        self.start()
        self.show("$ clear")
        self.show("$ clear", "x", "$ ")
        out = [t for k, t in self.chat() if k == "agent_output"]
        self.assertEqual(out[-1], "$ clear\nx")                      # from the cleared screen's top

    def test_lines_scrolled_off_are_kept_for_the_panel(self):
        self.pane.height = 3
        self.pane.lines = ["1", "2", "3"]
        self.start()
        self.show("2", "3", "4")
        self.show("3", "4", "5")
        self.assertEqual(B._screen_backlog[self.sid], ["1", "2"])

    def test_the_pane_ends_with_its_status(self):
        self.pane.lines = ["$ make", "building"]
        self.start()
        self.pane.lines = ["$ make", "building", "error: x", "", "Pane is dead (status 2, Tue Nov 25 10:00:00 2026)"]
        self.ended()
        # the lines not yet in the chat (the live one too), then the end
        self.assertEqual(self.chat()[-2:], [("agent_output", "building\nerror: x"), ("session_ended", 2)])
        m = self.meta()
        self.assertTrue(m["stopped"])
        self.assertFalse(m["alive"])
        self.assertIn(["kill-session", "-t", self.sid], self.tmux_calls)

    def test_an_attached_session_is_not_killed(self):
        self.pane.lines = ["x"]
        self.start(preset="attach")
        self.pane.lines = ["x", "Pane is dead (status 0)"]
        self.ended()
        self.assertEqual(self.tmux_calls, [])

    def test_a_dead_pane_without_a_status_line_waits_then_ends_with_0(self):
        self.pane.lines = ["bye"]
        self.start()
        self.pane.dead = True
        self.wait()
        self.assertTrue(self.thread.is_alive())                 # its status may still come
        self.clock.ahead += 3
        self.ended()
        self.assertEqual(self.chat()[-1], ("session_ended", 0))

    def test_a_dead_pane_reported_with_a_status(self):
        self.pane.lines = ["bye"]
        self.start()
        self.pane.dead, self.pane.status = True, "7"
        self.ended()
        self.assertEqual(self.chat()[-1], ("session_ended", 7))

    def test_a_finished_login_session_is_deleted(self):
        self.pane.lines = ["login"]
        self.start(preset="claude-login")
        self.pane.lines = ["login", "Pane is dead (status 0)"]
        self.ended()
        self.assertEqual(self.deleted, [self.sid])

    def test_the_tmux_session_gone_ends_it(self):
        self.pane.lines = ["x"]
        self.start()
        self.pane.alive = False
        self.clock.ahead += 6
        self.ended()
        self.assertEqual(self.chat()[-1], ("session_ended", None))
        self.assertTrue(self.meta()["stopped"])

    def test_a_claude_screen_is_not_turned_into_chat(self):
        # claude-tui's chat comes from its log (_tail_claude_transcript)
        self.pane.lines = ["╭───╮", "│ > │"]
        self.start(preset="claude-tui")
        self.show("● reply", "more", "╭───╮", "│ > │")
        self.assertEqual(self.chat(), [])
        self.assertEqual(self.screens[-1], "● reply\nmore\n╭───╮\n│ > │")

    def test_a_capture_that_times_out_is_skipped(self):
        self.pane.lines = ["a"]
        self.pane.timeout = True
        self.start()
        self.show("a", "b", "c")
        self.assertIn(("agent_output", "a\nb"), self.chat())

    def test_a_stopped_session_ends_the_watcher(self):
        self.pane.lines = ["a"]
        self.start()
        self.set_meta(stopped=True)
        self.clock.ahead += 6
        self.ended()
        self.assertNotIn("session_ended", [k for k, _ in self.chat()])


if __name__ == "__main__":
    unittest.main()
