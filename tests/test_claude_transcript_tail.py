"""The chat of a "claude-tui" session comes from Claude Code's own
conversation log (_tail_claude_transcript): which file (a pre-assigned id,
a resumed one, or the new one that appears), what is taken from it (only
Claude's text and thinking, whole lines), a 続きから's history copied once,
the move to another conversation (the deployment notes), and that it stops with
the session.

    python3 -m unittest discover -s tests -v

$HOME is a temporary directory; the watcher runs in its own thread as in
the backend, with a short poll and a clock that can be moved ahead (its
5-second check for a stopped session).
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_shared_search import B

CWD = "/work"
ID = "0a000000-0000-4000-8000-000000000001"
OTHER = "0b000000-0000-4000-8000-000000000002"


def user(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n"


def said(*blocks):
    return json.dumps({"type": "assistant", "message": {"content": list(blocks)}}) + "\n"


TEXT = lambda t: {"type": "text", "text": t}
THINK = lambda t: {"type": "thinking", "thinking": t, "signature": "s"}
TOOL = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}


class Clock:
    """time as the backend sees it: real, plus what a test moves it ahead."""
    def __init__(self):
        self.ahead = 0.0
        self.sleep = time.sleep

    def time(self):
        return time.time() + self.ahead


class TranscriptTailTest(unittest.TestCase):
    _n = 0

    def setUp(self):
        TranscriptTailTest._n += 1
        self.sid = f"cccc{TranscriptTailTest._n:08d}"
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "sessions"
        self.home = base / "home"
        (self.root / self.sid).mkdir(parents=True)
        self.clock = Clock()
        stubs = {"session_roots": lambda: [self.root], "SANDHOME": self.home, "time": self.clock,
                 "CLAUDE_TRANSCRIPT_POLL_INTERVAL": 0.02, "_claimed_transcripts": {},
                 "usage_backfill": lambda sid, path: None,
                 "_conv_hooked": set(), "_conv_pending": {}}
        self.saved = {n: getattr(B, n) for n in stubs}
        for n, v in stubs.items():
            setattr(B, n, v)
        self.proj = B.claude_project_dir(CWD)
        self.proj.mkdir(parents=True)
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
            "id": self.sid, "label": "t", "preset": "claude-tui", "tmux_location": "container", "cwd": CWD,
            "created_ts": time.time()}
        m.update(kw)
        p.write_text(json.dumps(m))

    def meta(self):
        return json.loads((self.root / self.sid / "meta.json").read_text())

    def events(self, text=""):
        p = self.root / self.sid / "events.jsonl"
        if not p.exists():
            p.write_text(text)

    def write(self, conv, text):
        with (self.proj / f"{conv}.jsonl").open("a") as f:
            f.write(text)

    def start(self):
        self.thread = threading.Thread(target=B._tail_claude_transcript, args=(self.sid,), daemon=True)
        self.thread.start()
        time.sleep(0.1)

    def shown(self, types=("agent_output", "agent_thinking", "user_message")):
        out = []
        for raw in (self.root / self.sid / "events.jsonl").read_text().splitlines():
            ev = json.loads(raw)
            if ev["type"] in types:
                out.append((ev["type"], ev.get("text")))
        return out

    def settle(self, until, timeout=3.0):
        end = time.time() + timeout
        while time.time() < end and not until():
            time.sleep(0.03)
        time.sleep(0.15)   # anything wrongly extra arrives too

    # -- tests --
    def test_a_new_session_waits_for_its_log_then_shows_claudes_part(self):
        self.set_meta(claude_session_id=ID)
        self.events()
        self.start()                                       # the log is not there yet
        self.assertTrue(self.thread.is_alive())
        self.write(ID, user("こんにちは"))                  # Claude Code makes it with the user's line
        time.sleep(0.2)
        self.write(ID, said(THINK("考え中"), TEXT("はい")) + said(TOOL))
        self.settle(lambda: len(self.shown()) >= 2)
        self.assertEqual(self.shown(), [("agent_thinking", "考え中"), ("agent_output", "はい")])

    def test_a_line_is_shown_only_once_it_is_whole(self):
        self.set_meta(claude_session_id=ID)
        self.events()
        self.write(ID, "")
        self.start()
        line = said(TEXT("一行"))
        self.write(ID, line[:20])
        time.sleep(0.2)
        self.assertEqual(self.shown(), [])
        self.write(ID, line[20:])
        self.settle(lambda: self.shown())
        self.assertEqual(self.shown(), [("agent_output", "一行")])

    def test_a_restart_does_not_replay_what_the_log_already_had(self):
        self.set_meta(claude_session_id=ID)
        self.events(json.dumps({"seq": 1, "type": "agent_output", "text": "前"}) + "\n")
        self.write(ID, said(TEXT("前")))
        self.start()
        self.write(ID, said(TEXT("後")))
        self.settle(lambda: len(self.shown()) >= 2)
        self.assertEqual(self.shown(), [("agent_output", "前"), ("agent_output", "後")])

    def test_resumed_copies_the_history_once(self):
        self.write(ID, user("前の質問") + said(TEXT("前の答え")))
        self.set_meta(claude_session_id=ID, resumed_from=ID)
        self.events()                                      # a new aiza session: its chat empty
        self.start()
        self.write(ID, said(TEXT("続き")))
        self.settle(lambda: ("agent_output", "続き") in self.shown())
        self.assertEqual(self.shown(), [("user_message", "前の質問"), ("agent_output", "前の答え"),
                                        ("agent_output", "続き")])

    def test_resumed_after_a_restart_copies_nothing(self):
        self.write(ID, user("前の質問") + said(TEXT("前の答え")))
        self.set_meta(claude_session_id=ID, resumed_from=ID)
        self.events(json.dumps({"seq": 1, "type": "agent_output", "text": "前の答え"}) + "\n")
        self.start()
        self.write(ID, said(TEXT("続き")))
        self.settle(lambda: len(self.shown()) >= 2)
        self.assertEqual(self.shown(), [("agent_output", "前の答え"), ("agent_output", "続き")])

    def test_resumed_without_its_log_gives_up(self):
        self.set_meta(claude_session_id=ID, resumed_from=ID)
        self.events()
        t = threading.Thread(target=B._tail_claude_transcript, args=(self.sid,), daemon=True)
        t.start()
        t.join(2)
        self.assertFalse(t.is_alive())

    def test_without_an_id_the_new_log_is_found_and_kept(self):
        self.write(OTHER, said(TEXT("別の会話")))          # there before: not this session's
        self.set_meta()
        self.events()
        self.start()
        self.write(ID, said(TEXT("新しい")))
        self.settle(lambda: self.meta().get("claude_session_id"))
        self.assertEqual(self.meta()["claude_session_id"], ID)
        self.write(ID, said(TEXT("次")))
        self.write(OTHER, said(TEXT("別の会話の続き")))
        self.settle(lambda: self.shown())
        self.assertEqual(self.shown(), [("agent_output", "次")])

    def test_a_log_another_session_holds_is_not_taken(self):
        self.set_meta()
        self.events()
        self.start()
        B._claimed_transcripts[(str(self.proj), f"{OTHER}.jsonl")] = "someone-else"
        self.write(OTHER, said(TEXT("あちら")))
        time.sleep(0.2)
        self.write(ID, said(TEXT("こちら")))
        self.settle(lambda: self.meta().get("claude_session_id"))
        self.assertEqual(self.meta()["claude_session_id"], ID)

    def test_a_stopped_session_stops_waiting(self):
        self.set_meta(claude_session_id=ID)
        self.events()
        self.start()
        self.set_meta(stopped=True)
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())

    def test_moves_to_another_conversation(self):
        # the deployment notes: /clear in Claude Code starts a new log
        self.set_meta(claude_session_id=ID)
        self.events()
        self.write(ID, "")
        self.start()
        self.write(ID, said(TEXT("一つ目")))
        self.settle(lambda: self.shown())
        self.write(OTHER, said(TEXT("新しい会話")))
        B.conv_report(self.sid, {"session_id": OTHER, "transcript_path": str(self.proj / f"{OTHER}.jsonl"),
                                 "source": "clear", "pane": True})
        self.settle(lambda: len(self.shown()) >= 2)
        self.write(ID, said(TEXT("古い方には戻らない")))
        self.write(OTHER, said(TEXT("続き")))
        self.settle(lambda: len(self.shown()) >= 3)
        self.assertEqual(self.shown(), [("agent_output", "一つ目"), ("agent_output", "新しい会話"),
                                        ("agent_output", "続き")])
        self.assertEqual(self.meta()["claude_session_id"], OTHER)

    def test_an_error_ends_it_quietly(self):
        self.set_meta(claude_session_id=ID)
        self.events()
        self.write(ID, "")
        boom = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        saved = B._split_assistant_text_events
        B._split_assistant_text_events = boom
        try:
            self.start()
            self.write(ID, said(TEXT("x")))
            self.thread.join(2)
            self.assertFalse(self.thread.is_alive())
        finally:
            B._split_assistant_text_events = saved


if __name__ == "__main__":
    unittest.main()
