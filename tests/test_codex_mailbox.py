"""Synthetic, offline Codex mailbox transfer integration; no real box access."""
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from test_shared_search import B

CONV = '12345678-1234-4234-9234-123456789abc'
SID = 'aaaaaaaaaa01'
NEW = 'bbbbbbbbbb01'


class CodexMailboxTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source, self.box = root / 'sandhome', root / 'mailbox'
        self.source.mkdir(); self.box.mkdir()
        self.src = self.source / '.codex/sessions/2026/11/15' / ('rollout-synthetic-' + CONV + '.jsonl')
        self.src.parent.mkdir(parents=True)
        self.data = (json.dumps({'type': 'session_meta', 'payload': {'id': CONV, 'source': 'cli'}}) + '\n').encode()
        self.src.write_bytes(self.data)
        self.meta = {'id': SID, 'preset': 'codex-tui', 'tmux_location': 'container', 'label': '解析/図', 'skip_permissions': True}
        self.new_meta = {'id': NEW}
        self.created, self.stopped, self.archived, self.events, self.notes, self.unlock = [], [], [], [], [], []
        self.stack = ExitStack()
        overrides = dict(MAILBOX={'dir': self.box}, SANDHOME=self.source,
            LAUNCH_PRESETS=dict(B.LAUNCH_PRESETS, **{'codex-mail': ('mail-shell', 'codex')}),
            load_meta=lambda sid: dict(self.meta if sid == SID else self.new_meta),
            _codex_conv_of=lambda sid: CONV,
            stop_session=self.stop, create_session=self.create,
            archive_session=lambda sid, flag: self.archived.append((sid, flag)),
            append_event=lambda sid, ev: self.events.append((sid, ev)),
            send_initial_message=lambda sid, text: self.notes.append((sid, text)),
            save_meta=lambda sid, meta: self.new_meta.update(meta),
            list_tmux_sessions=lambda: set(),
            require_unlock_if_outside_sandbox=lambda loc: self.unlock.append(loc))
        for key, value in overrides.items(): self.stack.enter_context(patch.object(B, key, value))
        self.stack.enter_context(patch.object(B.time, 'sleep', lambda _: None))
        # Keep first-input dispatch deterministic and isolated from other tests.
        class Immediate:
            def __init__(self, target, args=(), **kw): self.target, self.args = target, args
            def start(self): self.target(*self.args)
        self.stack.enter_context(patch.object(B.threading, 'Thread', Immediate))

    def tearDown(self):
        self.stack.close(); self.tmp.cleanup()

    def stop(self, sid):
        self.stopped.append(sid); self.meta['stopped'] = True

    def create(self, preset, label, **kw):
        self.created.append((preset, label, kw)); return {'id': NEW}

    def test_copy_and_resume_policy_warning_and_archive(self):
        self.assertTrue(B.can_move_to_mailbox(self.meta))
        self.assertEqual(B.move_to_mailbox(SID), {'id': NEW})
        self.assertEqual(self.unlock, ['host'])
        self.assertEqual(self.stopped, [SID])
        self.assertEqual(self.created, [('codex-mail', '解析/図', {'cwd': 'work/解析-図', 'resume': CONV, 'skip_permissions': False})])
        self.assertEqual(self.archived, [(SID, True)])
        self.assertEqual(self.src.read_bytes(), self.data)
        self.assertEqual(next(self.box.glob('.codex/sessions/**/*.jsonl')).read_bytes(), self.data)
        self.assertIn('moved_from', self.new_meta)
        self.assertTrue(any('確かめ直して' in text for _, text in self.notes))
        self.assertTrue(any('devbox から移した' in ev.get('text', '') for _, ev in self.events))

    def test_manual_codex_in_devbox_shell(self):
        self.meta['preset'] = 'shell'
        self.assertTrue(B.can_move_to_mailbox(self.meta))
        B.move_to_mailbox(SID)
        self.assertEqual(self.created[0][0], 'codex-mail')

    def test_disabled_until_codex_mail_entry_exists(self):
        with patch.object(B, 'LAUNCH_PRESETS', {}):
            self.assertFalse(B.can_move_to_mailbox(self.meta))
            with self.assertRaises(ValueError): B.move_to_mailbox(SID)
        self.assertEqual(self.stopped, [])

    def test_root_host_and_unknown_conversation_rejected(self):
        for location in ('host', 'root', 'ssh:other'):
            self.meta['tmux_location'] = location
            self.assertFalse(B.can_move_to_mailbox(self.meta))
            with self.assertRaises(ValueError): B.move_to_mailbox(SID)
        self.meta['tmux_location'] = 'container'
        with patch.object(B, '_codex_conv_of', lambda _: None):
            self.assertFalse(B.can_move_to_mailbox(self.meta))
            with self.assertRaises(ValueError): B.move_to_mailbox(SID)
        self.assertEqual(self.stopped, [])

    def test_missing_or_invalid_session_id_rejected(self):
        for sid in (None, '', '../other', 12):
            self.meta['id'] = sid
            with patch.object(B, '_codex_conv_of', side_effect=AssertionError('must not read')):
                self.assertFalse(B.can_move_to_mailbox(self.meta))

    def test_unlock_before_any_changes(self):
        def locked(_): raise B.UnlockRequired('host', 'user')
        with patch.object(B, 'require_unlock_if_outside_sandbox', locked), self.assertRaises(B.UnlockRequired):
            B.move_to_mailbox(SID)
        self.assertEqual(self.stopped, [])
        self.assertEqual(list(self.box.iterdir()), [])

    def test_stop_failure_still_alive_and_changed_conversation(self):
        def failed(_): raise RuntimeError('synthetic stop failure')
        with patch.object(B, 'stop_session', failed), self.assertRaises(RuntimeError): B.move_to_mailbox(SID)
        with patch.object(B, 'list_tmux_sessions', lambda: {SID}), self.assertRaises(ValueError): B.move_to_mailbox(SID)
        self.meta['stopped'] = False
        def change(sid): self.stop(sid); self.meta['changed'] = True
        with patch.object(B, 'stop_session', change), patch.object(B, '_codex_conv_of', lambda _: 'other' if self.meta.get('changed') else CONV), self.assertRaises(ValueError):
            B.move_to_mailbox(SID)
        self.assertEqual(self.created, [])
        self.assertEqual(list(self.box.iterdir()), [])

    def test_failure_rollback_then_retry(self):
        def fail(*args, **kw): raise RuntimeError('synthetic start failure')
        with patch.object(B, 'create_session', fail), self.assertRaises(RuntimeError): B.move_to_mailbox(SID)
        self.assertFalse(list(self.box.glob('.codex/sessions/**/*.jsonl')))
        self.assertFalse((self.box / 'work/解析-図').exists())
        self.assertEqual(self.archived, [])
        B.move_to_mailbox(SID)
        self.assertEqual(self.created[0][2]['cwd'], 'work/解析-図')

    def test_conversation_changed_after_copy_is_rolled_back(self):
        import codex_transfer
        copy = codex_transfer.copy_rollout
        changed = False
        def switch(*args, **kw):
            nonlocal changed
            receipt = copy(*args, **kw)
            changed = True
            return receipt
        with patch.object(codex_transfer, 'copy_rollout', switch), patch.object(B, '_codex_conv_of', lambda _: 'other' if changed else CONV), self.assertRaises(ValueError):
            B.move_to_mailbox(SID)
        self.assertEqual(self.created, [])
        self.assertEqual(self.archived, [])
        self.assertFalse(list(self.box.glob('.codex/sessions/**/*.jsonl')))

    def test_modified_copy_survives_failed_start(self):
        def fail(*args, **kw):
            next(self.box.glob('.codex/sessions/**/*.jsonl')).write_bytes(b'CHANGED')
            raise RuntimeError('synthetic start failure')
        with patch.object(B, 'create_session', fail), self.assertRaisesRegex(RuntimeError, '管理者が確認'):
            B.move_to_mailbox(SID)
        self.assertEqual(next(self.box.glob('.codex/sessions/**/*.jsonl')).read_bytes(), b'CHANGED')
        self.assertEqual(self.archived, [])

    def test_name_controls_removed_and_work_link_rejected(self):
        self.meta['label'] = 'a\u202eb\u200bc\x01'
        B.move_to_mailbox(SID)
        self.assertEqual(self.created[0][2]['cwd'], 'work/abc')
        other = self.box / 'other'; other.mkdir()
        (self.box / 'work').rename(self.box / 'old-work')
        (self.box / 'work').symlink_to(other, target_is_directory=True)
        with self.assertRaises(OSError): B.move_to_mailbox(SID)
        self.assertEqual(list(other.iterdir()), [])


if __name__ == '__main__': unittest.main()
