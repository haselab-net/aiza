"""Boundary and recovery regressions for the local Codex relay."""
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

HOOK = Path(__file__).resolve().parents[1] / 'bin/aiza-codex-hook'
H = runpy.run_path(str(HOOK))
from aiza_session_io import open_directory, open_private, open_talkto


def rollout(source='cli'):
    return (json.dumps({'type':'session_meta', 'payload':{'id':'test', 'source':source, 'history_mode':'paginated'}})+'\n'+
            json.dumps({'type':'event_msg', 'payload':{'type':'item_completed', 'item':{'type':'AgentMessage', 'id':'a', 'content':[{'type':'Text', 'text':'public'}]}}})+'\n')


class HookSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'home').mkdir(mode=0o755)
        self.session = self.root / 'session'; self.session.mkdir()
        self.path = self.root / 'rollout-test.jsonl'; self.path.write_text(rollout())
        self.env = patch.dict(os.environ, AIZA_TALKTO=str(self.session / 'talkto_out.jsonl'))
        self.env.start()
    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()
    def test_all_hook_outputs_follow_migration(self):
        old=self.root/'home/sandhome/.aiza/012345abcdef'
        new=self.root/'home/.aiza-state/sessions/012345abcdef'
        old.mkdir(parents=True);new.mkdir(parents=True,mode=0o700)
        new.parent.chmod(0o700);new.parent.parent.chmod(0o755)
        with patch.dict(os.environ,AIZA_TALKTO=str(old/'talkto_out.jsonl')):
            H['sync'](str(self.path),'test')
            H['set_active']('test',True,123,456)
            H['append_task']({'hook_event_name':'Stop'})
            H['log_failure']('ValueError')
        self.assertEqual(list(old.iterdir()),[])
        self.assertEqual({p.name for p in new.iterdir()}, {'codex-chat.jsonl','codex-relay-state.json','codex-active.json','talkto_out.jsonl','codex-relay-errors.jsonl'})
    def test_untrusted_host_store_does_not_fall_back(self):
        from aiza_session_path import open_session_dir
        old=self.root/'home/sandhome/.aiza/012345abcdef'
        new=self.root/'home/.aiza-state/sessions/012345abcdef'
        old.mkdir(parents=True);new.mkdir(parents=True,mode=0o700)
        new.parent.chmod(0o700);new.parent.parent.chmod(0o755)
        (self.root/'home').chmod(0o777)
        with self.assertRaises(PermissionError): open_session_dir(str(old/'talkto_out.jsonl'))
    def test_resolver_rejects_relative_and_parent_paths(self):
        from aiza_session_path import open_session_dir
        for path in ('relative/talkto_out.jsonl','/tmp/../talkto_out.jsonl'):
            with self.assertRaises(ValueError):open_session_dir(path)

    def test_missing_host_session_never_falls_back(self):
        import aiza_session_path as sp
        old=self.root/'home/sandhome/.aiza/012345abcdef'
        new=self.root/'home/.aiza-state/sessions/012345abcdef'
        old.mkdir(parents=True);new.parent.mkdir(parents=True)
        new.parent.chmod(0o700);new.parent.parent.chmod(0o755)
        for target in (old, new):
            with self.assertRaises(FileNotFoundError): sp.open_session_dir(str(target/'talkto_out.jsonl'))
        # A persistent marker closes fallback even if the entire state is removed.
        marker=self.root/'home'/sp.SESSION_STORE_MARKER
        marker.write_text('1\n');marker.chmod(0o600)
        new.parent.rmdir();new.parent.parent.rmdir()
        for target in (old,new):
            with self.assertRaises(FileNotFoundError):sp.open_session_dir(str(target/'talkto_out.jsonl'))
        self.assertEqual(list(old.iterdir()),[])

    def test_legacy_user_without_marker_or_store_keeps_working(self):
        import aiza_session_path as sp
        old=self.root/'home/sandhome/.aiza/012345abcdef';old.mkdir(parents=True)
        # The old backend already used .aiza-state for unrelated state.
        (self.root/'home/.aiza-state').mkdir(mode=0o755)
        fd,path=sp.open_session_dir(str(old/'talkto_out.jsonl'));os.close(fd)
        self.assertEqual(path,str(old))
    def test_marker_link_or_other_owner_fails_closed(self):
        import aiza_session_path as sp
        from types import SimpleNamespace
        old=self.root/'home/sandhome/.aiza/012345abcdef';old.mkdir(parents=True)
        marker=self.root/'home'/sp.SESSION_STORE_MARKER
        marker.symlink_to(self.root/'missing')
        with self.assertRaises(OSError):sp.open_session_dir(str(old/'talkto_out.jsonl'))
        marker.unlink();marker.write_text('1\n')
        real_fstat=os.fstat; marker_ino=marker.stat().st_ino
        def info(fd):
            st=real_fstat(fd)
            if st.st_ino==marker_ino:
                return SimpleNamespace(st_mode=st.st_mode,st_nlink=1,st_uid=987654)
            return st
        with patch('os.fstat',side_effect=info):
            with self.assertRaises(PermissionError):sp.open_session_dir(str(old/'talkto_out.jsonl'))

    def test_parent_symlink_refused(self):
        (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): open_directory(self.root / 'alias' / 'session')
    def test_hardlink_not_truncated_or_chmodded(self):
        target=self.root/'target';target.write_text('intact');target.chmod(0o640)
        os.link(target, self.session/'codex-active.json')
        dfd=open_directory(self.session)
        try:
            with self.assertRaises(ValueError):
                open_private(dfd, 'codex-active.json', os.O_WRONLY|os.O_CREAT|os.O_TRUNC)
        finally: os.close(dfd)
        self.assertEqual(target.read_text(),'intact');self.assertEqual(target.stat().st_mode&0o777,0o640)
    def test_symlink_not_truncated(self):
        target=self.root/'target';target.write_text('intact')
        (self.session/'codex-active.json').symlink_to(target)
        dfd=open_directory(self.session)
        try:
            with self.assertRaises(OSError):
                open_private(dfd, 'codex-active.json', os.O_WRONLY|os.O_CREAT|os.O_TRUNC)
        finally:os.close(dfd)
        self.assertEqual(target.read_text(),'intact')
    def test_fifo_refused_without_blocking(self):
        os.mkfifo(self.session/'codex-relay-state.json')
        with self.assertRaises(ValueError):H['sync'](str(self.path),'test')
    def test_exec_subagent_and_unknown_sources_not_relayed(self):
        for source in ('exec', {'subagent':{}}, None, 'unknown', 'vscode'):
            self.path.write_text(rollout(source))
            self.assertFalse(H['sync'](str(self.path),'test'))
        self.assertEqual(list(self.session.iterdir()),[])
    def test_corrupted_state_recovers(self):
        state=self.session/'codex-relay-state.json'
        for invalid in ([], {'test':{'offset':'bad','parser':{}}}, {'test':{'offset':-1,'parser':{}}},
                        {'test':{'offset':1,'parser':[]}}, {'test':{'offset':1,'parser':{'paginated':'bad'}}}):
            state.write_text(json.dumps(invalid))
            H['sync'](str(self.path),'test')
            valid=json.loads(state.read_text())['test']
            self.assertEqual(valid['offset'],self.path.stat().st_size)
        # Recovery replays stable IDs so the backend can deduplicate.
        rows=[json.loads(line) for line in (self.session/'codex-chat.jsonl').read_text().splitlines()]
        self.assertEqual({r['event']['codex_event_id'] for r in rows},{'test:a'})
    def test_idle_sync_does_not_rewrite_checkpoint(self):
        H['sync'](str(self.path),'test')
        state=self.session/'codex-relay-state.json'; before=state.stat().st_mtime_ns
        H['sync'](str(self.path),'test')
        self.assertEqual(state.stat().st_mtime_ns,before)
    def test_new_task_has_session_owner_and_private_mode(self):
        H['append_task']({'hook_event_name':'Stop'})
        target=self.session/'talkto_out.jsonl'
        self.assertEqual(target.stat().st_uid,self.session.stat().st_uid)
        self.assertEqual(target.stat().st_mode&0o777,0o600)
    def test_legacy_root_talkto_preserves_mode_and_owner(self):
        from types import SimpleNamespace
        target=self.session/'talkto_out.jsonl';target.write_text('before\n');target.chmod(0o644)
        dfd=open_directory(self.session)
        real_fstat=os.fstat
        def info(fd):
            st=real_fstat(fd)
            return SimpleNamespace(st_uid=1234 if fd==dfd else 0, st_gid=1234, st_mode=st.st_mode, st_nlink=st.st_nlink)
        try:
            with patch('os.fstat',side_effect=info), patch('os.fchmod') as chmod, patch('os.fchown') as chown:
                fd=open_talkto(dfd,os.O_WRONLY|os.O_APPEND|os.O_CREAT)
                with os.fdopen(fd,'a') as f: f.write('after\n')
                chmod.assert_not_called();chown.assert_not_called()
        finally:os.close(dfd)
        self.assertEqual(target.read_text(),'before\nafter\n')
        self.assertEqual(target.stat().st_mode&0o777,0o644)
    def test_talkto_cli_refuses_link(self):
        import subprocess
        target=self.root/'target';target.write_text('intact')
        (self.session/'talkto_out.jsonl').symlink_to(target)
        result=subprocess.run([sys.executable,str(HOOK.with_name('talkto')),'--no-wait','hello'],capture_output=True,text=True)
        self.assertEqual(result.returncode,1);self.assertEqual(target.read_text(),'intact')

    def test_pid_reuse_is_not_same_process(self):
        fn=H['same_process']
        with patch.dict(fn.__globals__,process_info=lambda pid:{'starttime':20}):
            self.assertFalse(fn(12,10));self.assertTrue(fn(12,20))
    def test_nonforeground_codex_is_not_registered(self):
        fn=H['codex_parent']
        for tty,pgrp,tpgid in ((0,1,1),(100,2,1)):
            info={'name':'codex','ppid':1,'tty':tty,'pgrp':pgrp,'tpgid':tpgid,'starttime':10}
            with patch.dict(fn.__globals__,process_info=lambda pid:info): self.assertIsNone(fn())
        info={'name':'codex','ppid':1,'tty':100,'pgrp':1,'tpgid':1,'starttime':10}
        with patch.dict(fn.__globals__,process_info=lambda pid:info, pane_foreground=lambda pid,info:True): self.assertEqual(fn(),(os.getppid(),10))
    def test_foreground_on_another_pty_is_rejected(self):
        from types import SimpleNamespace
        fn=H['pane_foreground']
        info={'tty':100,'pgrp':1,'tpgid':1}
        a=SimpleNamespace(st_mode=0o020600,st_rdev=1)
        b=SimpleNamespace(st_mode=0o020600,st_rdev=2)
        with patch.dict(os.environ,TMUX_PANE='%1'), patch('subprocess.run',return_value=SimpleNamespace(stdout='/dev/pts/1')), patch('os.stat',side_effect=[a,b]):
            self.assertFalse(fn(2,info))

    def test_mailbox_launcher_binding_and_terminal(self):
        from types import SimpleNamespace
        fn=H['pane_foreground']
        info={'tty':100,'pgrp':1,'tpgid':1,'starttime':10}
        device=SimpleNamespace(st_mode=0o020600,st_rdev=100)
        with patch.dict(fn.__globals__,mailbox_session=lambda:True), patch.dict(os.environ,AIZA_CODEX_MAILBOX_PROCESS='2:10:100',TMUX_PANE=''), patch('os.stat',return_value=device):
            self.assertTrue(fn(2,info))
            self.assertFalse(fn(3,info))  # nested interactive Codex
            self.assertFalse(fn(2,dict(info,starttime=11)))  # PID reuse
            self.assertFalse(fn(2,dict(info,tpgid=2)))
            self.assertFalse(fn(2,dict(info,tty=0)))
            self.assertFalse(fn(2,dict(info,tty=101)))
        with patch.dict(fn.__globals__,mailbox_session=lambda:True), patch.dict(os.environ,AIZA_CODEX_MAILBOX_PROCESS='broken'):
            self.assertFalse(fn(2,info))

    def test_mailbox_binding_cannot_replace_host_tmux_check(self):
        fn=H['pane_foreground']
        info={'tty':100,'pgrp':1,'tpgid':1,'starttime':10}
        with patch.dict(fn.__globals__,mailbox_session=lambda:False), patch.dict(os.environ,AIZA_CODEX_MAILBOX_PROCESS='2:10:100',TMUX_PANE=''):
            self.assertFalse(fn(2,info))
    def test_mailbox_binding_only_in_own_container_tree(self):
        from types import SimpleNamespace
        fn=H['mailbox_session']
        with patch('os.geteuid',return_value=1001), patch('pwd.getpwuid',return_value=SimpleNamespace(pw_dir='/home/test')), patch('pathlib.Path.exists',return_value=True), patch.dict(os.environ,HOME='/home/test/mailbox',AIZA_TALKTO='/home/test/mailbox/.aiza/012345abcdef/talkto_out.jsonl'):
            self.assertTrue(fn())
            with patch.dict(os.environ,AIZA_TALKTO='/home/test/sandhome/.aiza/012345abcdef/talkto_out.jsonl'): self.assertFalse(fn())
            with patch('os.geteuid',return_value=0): self.assertFalse(fn())
            with patch('pathlib.Path.exists',return_value=False): self.assertFalse(fn())

    def test_no_parent_no_events_even_with_cli_metadata(self):
        fn=H['main']; payload={'hook_event_name':'SessionStart','transcript_path':str(self.path),'session_id':'test'}
        with patch.dict(fn.__globals__,codex_parent=lambda:None), patch('sys.argv',['hook']), patch('sys.stdin',io.StringIO(json.dumps(payload))): fn()
        self.assertEqual(list(self.session.iterdir()),[])
    def stop_payload(self, **updates):
        return dict({'hook_event_name':'Stop','stop_hook_active':False,'session_id':'s1','turn_id':'t1','last_assistant_message':'確認します。'},**updates)
    def test_stop_reminder_is_once_per_turn(self):
        p=self.stop_payload()
        out=H['stop_reminder'](p)
        self.assertEqual(out['decision'],'block')
        self.assertNotIn(p['last_assistant_message'],out['reason'])
        self.assertIsNone(H['stop_reminder'](p))
        self.assertIsNone(H['stop_reminder'](self.stop_payload(turn_id='t2',stop_hook_active=True)))
        self.assertIsNotNone(H['stop_reminder'](self.stop_payload(turn_id='t2')))
    def test_stop_reminder_respects_declared_handoffs(self):
        for line in ('状態: 済み — 確認済み','**状態： 要判断 — 選択**','> 状態: 寝かせ 11/20 — 反映待ち'):
            self.assertIsNone(H['stop_reminder'](self.stop_payload(last_assistant_message='本文\n'+line)))
        self.assertFalse((self.session/'codex-stop-reminders.json').exists())
    def test_stop_reminder_does_not_restart_other_events_or_unknown_inputs(self):
        for update in ({'hook_event_name':'PermissionRequest'},{'hook_event_name':'Interrupt'},{'stop_hook_active':None},{'stop_hook_active':0},{'last_assistant_message':None},{'last_assistant_message':''},{'turn_id':None},{'turn_id':'../bad'}):
            self.assertIsNone(H['stop_reminder'](self.stop_payload(**update)))
    def test_stop_reminder_does_not_override_user_or_gate_wait(self):
        task=self.session/'task.json'
        for data in ({'prompt':True,'state':'you'},{'state':'you'},{'state':'snooze'},[],None):
            task.write_text(json.dumps(data))
            self.assertIsNone(H['stop_reminder'](self.stop_payload()))
        for data in ('broken','x'*16385):
            task.write_text(data)
            self.assertIsNone(H['stop_reminder'](self.stop_payload()))
        task.unlink();task.symlink_to(self.path)
        self.assertIsNone(H['stop_reminder'](self.stop_payload()))
    def test_stop_reminder_corrupt_checkpoint_never_continues(self):
        p=self.session/'codex-stop-reminders.json'
        for data in ('broken','{}','[1]','x'*32769):
            p.write_text(data)
            self.assertIsNone(H['stop_reminder'](self.stop_payload()))
    def test_stop_reminder_checkpoint_is_bounded(self):
        p=self.session/'codex-stop-reminders.json'
        p.write_text(json.dumps(['s:t'+str(i) for i in range(128)]))
        self.assertIsNotNone(H['stop_reminder'](self.stop_payload()))
        self.assertEqual(len(json.loads(p.read_text())),128)
    def test_main_continuation_does_not_publish_stop_task(self):
        fn=H['main'];p=self.stop_payload(transcript_path=str(self.path));out=io.StringIO()
        with patch.dict(fn.__globals__,codex_parent=lambda:(1,2),sync=lambda *a:True), patch('sys.argv',['hook']), patch('sys.stdin',io.StringIO(json.dumps(p))), patch('sys.stdout',out):fn()
        self.assertEqual(json.loads(out.getvalue())['decision'],'block')
        self.assertFalse((self.session/'talkto_out.jsonl').exists())

    def test_safe_error_log_does_not_include_payload(self):
        H['log_failure']('ValueError')
        row=json.loads((self.session/'codex-relay-errors.jsonl').read_text())
        self.assertEqual(set(row),{'ts','error'});self.assertEqual(row['error'],'ValueError')


if __name__=='__main__':unittest.main()
