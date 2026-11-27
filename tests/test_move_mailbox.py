"""Moving a devbox Claude session into the Email box (2026-11-15).

    python3 -m unittest discover -s tests -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

CONV = "11111111-2222-3333-4444-555555555555"


class MoveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.sandhome, self.box = root / "sandhome", root / "mailbox"
        self.box.mkdir()
        proj = self.sandhome / ".claude" / "projects" / "-home-x-sandhome-work"
        proj.mkdir(parents=True)
        (proj / f"{CONV}.jsonl").write_text('{"type":"user","message":{"content":"hi"}}\n')
        self.meta = {"id": "aaaaaaaaaa01", "preset": "claude-tui", "label": "解析/図", "claude_session_id": CONV}
        self.created, self.stopped, self.archived, self.events = [], [], [], []
        names = ("MAILBOX", "SANDHOME", "load_meta", "stop_session", "create_session", "archive_session",
                 "append_event", "require_unlock_if_outside_sandbox", "time", "send_initial_message", "save_meta")
        self.saved = {k: getattr(B, k) for k in names}
        B.MAILBOX = {"dir": self.box}
        B.SANDHOME = self.sandhome
        B.load_meta = lambda sid: dict(self.meta) if sid == "aaaaaaaaaa01" else None
        B.stop_session = lambda sid: self.stopped.append(sid)
        B.create_session = lambda preset, label, **kw: self.created.append((preset, label, kw)) or {"id": "bbbbbbbbbb01"}
        B.archive_session = lambda sid, flag: self.archived.append((sid, flag))
        B.append_event = lambda sid, ev: self.events.append(ev)
        self.notes = []
        B.send_initial_message = lambda sid, text, unlock_key=None: self.notes.append((sid, text))
        B.save_meta = lambda sid, meta: None
        self.unlock = []
        B.require_unlock_if_outside_sandbox = lambda loc: self.unlock.append(loc)

        class T:
            @staticmethod
            def sleep(_s):
                pass

            @staticmethod
            def time():
                return 1794708000.0
        B.time = T

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def test_moves_into_a_box_folder(self):
        new = B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(new["id"], "bbbbbbbbbb01")
        self.assertEqual(self.unlock, ["host"])
        self.assertEqual(self.stopped, ["aaaaaaaaaa01"])
        preset, label, kw = self.created[0]
        self.assertEqual((preset, kw["cwd"], kw["resume"]), ("mail-tui", "work/解析-図", CONV))
        work = self.box / "work" / "解析-図"
        self.assertTrue(work.is_dir())
        copied = B.claude_project_dir(str(work), home=self.box) / f"{CONV}.jsonl"
        self.assertEqual(copied.read_text(), '{"type":"user","message":{"content":"hi"}}\n')
        self.assertEqual(os.stat(copied).st_mode & 0o777, 0o600)
        self.assertEqual(self.archived, [("aaaaaaaaaa01", True)])

    def test_second_move_gets_its_own_folder(self):
        (self.box / "work" / "解析-図").mkdir(parents=True)
        B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(self.created[0][2]["cwd"], "work/解析-図-2")

    def test_failed_start_leaves_nothing_and_can_be_retried(self):
        def broken(preset, label, **kw):
            raise RuntimeError("the box did not start")
        B.create_session = broken
        with self.assertRaises(RuntimeError):
            B.move_to_mailbox("aaaaaaaaaa01")
        self.assertFalse((self.box / "work" / "解析-図").exists())
        self.assertEqual(list(self.box.glob(f".claude/projects/*/{CONV}.jsonl")), [])
        self.assertEqual(self.archived, [])
        B.create_session = lambda preset, label, **kw: self.created.append((preset, label, kw)) or {"id": "bbbbbbbbbb01"}
        B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(self.created[0][2]["cwd"], "work/解析-図")

    def test_moved_is_marked(self):
        B.move_to_mailbox("aaaaaaaaaa01")
        self.assertTrue(any("devbox から移した" in e.get("text", "") for e in self.events))

    def test_the_box_claude_is_told(self):
        import threading
        B.move_to_mailbox("aaaaaaaaaa01")
        for th in threading.enumerate():
            if th is not threading.current_thread() and th.daemon:
                th.join(timeout=1)
        self.assertTrue(any(sid == "bbbbbbbbbb01" and "確かめ直して" in t for sid, t in self.notes))

    def test_links_in_the_box_are_not_followed(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.box / "work").symlink_to(outside)
        with self.assertRaises(OSError):
            B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(list(outside.iterdir()), [])

    def test_invisible_characters_dropped_from_the_folder(self):
        self.meta["label"] = "a\u202eb\u200bc"
        B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(self.created[0][2]["cwd"], "work/abc")

    def test_too_large_is_not_moved(self):
        saved = B.MOVE_MAX_BYTES
        B.MOVE_MAX_BYTES = 10
        try:
            with self.assertRaises(ValueError):
                B.move_to_mailbox("aaaaaaaaaa01")
        finally:
            B.MOVE_MAX_BYTES = saved
        self.assertEqual(self.created, [])

    def test_only_devbox_claude(self):
        self.meta["preset"] = "mail-tui"
        with self.assertRaises(ValueError):
            B.move_to_mailbox("aaaaaaaaaa01")
        self.meta.update(preset="claude-tui", tmux_location="host")
        with self.assertRaises(ValueError):
            B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(self.created, [])

    def test_unlock_first(self):
        def locked(loc):
            raise B.UnlockRequired("host", "user")
        B.require_unlock_if_outside_sandbox = locked
        with self.assertRaises(B.UnlockRequired):
            B.move_to_mailbox("aaaaaaaaaa01")
        self.assertEqual(self.stopped, [])                 # nothing changed


if __name__ == "__main__":
    unittest.main()
