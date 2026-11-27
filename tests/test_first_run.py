"""A new account's first Claude Code / Codex start (2026-11-19, user:
初めて Claude を開くと YES/NO の選択がたくさん出る): the bypass warning is
turned off, Codex's folder trust is answered, and no login means the login
opens first."""
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

CODEX_SCREEN = """> You are in /home/u/w
  Do you trust the contents of this directory? Working with untrusted contents comes with higher risk of prompt
› 1. Yes, continue
  2. No, quit
  Press enter to continue"""


class FirstRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_skip_prompt_is_added_once_and_keeps_the_rest(self):
        (self.home / ".claude").mkdir()
        cfg = self.home / ".claude" / "settings.json"
        cfg.write_text(json.dumps({"model": "x"}))
        B.allow_claude_skip_prompt(self.home)
        self.assertEqual(json.loads(cfg.read_text()), {"model": "x", "skipDangerousModePermissionPrompt": True})
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)

    def test_skip_prompt_on_a_new_home_and_not_on_a_broken_file(self):
        B.allow_claude_skip_prompt(self.home)
        self.assertTrue(json.loads((self.home / ".claude" / "settings.json").read_text())["skipDangerousModePermissionPrompt"])
        (self.home / ".claude" / "settings.json").write_text("{broken")
        B.allow_claude_skip_prompt(self.home)
        self.assertEqual((self.home / ".claude" / "settings.json").read_text(), "{broken")

    def test_codex_trust_yes_is_highlighted(self):
        self.assertIsNone(B._trust_dialog_cursor_move(CODEX_SCREEN, B.CODEX_TRUST[1]))
        moved = CODEX_SCREEN.replace("› 1.", "  1.").replace("  2. No", "› 2. No")
        self.assertEqual(B._trust_dialog_cursor_move(moved, B.CODEX_TRUST[1]), "Up")

    def test_codex_question_after_its_box_is_still_answered(self):
        box = "\u256d\u2500\n\u2502 >_ OpenAI Codex (v0.155.0) \u2502\n\u203a Ask Codex to do anything"
        screens = iter([box, box, box + "\n" + CODEX_SCREEN])
        sent = []
        saved = B.tmux_query, B.tmux_exec, B.TRUST_DIALOG_POLL_INTERVAL
        try:
            B.tmux_query = lambda loc, args: B.subprocess.CompletedProcess(args, 0, next(screens, box), "")
            B.tmux_exec = lambda loc, args, **kw: sent.append(args[-1])
            B.TRUST_DIALOG_POLL_INTERVAL = 0.01
            B._accept_workspace_trust_if_shown("container", "s", tool="codex", timeout=2)
        finally:
            B.tmux_query, B.tmux_exec, B.TRUST_DIALOG_POLL_INTERVAL = saved
        self.assertEqual(sent, ["Enter"])

    def test_claude_trust_unchanged(self):
        screen = " ❯ No, exit\n   Yes, I trust this folder"
        self.assertEqual(B._trust_dialog_cursor_move(screen), "Down")

    def test_logged_in_is_read_from_the_credential_files(self):
        saved = B.SANDHOME, B.HOME
        try:
            B.SANDHOME = self.home / "sand"
            B.HOME = self.home
            self.assertFalse(B.agent_logged_in("claude", "container"))
            (B.SANDHOME / ".claude").mkdir(parents=True)
            (B.SANDHOME / ".claude" / ".credentials.json").write_text("{}")
            self.assertTrue(B.agent_logged_in("claude", "container"))
            self.assertFalse(B.agent_logged_in("claude", "host"))
            (self.home / ".codex").mkdir()
            (self.home / ".codex" / "auth.json").write_text("{}")
            self.assertTrue(B.agent_logged_in("codex", "host"))
            self.assertFalse(B.agent_logged_in("codex", "container"))
        finally:
            B.SANDHOME, B.HOME = saved

    def test_login_first_presets(self):
        self.assertEqual(set(B.LOGIN_FIRST), {"claude-tui", "claude-host", "codex-tui", "codex-host"})
        for p in B.LOGIN_FIRST:
            self.assertTrue(p in B.PRESETS or p in B.LAUNCH_PRESETS, p)


if __name__ == "__main__":
    unittest.main()
