"""Only synthetic rollouts are used here; credentials are never copied."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import codex_transfer as transfer

CONV = '12345678-1234-4234-9234-123456789abc'


class TransferTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.destination = self.root / 'destination'; self.destination.mkdir()
        self.relative = Path('2026/11/15') / ('rollout-synthetic-' + CONV + '.jsonl')
        self.src = self.source / '.codex/sessions' / self.relative
        self.src.parent.mkdir(parents=True)
        self.data = (json.dumps({'type': 'session_meta', 'payload': {'id': CONV, 'source': 'cli'}}) + '\n' +
                     json.dumps({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'synthetic'}}) + '\n').encode()
        self.src.write_bytes(self.data)
        (self.source / '.codex/auth.json').write_text('DO NOT COPY')

    def tearDown(self):
        self.tmp.cleanup()

    def copy(self, receipt=False):
        return transfer.copy_rollout(self.source, self.destination, CONV, return_receipt=receipt)

    def assert_no_copy(self):
        sessions = self.destination / '.codex/sessions'
        self.assertFalse(list(sessions.glob('**/rollout-*.jsonl')) if sessions.exists() else [])

    def test_valid_copy_permissions_source_unchanged(self):
        before = self.src.stat()
        dst = self.copy()
        self.assertEqual(dst.read_bytes(), self.data)
        self.assertEqual(dst.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.src.read_bytes(), self.data)
        self.assertEqual((before.st_ino, before.st_mtime_ns, before.st_ctime_ns),
                         (self.src.stat().st_ino, self.src.stat().st_mtime_ns, self.src.stat().st_ctime_ns))
        self.assertFalse((self.destination / '.codex/auth.json').exists())
        self.assertEqual(transfer.find_rollout(self.source, CONV), self.src)

    def test_existing_destination_not_overwritten(self):
        dst = self.copy()
        with self.assertRaises(FileExistsError):
            self.copy()
        self.assertEqual(dst.read_bytes(), self.data)

    def test_invalid_ids(self):
        for value in ('../x', CONV.upper(), None, 'bad'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError, AttributeError)):
                transfer.copy_rollout(self.source, self.destination, value)

    def test_ambiguous_conversation(self):
        self.src.with_name('rollout-other-' + CONV + '.jsonl').write_bytes(self.data)
        with self.assertRaises(ValueError):
            self.copy()
        self.assert_no_copy()

    def test_source_symlink_hardlink_fifo(self):
        target = self.root / 'target'; target.write_bytes(self.data)
        for kind in ('symlink', 'hardlink', 'fifo'):
            self.src.unlink()
            if kind == 'symlink': self.src.symlink_to(target)
            elif kind == 'hardlink': os.link(target, self.src)
            else: os.mkfifo(self.src)
            with self.subTest(kind=kind), self.assertRaises((OSError, ValueError)):
                self.copy()
            self.assert_no_copy()

    def test_directory_symlink(self):
        old = self.src.parent
        renamed = old.with_name('other'); old.rename(renamed); old.symlink_to(renamed, target_is_directory=True)
        with self.assertRaises(OSError): self.copy()
        self.assert_no_copy()

    def test_destination_symlink(self):
        (self.destination / '.codex').symlink_to(self.source / '.codex', target_is_directory=True)
        with self.assertRaises(OSError): self.copy()
        self.assertEqual(self.src.read_bytes(), self.data)

    def test_malformed_truncated_metadata_source(self):
        invalid = [b'BAD\n', b'[]\n', self.data[:-1], b'', self.data + b'null\n',
                   self.data + b'{"x":NaN}\n', self.data + b'{"x":1,"x":2}\n']
        for meta in ({'id': CONV, 'source': 'exec'}, {'id': 'other', 'source': 'cli'}):
            invalid.append((json.dumps({'type': 'session_meta', 'payload': meta}) + '\n').encode())
        for data in invalid:
            self.src.write_bytes(data)
            with self.subTest(data_length=len(data)), self.assertRaises(ValueError): self.copy()
            self.assert_no_copy()
        self.src.write_bytes(self.data)
        self.assertTrue(self.copy().exists())

    def test_size_and_entry_limits(self):
        for name, limit in (('MAX_BYTES', 20), ('MAX_LINE', 20), ('MAX_ENTRIES', 1)):
            with self.subTest(limit=name), patch.object(transfer, name, limit), self.assertRaises(ValueError): self.copy()
            self.assert_no_copy()

    def test_source_change_during_copy_rejected(self):
        read = os.read
        changed = False
        def changing_read(fd, size):
            nonlocal changed
            data = read(fd, size)
            if data and not changed:
                changed = True
                with self.src.open('ab') as f: f.write(b'{}\n')
            return data
        with patch.object(transfer.os, 'read', changing_read), self.assertRaises(ValueError):
            self.copy()
        self.assert_no_copy()

    def test_failure_cleanup_and_retry(self):
        receipt = self.copy(True)
        self.assertIsInstance(receipt, transfer.TransferReceipt)
        self.assertEqual(receipt.sha256, hashlib.sha256(self.data).hexdigest())
        # create_session raised before the new agent started.
        self.assertTrue(transfer.rollback_rollout(receipt))
        self.assertFalse(receipt.path.exists())
        self.assertEqual(self.copy().read_bytes(), self.data)
        self.assertEqual(self.src.read_bytes(), self.data)

    def test_cleanup_refuses_same_name_replacement(self):
        receipt = self.copy(True)
        replacement = receipt.path.with_name('replacement'); replacement.write_bytes(self.data)
        replacement.replace(receipt.path)
        self.assertFalse(transfer.rollback_rollout(receipt))
        self.assertEqual(receipt.path.read_bytes(), self.data)

    def test_cleanup_refuses_modified_or_hardlinked(self):
        receipt = self.copy(True)
        receipt.path.write_bytes(self.data + b'changed')
        self.assertFalse(transfer.rollback_rollout(receipt))
        self.assertTrue(receipt.path.exists())
        receipt.path.write_bytes(self.data)
        os.link(receipt.path, receipt.path.with_name('hardlink'))
        self.assertFalse(transfer.rollback_rollout(receipt))
        self.assertTrue(receipt.path.exists())

    def test_cleanup_rename_race_preserves_replacement(self):
        receipt = self.copy(True)
        rename = os.rename
        def replace_before_rename(src, dst, **kw):
            replacement = receipt.path.with_name('replacement')
            replacement.write_bytes(b'NEW FILE')
            replacement.replace(receipt.path)
            return rename(src, dst, **kw)
        with patch.object(transfer.os, 'rename', replace_before_rename):
            self.assertFalse(transfer.rollback_rollout(receipt))
        self.assertEqual(receipt.path.read_bytes(), b'NEW FILE')

    def test_cleanup_collision_preserves_both(self):
        receipt = self.copy(True)
        rename = os.rename
        def replace_twice(src, dst, **kw):
            replacement = receipt.path.with_name('replacement')
            replacement.write_bytes(b'FIRST REPLACEMENT')
            replacement.replace(receipt.path)
            result = rename(src, dst, **kw)
            receipt.path.write_bytes(b'SECOND REPLACEMENT')
            return result
        with patch.object(transfer.os, 'rename', replace_twice):
            self.assertFalse(transfer.rollback_rollout(receipt))
        self.assertEqual(receipt.path.read_bytes(), b'SECOND REPLACEMENT')
        held = list(receipt.path.parent.glob('.rollout-rollback-*/candidate'))
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0].read_bytes(), b'FIRST REPLACEMENT')


if __name__ == '__main__': unittest.main()
