"""The headless turn (_run_claude_headless_turn) for both its programs: the
public demo's "agent" (the deployment notes: docker/box/agent-turn.py, the Claude
Agent SDK in the box) and the "claude" preset (Claude Code's -p), through the
same `sandbox --stdin exec`, the prompt on stdin. Here a stand-in `sandbox` runs the
command as is, and a stand-in agent-turn.py prints what the real one would.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

FAKE_TURN = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
open(sys.argv[0] + ".seen", "w").write(json.dumps({"args": args, "prompt": prompt}))
mode = open(sys.argv[0] + ".mode").read().strip()
print(json.dumps({"type": "system", "subtype": "init", "session_id": "conv-1"}))
if mode == "ok":
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls", "description": "List files"}}]}}))
    print(json.dumps({"type": "result", "result": "できました", "session_id": "conv-1", "is_error": False,
                      "api_error_status": None, "total_cost_usd": 0.01}))
elif mode == "429":
    print(json.dumps({"type": "result", "result": "API Error: Request rejected (429)", "session_id": "conv-1",
                      "is_error": True, "api_error_status": 429, "total_cost_usd": 0}))
    print(json.dumps({"type": "error", "text": "ResultError: ..."}))
elif mode == "credit":
    print(json.dumps({"type": "result", "result": "API Error: 400 Your credit balance is too low", "session_id": "conv-1",
                      "is_error": True, "api_error_status": 400}))
'''

FAKE_SANDBOX = """#!/bin/sh
while [ $# -gt 0 ]; do case "$1" in --stdin|--claude|--fg) shift ;; *) break ;; esac; done
[ "$1" = exec ] && shift; [ "$1" = -- ] && shift
exec "$@"
"""


class AgentTurnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.sid = "aaaaaaaaaa0a"
        self.sdir = t / self.sid
        (self.sdir / "outbox").mkdir(parents=True)
        (self.sdir / "meta.json").write_text(json.dumps({"id": self.sid, "preset": "agent"}))
        (t / "bin").mkdir()
        (t / "bin" / "sandbox").write_text(FAKE_SANDBOX)
        self.turn = t / "agent-turn.py"
        self.turn.write_text(FAKE_TURN)
        for p in (t / "bin" / "sandbox", self.turn):
            p.chmod(0o755)
        self.stops = []
        self.saved = {k: getattr(B, k) for k in ("session_dir", "AGENT_TURN", "AGENT_PYTHON", "task_hook")}
        self.path = os.environ["PATH"]
        os.environ["PATH"] = f"{t / 'bin'}:{self.path}"
        B.session_dir = lambda sid, *a, **kw: t / sid
        B.AGENT_TURN = str(self.turn)
        B.AGENT_PYTHON = "python3"
        B.task_hook = lambda sid, ev: self.stops.append(ev.get("last_assistant_message"))
        B._next_seq.pop(self.sid, None)

    def tearDown(self):
        os.environ["PATH"] = self.path
        for k, v in self.saved.items():
            setattr(B, k, v)
        B._next_seq.pop(self.sid, None)
        self.tmp.cleanup()

    def run_turn(self, mode, text="こんにちは"):
        Path(str(self.turn) + ".mode").write_text(mode)
        B._run_claude_headless_turn(self.sid, text)
        ev = [json.loads(l) for l in (self.sdir / "events.jsonl").read_text().splitlines()]
        return [(e["type"], e.get("text")) for e in ev]

    def test_a_turn_shows_its_tools_and_its_reply_and_keeps_the_conversation(self):
        self.assertEqual(self.run_turn("ok"), [("tool", "Bash: List files"), ("agent_output", "できました")])
        seen = json.loads(Path(str(self.turn) + ".seen").read_text())
        self.assertEqual(seen["prompt"], "こんにちは")              # on stdin, not the command line
        self.assertEqual(B.load_meta(self.sid)["claude_session_id"], "conv-1")
        self.assertEqual(self.stops, ["できました"])
        self.run_turn("ok", "次")
        seen = json.loads(Path(str(self.turn) + ".seen").read_text())
        self.assertEqual(seen["args"][-2:], ["--resume", "conv-1"])
        self.assertFalse((self.sdir / "claude.pid").exists())

    def test_the_relays_refusals_are_said_in_words(self):
        self.assertEqual(self.run_turn("429")[-1][0], "system")
        said = self.run_turn("429")[-1][1]
        self.assertIn("上限", said)
        self.assertIn("Request rejected (429)", said)        # what the API said, too
        self.assertIn("無料枠", self.run_turn("credit")[-1][1])
        self.assertEqual(self.stops, [])

    def test_the_claude_preset_goes_the_same_way(self):
        # The same _run_claude_headless_turn, only the program differs
        # (_headless_program): Claude Code's own -p, the prompt on stdin.
        claude = Path(os.environ["PATH"].split(":")[0]) / "claude"
        claude.write_text(FAKE_TURN)
        claude.chmod(0o755)
        Path(str(claude) + ".mode").write_text("ok")
        (self.sdir / "meta.json").write_text(json.dumps({"id": self.sid, "preset": "claude", "claude_session_id": "c0"}))
        B._run_claude_headless_turn(self.sid, "いつもの版から")
        seen = json.loads(Path(str(claude) + ".seen").read_text())
        self.assertEqual(seen["prompt"], "いつもの版から")
        self.assertNotIn("いつもの版から", " ".join(seen["args"]))
        self.assertEqual(seen["args"][:2], ["--dangerously-skip-permissions", "-p"])
        self.assertEqual(seen["args"][-2:], ["--resume", "c0"])
        ev = [json.loads(l) for l in (self.sdir / "events.jsonl").read_text().splitlines()]
        self.assertEqual([(e["type"], e.get("text")) for e in ev], [("tool", "Bash: List files"), ("agent_output", "できました")])
        self.assertEqual(B.load_meta(self.sid)["claude_session_id"], "conv-1")

    def test_a_turn_with_no_result_says_so(self):
        kind, text = self.run_turn("nothing")[-1]
        self.assertEqual(kind, "system")
        self.assertIn("答えずに終わりました", text)


if __name__ == "__main__":
    unittest.main()
