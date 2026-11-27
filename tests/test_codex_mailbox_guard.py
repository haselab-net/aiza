"""No real local-only data is read: fixtures exercise pre-tool decisions only."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'bin/aiza-codex-mailbox-guard'
loader = importlib.machinery.SourceFileLoader('mail_guard', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
guard = importlib.util.module_from_spec(spec)
loader.exec_module(guard)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.policy = self.home / '.claude/hooks/local-only-guard.py'
        self.policy.parent.mkdir(parents=True)
        self.policy.write_text('import sys,json\ne=json.load(sys.stdin)\nsys.exit(2 if e["tool_input"].get("command") == "broad search" else 0)\n')
        self.policy.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def event(self, tool='Bash', **ti):
        return {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': ti}

    def test_native_bash_passes_canonical_guard_and_its_deny(self):
        self.assertTrue(guard.allowed(self.event(command='pwd'), self.home))
        self.assertFalse(guard.allowed(self.event(command='broad search'), self.home))

    def test_all_tools_opaque_nested_inputs_block_local_only(self):
        for e in (self.event(command='cat ~/work/.local-only/x'),
                  self.event('apply_patch', input='*** Add File: work/.local-only/x\n+new'),
                  self.event('mcp__read', arguments={'files': ['work/.local-only/x']}),
                  self.event('read_file', **{'.local-only': 'value'})):
            with self.subTest(e=e):
                with patch.object(guard, 'guard_fd', side_effect=AssertionError('must not run')):
                    self.assertFalse(guard.allowed(e, self.home))

    def test_guard_missing_link_special_and_writable_fail_closed(self):
        self.policy.unlink()
        with self.assertRaises(FileNotFoundError): guard.allowed(self.event(command='pwd'), self.home)
        other = self.home / 'other'; other.write_text('raise SystemExit(0)')
        self.policy.symlink_to(other)
        with self.assertRaises(OSError): guard.allowed(self.event(command='pwd'), self.home)
        self.policy.unlink(); os.mkfifo(self.policy)
        with self.assertRaises(ValueError): guard.allowed(self.event(command='pwd'), self.home)
        self.policy.unlink(); self.policy.write_text(''); self.policy.chmod(0o666)
        with self.assertRaises(ValueError): guard.allowed(self.event(command='pwd'), self.home)

    def test_malformed_bash_and_wrong_event_are_denied(self):
        for event in ({}, self.event(command=[]), dict(self.event(command='pwd'), hook_event_name='Stop')):
            self.assertFalse(guard.allowed(event, self.home))

    def test_main_errors_emit_structured_deny_even_on_host(self):
        for raw in ('{', '{"tool_input":NaN}', json.dumps(self.event(command='pwd'))):
            r = subprocess.run([str(SCRIPT)], input=raw, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(json.loads(r.stdout)['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertNotIn('pwd', r.stdout)

    def test_timeout_is_not_permission(self):
        with patch.object(guard.subprocess, 'run', side_effect=subprocess.TimeoutExpired('guard', 5)):
            with self.assertRaises(subprocess.TimeoutExpired): guard.allowed(self.event(command='pwd'), self.home)


if __name__ == '__main__': unittest.main()
