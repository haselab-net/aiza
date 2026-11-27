"""The host-only session store (the deployment notes, 2026-11-14): sessions
outside the containers (host, root, ssh:) live in ~/.aiza-state/sessions, not
in ~/sandhome/.aiza (writable from devbox-<user> and the Email box). Older
ones are moved: stopped ones whole, live ones at start-up with their old
directory kept and synced until they end. A moved tree carries plain files
and directories only. Also lib/aiza_session_path (talkto and the hooks find
the new directory from the old AIZA_TALKTO) and the Codex chat tailer's
state checks and "is Codex in front" decision.

    python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from test_shared_search import B

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("aiza_session_path", ROOT / "lib" / "aiza_session_path.py")
SP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SP)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.sandhome = self.home / "sandhome"
        self.old = self.sandhome / ".aiza"
        self.state = self.home / ".aiza-state"
        self.new = self.state / "sessions"
        # the store itself is made by the first run (after its plan)
        for d in (self.old, self.state):
            d.mkdir(parents=True)
        self.home.chmod(0o755)
        self.state.chmod(0o755)
        stubs = {"SANDHOME": self.sandhome, "SESSIONS_DIR": self.old, "STATE_DIR": self.state,
                 "HOST_SESSIONS_DIR": self.new, "MAIL_SESSIONS_DIR": None, "HOME": self.home,
                 "SESSION_STORE_MARK": self.home / ".aiza-session-store-enabled",
                 "MIGRATION_PLAN": self.state / "session-store-migration.json",
                 "SESSION_STORE_ENABLED": True, "_host_ids": set(),
                 "tmux_exec": lambda loc, args, **kw: subprocess.CompletedProcess(args, 0, "", "")}
        self.saved = {k: getattr(B, k) for k in stubs}
        for k, v in stubs.items():
            setattr(B, k, v)
        B._session_resuming.clear()

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def make_old(self, sid, location="root", stopped=True, extra=None):
        d = self.old / sid
        (d / "outbox" / "sub").mkdir(parents=True)
        for name in B._MOVE_SKIP:
            (d / name).write_text("{}\n")
        preset = {"root": "root-shell", "host": "host-shell", "container": "shell"}[location]
        (d / "meta.json").write_text(json.dumps({"id": sid, "tmux_location": location, "stopped": stopped,
                                                 "preset": preset, **(extra or {})}))
        (d / "events.jsonl").write_text('{"seq": 1}\n')
        (d / "talkto_out.jsonl").write_text('{"id": "a"}\n')
        (d / "outbox" / "sub" / "f.txt").write_text("x")
        os.symlink("/etc/passwd", d / "evil")
        os.symlink("/etc", d / "outbox" / "evil-dir")
        os.mkfifo(d / "screen.fifo")
        return d

    def test_new_session_dirs_in_the_store_are_private_whatever_the_umask(self):
        self.new.mkdir(mode=0o700)
        d = self.new / "a1a1a1a1a1a1"
        old = os.umask(0o002)
        try:
            (d / "outbox").mkdir(parents=True)
        finally:
            os.umask(old)
        B._private_session_dir(d)
        self.assertEqual(oct(d.stat().st_mode & 0o777), "0o700")

    def test_a_user_not_on_the_list_keeps_everything_where_it_was(self):
        saved = B.SESSION_STORE_ENABLED
        B.SESSION_STORE_ENABLED = False
        try:
            self.assertEqual(B.session_dir("aaaaaaaaaaaa", preset="root-shell"), self.old / "aaaaaaaaaaaa")
            self.assertEqual(B.session_dir("aaaaaaaaaaaa", location="ssh:m"), self.old / "aaaaaaaaaaaa")
        finally:
            B.SESSION_STORE_ENABLED = saved

    def test_the_list_is_read_from_the_config(self):
        cfg = Path(self.tmp.name) / "session-store.json"
        saved = B.SESSION_STORE_CONFIG
        B.SESSION_STORE_CONFIG = str(cfg)
        try:
            self.assertFalse(B._session_store_enabled())                 # no file: off
            cfg.write_text(json.dumps({"users": ["someone-else"]}))
            self.assertFalse(B._session_store_enabled())
            import getpass
            cfg.write_text(json.dumps({"users": [getpass.getuser()]}))
            self.assertTrue(B._session_store_enabled())
            cfg.write_text("not json")
            self.assertFalse(B._session_store_enabled())
        finally:
            B.SESSION_STORE_CONFIG = saved

    def test_new_sessions_go_where_they_run(self):
        self.assertEqual(B.session_dir("aaaaaaaaaaaa", preset="host-shell"), self.new / "aaaaaaaaaaaa")
        self.assertEqual(B.session_dir("aaaaaaaaaaaa", preset="root-shell"), self.new / "aaaaaaaaaaaa")
        self.assertEqual(B.session_dir("aaaaaaaaaaaa", preset="shell"), self.old / "aaaaaaaaaaaa")
        self.assertEqual(B.session_dir("aaaaaaaaaaaa", preset="claude"), self.old / "aaaaaaaaaaaa")
        self.assertEqual(B.session_dir("aaaaaaaaaaaa", location="ssh:m"), self.new / "aaaaaaaaaaaa")
        self.assertEqual(B.session_dir("aaaaaaaaaaaa", location="container"), self.old / "aaaaaaaaaaaa")

    def vouch(self, *ids):
        (self.state / "session_order.json").write_text(json.dumps(list(ids)))

    def run_once(self):
        return B.run_session_store_migration()

    def test_one_time_move_of_a_vouched_stopped_session(self):
        self.make_old("bbbbbbbbbbbb", extra={"auto": True, "issue": "o/r#1", "planted_key": 1, "label": "x" * 300,
                                             "shared_with": ["*"], "skip_permissions": True,
                                             "cwd": str(self.sandhome / "proj"), "claude_cwd": "/root/work"})
        self.vouch("bbbbbbbbbbbb")
        self.assertEqual(self.run_once(), (1, 0))
        d = self.new / "bbbbbbbbbbbb"
        self.assertFalse((self.old / "bbbbbbbbbbbb").exists())
        self.assertEqual((d / "events.jsonl").read_text(), '{"seq": 1}\n')
        self.assertEqual((d / "outbox" / "sub" / "f.txt").read_text(), "x")
        for gone in ("evil", "screen.fifo", "outbox/evil-dir", *B._MOVE_SKIP):
            self.assertFalse(os.path.lexists(d / gone), gone)
        meta = json.loads((d / "meta.json").read_text())
        self.assertTrue(meta["migrated"])
        self.assertEqual((meta["auto"], meta["issue"]), (False, None))
        self.assertNotIn("planted_key", meta)
        self.assertNotIn("label", meta)                                  # too long: dropped
        self.assertNotIn("shared_with", meta)                            # sharing is not carried
        self.assertFalse(meta["skip_permissions"])                       # root: prompts back on
        self.assertNotIn("cwd", meta)                                    # a container-writable folder
        self.assertEqual(meta["claude_cwd"], "/root/work")
        self.assertEqual(oct(d.stat().st_mode & 0o777), "0o700")
        self.assertTrue(B.SESSION_STORE_MARK.exists())
        self.assertFalse(B.MIGRATION_PLAN.exists())
        self.assertEqual(B.load_meta("bbbbbbbbbbbb")["id"], "bbbbbbbbbbbb")

    def test_a_lost_mark_is_put_back_without_a_second_move(self):
        self.make_old("a9a9a9a9a9a9")
        self.vouch("a9a9a9a9a9a9")
        # the store exists (from before), no plan, no mark: e.g. the mark was deleted
        self.new.mkdir(mode=0o700)
        self.assertEqual(self.run_once(), (0, 0))
        self.assertTrue(B.SESSION_STORE_MARK.exists())
        self.assertFalse((self.new / "a9a9a9a9a9a9").exists())
        self.assertTrue((self.old / "a9a9a9a9a9a9").exists())

    def test_first_run_makes_the_store_after_its_plan(self):
        self.make_old("b9b9b9b9b9b9")
        self.vouch("b9b9b9b9b9b9")
        self.assertEqual(self.run_once(), (1, 0))
        self.assertEqual(oct(self.new.stat().st_mode & 0o777), "0o700")
        self.assertTrue((self.new / "b9b9b9b9b9b9").is_dir())

    def test_only_once_and_only_what_this_host_vouches_for(self):
        self.make_old("cccccccccccc", location="container")
        self.make_old("dddddddddddd")                                     # not vouched for
        self.vouch()
        self.assertEqual(self.run_once(), (0, 1))
        self.assertIsNotNone(B.load_meta("cccccccccccc"))                # a container session stays, visible
        self.assertIsNone(B.load_meta("dddddddddddd"))                   # a root session left in ~/sandhome is hidden
        self.make_old("eeeeeeeeeeee")
        self.vouch("eeeeeeeeeeee")
        self.assertEqual(self.run_once(), (0, 0))                        # done before: nothing more is taken
        self.assertFalse((self.new / "eeeeeeeeeeee").exists())
        self.assertIsNone(B.load_meta("eeeeeeeeeeee"))

    def test_an_ended_session_of_a_machine_no_longer_configured_is_moved(self):
        for sid, stopped in (("d1d1d1d1d1d1", True), ("d2d2d2d2d2d2", False)):
            self.make_old(sid, stopped=stopped, extra={"preset": "shell-oldbox", "tmux_location": "ssh:oldbox"})
        self.vouch("d1d1d1d1d1d1", "d2d2d2d2d2d2")
        self.run_once()
        self.assertTrue((self.new / "d1d1d1d1d1d1" / "meta.json").exists())
        self.assertFalse((self.new / "d2d2d2d2d2d2").exists())          # a live one of a gone machine: not moved

    def test_checked_on_the_copy(self):
        self.make_old("f0f0f0f0f0f0", extra={"preset": "shell"})        # shell runs in a container, not root
        self.vouch("f0f0f0f0f0f0")
        self.run_once()
        self.assertFalse((self.new / "f0f0f0f0f0f0").exists())
        self.assertEqual(list((self.state / "sessions-moving").iterdir()), [])

    def test_too_big_stays_where_it_was(self):
        self.make_old("f1f1f1f1f1f1")
        (self.old / "f1f1f1f1f1f1" / "outbox" / "big").write_bytes(b"x" * 4096)
        self.vouch("f1f1f1f1f1f1")
        saved = B.SESSION_MIGRATE_MAX_BYTES
        B.SESSION_MIGRATE_MAX_BYTES = 1024
        try:
            self.run_once()
        finally:
            B.SESSION_MIGRATE_MAX_BYTES = saved
        self.assertFalse((self.new / "f1f1f1f1f1f1").exists())
        self.assertFalse(B.MIGRATION_PLAN.exists())

    def test_live_session_old_dir_is_emptied_and_never_carries_anything(self):
        old = self.make_old("a2a2a2a2a2a2", location="host", stopped=False)
        self.vouch("a2a2a2a2a2a2")
        self.run_once()
        new = self.new / "a2a2a2a2a2a2"
        self.assertTrue((new / B.MOVED_FROM_NAME).is_file())
        left = sorted(str(p.relative_to(old)) for p in old.rglob("*"))
        self.assertEqual(left, ["outbox"])                               # only an empty outbox/
        notes = [json.loads(l) for l in (new / "events.jsonl").read_text().splitlines()]
        self.assertTrue(any("ホストだけの置き場" in e.get("text", "") for e in notes))   # told in the new chat
        with open(old / "talkto_out.jsonl", "a") as f:
            f.write('{"id": "forged"}\n')
        (old / "codex-chat.jsonl").write_text("{}\n")
        (old / "outbox" / "attachment.png").write_bytes(b"png")
        os.utime(old / "outbox" / "attachment.png", (time.time() - 60, time.time() - 60))
        B._sync_moved_sessions()
        self.assertFalse((new / "talkto_out.jsonl").exists())
        self.assertFalse((new / "outbox" / "attachment.png").exists())   # not carried, even an attachment
        self.assertEqual(sorted(str(p.relative_to(old)) for p in old.rglob("*")), ["outbox"])
        meta = json.loads((new / "meta.json").read_text()); meta["stopped"] = True
        (new / "meta.json").write_text(json.dumps(meta))
        B._sync_moved_sessions()
        self.assertFalse(old.exists())
        self.assertFalse((new / B.MOVED_FROM_NAME).exists())

    def test_crash_recovery_retries_the_plan_only_and_an_existing_copy_takes_nothing(self):
        self.make_old("a3a3a3a3a3a3")
        old = self.make_old("a4a4a4a4a4a4", stopped=False)
        self.vouch("a3a3a3a3a3a3", "a4a4a4a4a4a4")
        # as if the last start-up had copied a4 and then crashed
        self.new.mkdir(mode=0o700)
        (self.new / "a4a4a4a4a4a4").mkdir(mode=0o700)
        (self.new / "a4a4a4a4a4a4" / B.MOVED_FROM_NAME).write_text("a4a4a4a4a4a4")
        B._write_plan(["a3a3a3a3a3a3", "a4a4a4a4a4a4"])
        B._mark_session_store()
        touched = []
        saved = B.tmux_exec
        B.tmux_exec = lambda loc, args, **kw: touched.append(args) or subprocess.CompletedProcess(args, 0, "", "")
        try:
            self.run_once()
        finally:
            B.tmux_exec = saved
        self.assertTrue((self.new / "a3a3a3a3a3a3" / "meta.json").exists())
        self.assertFalse((self.new / "a4a4a4a4a4a4" / "meta.json").exists())      # nothing carried into it
        self.assertEqual(sorted(str(p.relative_to(old)) for p in old.rglob("*")), ["outbox"])
        self.assertEqual(touched, [])                                     # tmux not touched for it
        self.assertFalse(B.MIGRATION_PLAN.exists())

    def test_each_tree_holds_only_its_own_kind(self):
        mail = Path(self.tmp.name) / "mailbox" / ".aiza"
        (mail / "a5a5a5a5a5a5").mkdir(parents=True)
        (mail / "a5a5a5a5a5a5" / "meta.json").write_text(json.dumps({"id": "a5a5a5a5a5a5", "preset": "root-shell",
                                                                      "tmux_location": "root"}))
        (self.old / "a6a6a6a6a6a6").mkdir()
        (self.old / "a6a6a6a6a6a6" / "meta.json").write_text(json.dumps({"id": "a6a6a6a6a6a6", "preset": "mail-tui",
                                                                          "tmux_location": "host"}))
        saved = (B.MAIL_SESSIONS_DIR, B.MAIL_TREE_PRESETS)
        B.MAIL_SESSIONS_DIR, B.MAIL_TREE_PRESETS = mail, {"mail-tui", "mail-shell"}
        try:
            self.assertIsNone(B.load_meta("a5a5a5a5a5a5"))               # root-shell in the Email tree
            self.assertIsNone(B.load_meta("a6a6a6a6a6a6"))               # an Email preset in ~/sandhome
        finally:
            B.MAIL_SESSIONS_DIR, B.MAIL_TREE_PRESETS = saved

    def test_preset_must_run_where_meta_says(self):
        (self.old / "c5c5c5c5c5c5").mkdir()
        (self.old / "c5c5c5c5c5c5" / "meta.json").write_text(json.dumps({
            "id": "c5c5c5c5c5c5", "preset": "root-shell", "tmux_location": "container", "stopped": True,
            "claude_session_id": "9548bfee-988a-44c8-813e-99bf3a36b0d0"}))
        self.assertIsNone(B.load_meta("c5c5c5c5c5c5"))
        saved = B.SESSION_STORE_ENABLED
        B.SESSION_STORE_ENABLED = False                                   # also for a user without the store
        try:
            self.assertIsNone(B.load_meta("c5c5c5c5c5c5"))
        finally:
            B.SESSION_STORE_ENABLED = saved
        self.assertNotIn("c5c5c5c5c5c5", [m["id"] for m in B.list_sessions()])
        with self.assertRaises(ValueError):
            B.create_session("root-shell", None, resume="9548bfee-988a-44c8-813e-99bf3a36b0d0",
                             replace_session="c5c5c5c5c5c5")
        ok = {"id": "x", "preset": "shell", "tmux_location": "container"}
        self.assertTrue(B._preset_location_ok(ok))
        self.assertTrue(B._preset_location_ok({"preset": "claude"}))
        self.assertFalse(B._preset_location_ok({"preset": "claude", "tmux_location": "root"}))
        self.assertFalse(B._preset_location_ok({"preset": "host-shell", "tmux_location": "root"}))
        self.assertTrue(B._preset_location_ok({"preset": "attach", "tmux_location": "host"}))
        self.assertFalse(B._preset_location_ok({"preset": "attach", "tmux_location": "root"}))
        self.assertTrue(B._preset_location_ok({"preset": "shell-gone", "tmux_location": "ssh:gone"}))
        self.assertFalse(B._preset_location_ok({"preset": "root-shell", "tmux_location": "ssh:gone"}))

    def test_email_tree_holds_its_presets_at_their_own_location(self):
        mail = Path(self.tmp.name) / "mailbox" / ".aiza"
        for sid, meta in (("b1b1b1b1b1b1", {"preset": "mail-tui", "tmux_location": "host"}),        # the real shape
                          ("b2b2b2b2b2b2", {"preset": "mail-tui", "tmux_location": "container"}),   # wrong location
                          ("b3b3b3b3b3b3", {"preset": "shell", "tmux_location": "container"})):     # not an Email preset
            (mail / sid).mkdir(parents=True)
            (mail / sid / "meta.json").write_text(json.dumps({"id": sid, **meta}))
        saved = (B.MAIL_SESSIONS_DIR, B.MAIL_TREE_PRESETS, B.TMUX_PRESETS)
        B.MAIL_SESSIONS_DIR, B.MAIL_TREE_PRESETS = mail, {"mail-tui", "mail-shell"}
        B.TMUX_PRESETS = {**B.TMUX_PRESETS, "mail-tui": {"command": ["true"], "location": "host"}}
        try:
            self.assertEqual(B.load_meta("b1b1b1b1b1b1")["preset"], "mail-tui")
            self.assertIsNone(B.load_meta("b2b2b2b2b2b2"))
            self.assertIsNone(B.load_meta("b3b3b3b3b3b3"))
        finally:
            B.MAIL_SESSIONS_DIR, B.MAIL_TREE_PRESETS, B.TMUX_PRESETS = saved

    def test_resume_only_from_the_same_tree(self):
        (self.old / "c6c6c6c6c6c6").mkdir()
        (self.old / "c6c6c6c6c6c6" / "meta.json").write_text(json.dumps({
            "id": "c6c6c6c6c6c6", "preset": "shell", "tmux_location": "container", "stopped": True,
            "claude_session_id": "9548bfee-988a-44c8-813e-99bf3a36b0d0"}))
        with self.assertRaises(ValueError):
            B.create_session("host-shell", None, resume="9548bfee-988a-44c8-813e-99bf3a36b0d0",
                             replace_session="c6c6c6c6c6c6")

    def test_a_host_session_is_never_written_outside_the_store(self):
        self.make_old("a7a7a7a7a7a7")
        self.vouch("a7a7a7a7a7a7")
        self.run_once()
        shutil.rmtree(self.new / "a7a7a7a7a7a7")
        planted = self.old / "a7a7a7a7a7a7"
        planted.mkdir()
        (planted / "events.jsonl").write_text("")
        B.append_event("a7a7a7a7a7a7", {"type": "system", "text": "secret"})
        self.assertEqual((planted / "events.jsonl").read_text(), "")
        self.assertIsNone(B.load_meta("a7a7a7a7a7a7"))

    def test_mark_must_be_this_users_plain_file(self):
        self.assertTrue(B._mark_session_store())
        self.assertEqual(oct(B.SESSION_STORE_MARK.stat().st_mode & 0o777), "0o600")
        os.link(B.SESSION_STORE_MARK, self.home / "second-link")
        self.assertFalse(B._mark_session_store())                       # two links: refused
        os.unlink(self.home / "second-link")
        B.SESSION_STORE_MARK.unlink()
        os.symlink("/etc/passwd", B.SESSION_STORE_MARK)
        self.assertFalse(B._mark_session_store())                       # a link: refused, not followed
        os.unlink(B.SESSION_STORE_MARK)
        self.make_old("a8a8a8a8a8a8")
        self.vouch("a8a8a8a8a8a8")
        os.mkdir(B.SESSION_STORE_MARK)                                    # cannot be written: nothing moves
        self.run_once()
        self.assertFalse((self.new / "a8a8a8a8a8a8").exists())

    def test_finish_moves_command_line_never_starts_a_backend_or_guesses(self):
        from unittest import mock
        calls = []
        with mock.patch.object(B, "_sync_moved_sessions", lambda finish=None: calls.append(finish)), \
                mock.patch.object(B, "load_extensions", lambda d: self.fail("would start a backend")):
            for argv, enabled in ((["--finish-moves"], True), (["--finish-moves", "nope"], True),
                                  (["--finish-moves", "aaaaaaaaaaaa", "../x"], True),
                                  (["--finish-moves", "aaaaaaaaaaaa"], False)):
                with mock.patch.object(B, "SESSION_STORE_ENABLED", enabled), \
                        mock.patch.object(sys, "argv", ["aiza-backend", *argv]):
                    with self.assertRaises(SystemExit) as cm:
                        B.main()
                    self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(calls, [])
            for argv, want in ((["--finish-moves", "aaaaaaaaaaaa", "bbbbbbbbbbbb"], {"aaaaaaaaaaaa", "bbbbbbbbbbbb"}),
                               (["--finish-moves", "--all"], set())):
                with mock.patch.object(B, "SESSION_STORE_ENABLED", True), \
                        mock.patch.object(sys, "argv", ["aiza-backend", *argv]):
                    B.main()
                self.assertEqual(calls[-1], want)

    def test_finish_moves_drops_the_old_directory_of_a_live_session(self):
        old = self.make_old("cdcdcdcdcdcd", stopped=False)
        self.vouch("cdcdcdcdcdcd")
        self.run_once()
        B._sync_moved_sessions(finish={"ffffffffffff"})                 # another id: untouched
        self.assertTrue(old.exists())
        B._sync_moved_sessions(finish={"cdcdcdcdcdcd"})
        self.assertFalse(old.exists())
        self.assertFalse((self.new / "cdcdcdcdcdcd" / B.MOVED_FROM_NAME).exists())
        self.assertEqual(B.session_dir("cdcdcdcdcdcd"), self.new / "cdcdcdcdcdcd")

    def test_resolver_follows_the_move_and_refuses_links(self):
        sid = "ffffffffffff"
        (self.old / sid).mkdir()
        talkto = str(self.old / sid / "talkto_out.jsonl")
        # Only a container without the host state mounted may use a legacy path.
        os.rename(self.state, self.home / 'hidden-state')
        try:
            fd, path = SP.open_session_dir(talkto)
            os.close(fd)
            self.assertEqual(path, str(self.old / sid))
        finally:
            os.rename(self.home / 'hidden-state', self.state)
        self.new.mkdir(mode=0o700, exist_ok=True)
        (self.new / sid).mkdir(mode=0o700)
        os.chmod(self.new, 0o700); os.chmod(self.state, 0o755)
        fd, path = SP.open_session_dir(talkto)
        os.close(fd)
        self.assertEqual(path, str(self.new / sid))
        # A bad host-only path fails closed, never redirects writes into the sandbox.
        (self.new / sid).rmdir()
        os.symlink(self.old / sid, self.new / sid)
        with self.assertRaises(OSError):
            SP.open_session_dir(talkto)
        os.unlink(self.new / sid)
        # nor is a link on the way to the old one
        os.rename(self.old, self.sandhome / "real")
        os.symlink(self.sandhome / "real", self.old)
        with self.assertRaises(OSError):
            SP.open_session_dir(talkto)


class CodexTailerTest(unittest.TestCase):
    def test_bad_cursors_are_dropped(self):
        st = {"version": 2, "sources": {"a": {"offset": 5, "parser": {"thread": "t", "paginated": True}},
                                         "b": {"offset": "x", "parser": {}},
                                         "c": {"offset": -1, "parser": {}}, "d": {"offset": 1, "parser": []},
                                         "e": {"offset": True, "parser": {}},
                                         "f": {"offset": 1, "parser": {"thread": 3}},
                                         "g": {"offset": 1, "parser": {"paginated": 1}}}}
        self.assertEqual(list(B._valid_codex_state(st)["sources"]), ["a"])
        self.assertEqual(B._valid_codex_state({"version": 1}), {"version": 2, "sources": {}})
        self.assertEqual(B._valid_codex_state([]), {"version": 2, "sources": {}})

    def _active(self, active_json, fg=None):
        d = Path(tempfile.mkdtemp())
        if active_json is not None:
            (d / "codex-active.json").write_text(json.dumps(active_json))
        saved = B.tmux_query
        def q(loc, args, **kw):
            if fg is None:
                raise subprocess.TimeoutExpired(args, 5)
            return subprocess.CompletedProcess(args, 0, fg + "\n", "")
        B.tmux_query = q
        try:
            return B._codex_relay_active("s", {"tmux_location": "root"}, d)
        finally:
            B.tmux_query = saved

    def test_front_needs_more_than_the_relays_word(self):
        me = os.getpid(); start = B._proc_starttime(me)
        self.assertTrue(self._active({"active": True, "pid": me, "starttime": start}))
        self.assertFalse(self._active({"active": True, "pid": me, "starttime": start + 1}))   # pid reused
        self.assertFalse(self._active({"active": True}))                                      # nothing backs it
        self.assertTrue(self._active({"active": True}, fg="codex"))
        self.assertFalse(self._active({"active": True}, fg="bash"))
        self.assertFalse(self._active({"active": True, "pid": me, "starttime": start}, fg="bash"))
        self.assertFalse(self._active({"active": False, "pid": me, "starttime": start}, fg="codex"))
        self.assertFalse(self._active(None, fg="codex"))


if __name__ == "__main__":
    unittest.main()
