"""How send_message types a message into a pane: Codex gets a bracketed
paste (its composer swallowed the Enter after long typed input, 2026-10-12),
everything else the literal keys it always got."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


class SendMessageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = []
        self.checks = []
        stubs = {
            "session_roots": lambda: [self.root],
            "tmux_exec": self.fake_tmux,
            # text goes on stdin (the deployment notes); recorded as the argv it replaces
            "tmux_exec_text": lambda loc, args, text, **kw: self.fake_tmux(loc, [*args, text]),
            "require_unlock_if_outside_sandbox": lambda location: None,
            "_start_stuck_input_check": lambda *a: self.checks.append(a),
        }
        self.saved = {name: getattr(B, name) for name in stubs}
        for name, value in stubs.items():
            setattr(B, name, value)

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(B, name, value)
        self.tmp.cleanup()

    def fake_tmux(self, location, args, *a, **kw):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    def session(self, sid, preset):
        d = self.root / sid
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": sid, "preset": preset, "tmux_name": sid,
                                                  "tmux_location": "container"}))
        (d / "events.jsonl").write_text("")

    def test_codex_gets_a_bracketed_paste_then_enter(self):
        self.session("cccc00000001", "codex-tui")
        text = "1行目\n" + "長い行。" * 400
        B.send_message("cccc00000001", text)
        self.assertEqual(self.calls, [
            ["set-buffer", "-b", "aiza-send-cccc00000001", "--", text],
            ["paste-buffer", "-p", "-d", "-b", "aiza-send-cccc00000001", "-t", "cccc00000001"],
            ["send-keys", "-t", "cccc00000001", "Enter"],
        ])

    def test_codex_without_submit_pastes_only(self):
        self.session("cccc00000002", "codex-tui")
        B.send_message("cccc00000002", "abc", submit=False)
        self.assertEqual([c[0] for c in self.calls], ["set-buffer", "paste-buffer"])

    def test_others_still_type_literally(self):
        for sid, preset in (("cccc00000003", "shell"), ("cccc00000004", "claude-tui")):
            self.calls = []
            self.session(sid, preset)
            B.send_message(sid, "-starts with a dash")
            self.assertEqual(self.calls, [
                ["send-keys", "-t", sid, "-l", "--", "-starts with a dash"],
                ["send-keys", "-t", sid, "Enter"],
            ])

    def test_hand_started_codex_gets_the_paste(self):
        # The Email box's shell (its Codex is started there by hand, and the
        # pane only shows the box's entry) and a shell whose relay says Codex.
        meta = {"id": "cccc00000006", "preset": "mail-shell", "tmux_name": "cccc00000006", "tmux_location": "host"}
        saved = (B.load_meta, B.session_dir)
        B.load_meta = lambda sid: dict(meta)            # a box session's own folder is in the box
        B.session_dir = lambda sid: self.root / sid
        (self.root / "cccc00000006").mkdir()
        try:
            B.send_message("cccc00000006", "1行目\n2行目")
        finally:
            B.load_meta, B.session_dir = saved
        self.assertEqual([c[0] for c in self.calls], ["set-buffer", "paste-buffer", "send-keys"])
        self.calls = []
        self.session("cccc00000007", "shell")
        saved = B._codex_relay_active
        B._codex_relay_active = lambda sid, meta, sdir: sid == "cccc00000007"
        try:
            B.send_message("cccc00000007", "abc")
        finally:
            B._codex_relay_active = saved
        self.assertEqual([c[0] for c in self.calls], ["set-buffer", "paste-buffer", "send-keys"])

    def test_run_with_text_starts_the_stuck_input_check(self):
        self.session("cccc00000005", "claude-tui")
        B.send_message("cccc00000005", "abc")
        B.send_message("cccc00000005", "", submit=True)
        B.send_message("cccc00000005", "def", submit=False)
        self.assertEqual(self.checks, [("cccc00000005", "container", "cccc00000005", "abc")])


class BoxPidTest(unittest.TestCase):
    """The Email box's Codex is found on the host by its box pid and its
    session (the box has its own pid numbers)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def p(self, pid, ppid, nspid, env=""):
        d = self.proc / str(pid)
        d.mkdir()
        (d / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\nNSpid:\t{nspid}\n")
        (d / "environ").write_text(env.replace(" ", "\0"))

    def test_found_only_for_its_own_session(self):
        self.p(500, 2, "500")
        self.p(600, 500, "600\t40", "HOME=/x AIZA_TALKTO=/m/.aiza/aaaaaaaaaa01/talkto_out.jsonl")
        self.p(700, 600, "700\t41")
        self.p(800, 2, "800\t41", "AIZA_TALKTO=/m/.aiza/bbbbbbbbbb01/talkto_out.jsonl")
        self.assertEqual(B._box_host_pid(41, "aaaaaaaaaa01", proc=str(self.proc)), 700)
        self.assertEqual(B._box_host_pid(41, "bbbbbbbbbb01", proc=str(self.proc)), 800)
        self.assertIsNone(B._box_host_pid(41, "cccccccccc01", proc=str(self.proc)))
        self.assertIsNone(B._box_host_pid(500, "aaaaaaaaaa01", proc=str(self.proc)))   # host-only pid


RULE = "─" * 80
SENT = "https://example.org/mail/ の既決がなくなっています。全部未読になってしまった？　状況確認をお願いします。"
# The Email session's screen on 2026-10-14, stuck with the text in its box
# (the diff panel on the right, trimmed).
STUCK_SCREEN = "\n".join([
    "  コミットはまだしていません。                    │" + "─" * 30,
    "✻ Sautéed for 3m 6s · done 11:30 AM               │.gitignore    [ ask ]",
    "                     ✔ Update installed · Restart to update  │",
    RULE,
    "❯ https://example.org/mail/ の既決がなくなっています。全部未読になってしまった？　状況確認をお願い",
    "  します。",
    "",
    RULE,
    "  ⏵⏵ bypass permissions on (shift+tab to cycle)",
])
TAKEN_SCREEN = "\n".join([
    "❯ " + SENT, "", "* Boondoggling… (20s · ↓ 1.4k tokens)", RULE, "❯ ", RULE,
    "  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt",
])
QUEUED_SCREEN = "\n".join([
    "  ctrl+x ctrl+s to send now", "* Jitterbugging… (7s)", RULE,
    "❯ Press up to edit queued messages", RULE, "  ⏵⏵ auto mode on",
])


class ComposerTest(unittest.TestCase):
    def test_stuck_text_is_seen_in_the_box(self):
        self.assertTrue(B._text_still_in_composer(STUCK_SCREEN, SENT))

    def test_taken_or_queued_is_not_stuck(self):
        self.assertFalse(B._text_still_in_composer(TAKEN_SCREEN, SENT))
        self.assertFalse(B._text_still_in_composer(QUEUED_SCREEN, SENT))

    def test_not_claude_prompt(self):
        self.assertIsNone(B._claude_composer_text("user@box:~$ ls\nfoo\nuser@box:~$ "))


class StuckInputCheckTest(unittest.TestCase):
    def setUp(self):
        self.screens = []
        self.keys = []
        self.events = []
        stubs = {
            "tmux_query": lambda loc, args, *a, **kw: subprocess.CompletedProcess(args, 0, self.screens.pop(0), ""),
            "tmux_exec": lambda loc, args, *a, **kw: self.keys.append(args),
            "append_event": lambda sid, ev: self.events.append(ev["text"]),
            "STUCK_INPUT_CHECK_DELAY": 0,
            "STUCK_INPUT_RETRY": 0,
        }
        self.saved = {name: getattr(B, name) for name in stubs}
        for name, value in stubs.items():
            setattr(B, name, value)
        self.sleep = B.time.sleep
        B.time.sleep = lambda s: None

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(B, name, value)
        B.time.sleep = self.sleep

    def test_taken_at_once_says_nothing(self):
        self.screens = [TAKEN_SCREEN]
        B._stuck_input_check("s1", "host", "s1", SENT)
        self.assertEqual((self.events, self.keys), ([], []))

    def test_stuck_warns_retries_enter_and_reports_when_taken(self):
        # first check, retry 1 (before/after Enter), retry 2 (before/after Enter)
        self.screens = [STUCK_SCREEN, STUCK_SCREEN, STUCK_SCREEN, STUCK_SCREEN, TAKEN_SCREEN]
        B._stuck_input_check("s2", "host", "s2", SENT)
        self.assertEqual(self.keys, [["send-keys", "-t", "s2", "Enter"]] * 2)
        self.assertEqual(len(self.events), 2)
        self.assertIn("受け付けていません", self.events[0])
        self.assertIn("受け付けました", self.events[1])
        self.assertNotIn("s2", B._stuck_input_checks)

    def test_stops_when_the_prompt_is_gone(self):
        self.screens = [STUCK_SCREEN, "$ "]
        B._stuck_input_check("s3", "host", "s3", SENT)
        self.assertEqual(self.keys, [])
        self.assertEqual(len(self.events), 1)


if __name__ == "__main__":
    unittest.main()
