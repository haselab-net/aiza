"""What to run x where (2026-11-14): Claude/Codex/Shell in each of Dev,
Email, the host and root. The combinations with no preset of their own are
that place's shell with the program typed in (LAUNCH_PRESETS, meta.launch);
the Email shell is the Email box with no claude (mail-shell). The page's
KIND_PLACE table may only name presets the backend takes.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

ROOT = Path(__file__).resolve().parent.parent


class KindPlaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "sessions").mkdir()
        self.mail = self.root / "mailbox"
        (self.mail / ".aiza").mkdir(parents=True)
        self.calls = []
        mailbox = {"dir": self.mail, "container_name": "mail", "label": "Email"}
        mail_shell = {"command": ["sandbox", "box", "mail", str(self.mail)], "location": "host", "width": 100}
        stubs = {
            "SESSIONS_DIR": self.root / "sessions",
            "HOST_SESSIONS_DIR": self.root / "sessions",
            "MAIL_SESSIONS_DIR": self.mail / ".aiza",
            "session_roots": lambda: [self.root / "sessions", self.mail / ".aiza"],
            "MAILBOX": mailbox,
            "TMUX_PRESETS": {**B.TMUX_PRESETS, "mail-shell": mail_shell},
            "PRESETS": {**B.PRESETS, "mail-shell": mail_shell},
            "MAIL_TREE_PRESETS": {"mail-tui", "mail-shell"},
            "LAUNCH_PRESETS": dict(B.LAUNCH_PRESETS),
            "resolve_host_workdir": lambda cwd: None,
            "resolve_root_workdir": lambda cwd: None,
            "resolve_mail_workdir": lambda cwd: None,
            "root_shell_allowed": lambda: True,
            "tmux_exec": lambda loc, args, **kw: self.calls.append((loc, args)) or subprocess.CompletedProcess(args, 0, "", ""),
            "tag_tmux_owner": lambda loc, sid: None,
            "ensure_watcher": lambda sid: None,
            "_accept_workspace_trust_if_shown": lambda loc, sid, **kw: None,
            "mark_claude_onboarded": lambda home: None,
            "allow_claude_skip_prompt": lambda home: None,
            "_unlockd_call": lambda verb, **f: {"ok": True, "unlocked": True, "tier": "root"},
        }
        self.saved = {k: getattr(B, k) for k in stubs}
        for k, v in stubs.items():
            setattr(B, k, v)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def typed(self):
        return [a[a.index("-t") + 2] for _, a in self.calls if a[0] == "send-keys" and "Enter" in a]

    def respawned(self):
        loc, a = next((loc, a) for loc, a in self.calls if a[0] == "respawn-pane")
        return loc, a[a.index("--") + 1:]

    def test_claude_on_the_host_is_the_host_shell_with_claude_typed_in(self):
        meta = B.create_session("claude-host", "x")
        self.assertEqual((meta["preset"], meta["tmux_location"], meta["launch"]), ("host-shell", "host", "claude"))
        self.assertTrue(meta["claude_session_id"])           # pre-assigned, picked up by the wrapper
        typed = self.typed()
        self.assertTrue(typed[0].startswith("claude() {"))   # the wrapper first
        self.assertEqual(typed[-1], "claude --dangerously-skip-permissions")

    def test_permission_checkbox_off(self):
        B.create_session("claude-host", "x", skip_permissions=False)
        self.assertEqual(self.typed()[-1], "claude")
        self.calls.clear()
        B.create_session("codex-host", "x", skip_permissions=False)
        self.assertEqual(self.typed()[-1], "codex --no-daemon")

    def test_claude_as_root_never_skips_permissions(self):
        # Claude refuses the flag as root: asked for or not, it is not typed.
        # It runs in Auto mode (2026-11-24, the user), what it asks as a card.
        meta = B.create_session("claude-root", "x", skip_permissions=True)
        self.assertEqual(self.typed()[-1], "claude --permission-mode auto")
        self.assertFalse(meta["skip_permissions"])
        # Resumed (the page asks with the old value or the default): still not.
        conv = meta["claude_session_id"]
        meta["stopped"] = True
        B.save_meta(meta["id"], meta)
        self.calls.clear()
        saved = (B.find_transcript_cwd, B.list_sessions)
        B.find_transcript_cwd = lambda loc, cid: str(self.root)
        B.list_sessions = lambda on_behalf_of=None: []
        try:
            B.create_session("root-shell", None, resume=conv, replace_session=meta["id"], skip_permissions=True)
        finally:
            B.find_transcript_cwd, B.list_sessions = saved
        self.assertEqual(self.typed()[-1], f"claude --resume '{conv}' --permission-mode auto")

    def test_codex_as_root_never_skips_approvals(self):
        # 2026-11-24, the user: root's Codex is not to skip; asked for or not.
        meta = B.create_session("codex-root", "x", skip_permissions=True)
        self.assertEqual((meta["preset"], meta["tmux_location"], meta["launch"]), ("root-shell", "root", "codex"))
        self.assertEqual(self.typed()[-1], "codex --no-daemon")
        self.assertFalse(meta["skip_permissions"])

    # Codex 0.171.0's TUI runs the conversation in a shared per-user
    # background server unless told otherwise. That server is started by the
    # first TUI and keeps *its* environment, so a second session's rollout
    # (and its hooks) carry the first session's AIZA_TALKTO, and the rollout
    # says source "vscode", which the relay hook refuses: the second
    # session's chat stayed empty. Every Codex aiza starts runs its own.
    def test_codex_tui_runs_without_the_shared_daemon(self):
        meta = B.create_session("codex-tui", "x")
        _, cmd = self.respawned()
        at = cmd.index("codex")
        self.assertIn("--no-daemon", cmd[at:])
        self.assertTrue(meta["id"])

    def test_codex_resume_runs_without_the_shared_daemon(self):
        old = B.create_session("codex-host", "x")
        conv = "019a0000-0000-7000-8000-000000000000"
        (B.session_dir(old["id"]) / "codex-active.json").write_text(json.dumps({"session_id": conv}))
        old["stopped"] = True
        B.save_meta(old["id"], old)
        self.calls.clear()
        saved = B.list_sessions
        B.list_sessions = lambda on_behalf_of=None: []
        try:
            meta = B.create_session("host-shell", None, resume=conv, replace_session=old["id"])
        finally:
            B.list_sessions = saved
        self.assertEqual(meta["launch"], "codex")
        self.assertEqual(self.typed()[-1],
                         f"codex resume '{conv}' --no-daemon --dangerously-bypass-approvals-and-sandbox")

    def test_email_shell_is_the_box_without_claude_in_the_email_tree(self):
        meta = B.create_session("mail-shell", "x")
        self.assertEqual((meta["preset"], meta["tmux_location"], meta["launch"]), ("mail-shell", "host", None))
        self.assertTrue((self.mail / ".aiza" / meta["id"] / "meta.json").is_file())
        loc, cmd = self.respawned()
        at = cmd.index("sandbox")
        self.assertEqual(cmd[at:], ["sandbox", "--aiza-session", meta["id"], "box", "mail", str(self.mail)])
        self.assertNotIn("--claude", cmd)
        # The Email box's shell: never co-working (it holds the mail
        # credentials; only the box's Claude may be co-worked), never everyone.
        self.assertNotEqual(B.share_mode({**meta, "shared_with": ["bob"]}, "bob"), "write")
        with self.assertRaises(ValueError):
            B.share_session(meta["id"], "bob", "write")

    def test_no_codex_in_the_email_box_until_ready(self):
        # Not ready (no codex-mail): refused, also by hand.
        with self.assertRaises(ValueError):
            B.create_session("codex-mail", "x")

    def test_codex_in_the_email_box_when_ready_goes_through_its_launcher(self):
        B.LAUNCH_PRESETS["codex-mail"] = ("mail-shell", "codex")
        try:
            meta = B.create_session("codex-mail", "x", skip_permissions=True)
        finally:
            del B.LAUNCH_PRESETS["codex-mail"]
        self.assertEqual((meta["preset"], meta["launch"]), ("mail-shell", "codex"))
        line = self.typed()[-1]
        self.assertTrue(line.startswith(B.CODEX_MAILBOX_LAUNCHER + " --cd "), line)
        self.assertNotIn("dangerously", line)

    def test_box_resume_cannot_carry_codex(self):
        # A stopped box shell whose meta says it ran Codex (an old codex-mail,
        # or written from inside the box): resuming it is refused.
        old = B.create_session("mail-shell", "x")
        old.update(stopped=True, launch="codex", codex_resume_id="019a0000-0000-7000-8000-000000000000")
        B.save_meta(old["id"], old)
        with self.assertRaises(ValueError):
            B.create_session("mail-shell", None, resume=old["codex_resume_id"], replace_session=old["id"])

    def test_resume_of_an_ended_claude_on_the_host_types_resume_and_stays_claude(self):
        old = B.create_session("claude-host", "x")
        conv = old["claude_session_id"]
        old["stopped"] = True
        B.save_meta(old["id"], old)
        self.calls.clear()
        saved = (B.find_transcript_cwd, B.list_sessions)
        B.find_transcript_cwd = lambda loc, cid: str(self.root)
        B.list_sessions = lambda on_behalf_of=None: []
        try:
            meta = B.create_session("host-shell", None, resume=conv, replace_session=old["id"])
        finally:
            B.find_transcript_cwd, B.list_sessions = saved
        self.assertEqual(meta["launch"], "claude")
        # Started without permission prompts (the default): resumed the same way.
        self.assertEqual(self.typed()[-1], f"claude --resume '{conv}' --dangerously-skip-permissions")

    def test_resume_keeps_permission_prompts_when_it_started_with_them(self):
        old = B.create_session("claude-host", "x", skip_permissions=False)
        conv = old["claude_session_id"]
        old["stopped"] = True
        B.save_meta(old["id"], old)
        self.calls.clear()
        saved = (B.find_transcript_cwd, B.list_sessions)
        B.find_transcript_cwd = lambda loc, cid: str(self.root)
        B.list_sessions = lambda on_behalf_of=None: []
        try:
            B.create_session("host-shell", None, resume=conv, replace_session=old["id"], skip_permissions=False)
        finally:
            B.find_transcript_cwd, B.list_sessions = saved
        self.assertEqual(self.typed()[-1], f"claude --resume '{conv}'")


class PageTableTest(unittest.TestCase):
    def test_every_combination_is_a_preset_the_backend_takes(self):
        from page_sources import sources
        js = "\n".join(sources().values())   # the page's scripts (KIND_PLACE is in form.js)
        table = re.search(r"const KIND_PLACE = \{(.*?)\n  \};", js, re.S).group(1)
        values = re.findall(r'(?:dev|mail|host|root): "([a-z-]+)"', table)
        self.assertEqual(len(values), 12)          # mailbox Codex is capability-gated
        known = set(B.PRESETS) | set(B.LAUNCH_PRESETS) | {"mail-tui", "mail-shell", "codex-mail"}
        self.assertEqual([v for v in values if v not in known], [])
        self.assertIn("caps.mailbox.codex === true", js)


if __name__ == "__main__":
    unittest.main()
