"""Codex approval uses the existing phone protocol, never Claude-only grants."""
import contextlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from test_ask_hook import H, B, CONV, page_answer


class CodexApprovalTest(unittest.TestCase):
    def test_output_contract(self):
        for answer, expected in [
            ({'behavior':'allow','session':True}, {'behavior':'allow'}),
            ({'behavior':'deny','message':'理由'}, {'behavior':'deny','message':'理由'}),
        ]:
            self.assertEqual(H.output('codex', {}, answer), {'hookSpecificOutput': {
                'hookEventName':'PermissionRequest', 'decision':expected}})
        for answer in [None, {'terminal':True}, {'answers':{'q':'a'}}, {'behavior':'unknown'}]:
            self.assertIsNone(H.output('codex', {}, answer))

    def test_ineligible_requests_stay_native(self):
        base={'tool_name':'Bash','tool_input':{'command':'pwd'}}
        with patch.dict(os.environ, {'AIZA_TALKTO':'/tmp/unused/talkto_out.jsonl'}), patch.object(H,'wait_answer') as wait:
            with patch.object(H.os,'geteuid',return_value=1000):
                self.assertFalse(H.codex_permission(base))
            with patch.object(H.os,'geteuid',return_value=0):
                self.assertFalse(H.codex_permission(dict(base,permission_mode='bypassPermissions')))
                self.assertFalse(H.codex_permission(dict(base,tool_input={'command':'x'*401})))
                self.assertFalse(H.codex_permission(dict(base,tool_name=None)))
            wait.assert_not_called()

    def test_phone_round_trip_and_terminal(self):
        for answer in [{'behavior':'allow'}, {'behavior':'deny','message':'試験の拒否'}, {'terminal':True}]:
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as tmp:
                home=Path(tmp)/'home'; sd=home/'.aiza-state'/'sessions'/'eeeeeeeeee01'
                sd.mkdir(parents=True)
                for p in [home,home/'.aiza-state',sd.parent,sd]:p.chmod(0o700)
                sid=sd.name; talkto=sd/'talkto_out.jsonl'
                payload={'tool_name':'Bash','tool_input':{'command':'pwd'},'session_id':CONV,'cwd':'/tmp'}
                (sd/'meta.json').write_text(json.dumps({'id':sid,'preset':'root-shell','tmux_location':'root'}))
                patches=[patch.dict(os.environ,{'AIZA_TALKTO':str(talkto),'TMUX_PANE':'%99'}),
                         patch.object(H.os,'geteuid',return_value=0), patch.object(H.signal,'signal'),
                         patch.object(H,'root_window_open',return_value=True),patch.object(H,'POLL',0.01),patch.object(B,'session_dir',lambda _:sd),
                         patch.object(B,'load_meta',lambda _:{'id':sid}),patch.object(B,'send_push_notification'),
                         patch.object(B,'_ask_open',{}),patch.object(B,'set_task')]
                with contextlib.ExitStack() as stack:
                    for p in patches:stack.enter_context(p)
                    buf=io.StringIO();errors=[]
                    def worker():
                        try:
                            with contextlib.redirect_stdout(buf):H.codex_permission(payload)
                        except BaseException as exc:errors.append(exc)
                    t=threading.Thread(target=worker,daemon=True);t.start()
                    req=None;deadline=time.monotonic()+5
                    while time.monotonic()<deadline:
                        if talkto.exists():
                            lines=talkto.read_text().splitlines()
                            if lines:req=json.loads(lines[0]);break
                        time.sleep(.01)
                    self.assertIsNotNone(req)
                    self.assertFalse(req['ask']['terminal']);self.assertFalse(req['ask']['can_session'])
                    self.assertEqual(json.loads(req['ask']['summary']),{'tool':'Bash','input':{'command':'pwd'},'cwd':'/tmp'})
                    B.ask_hook(sid,str(talkto),req['id'],req['ask'])
                    page_answer(sid,{'ask_id':req['id'],'answer':answer})
                    t.join(5);self.assertFalse(t.is_alive());self.assertFalse(errors)
                    if answer.get('terminal'):self.assertEqual(buf.getvalue(),'')
                    else:self.assertEqual(json.loads(buf.getvalue())['hookSpecificOutput']['decision'],answer)
                    events=[json.loads(x) for x in (sd/'events.jsonl').read_text().splitlines()]
                    self.assertEqual([e['type'] for e in events],['ask','ask_done'])
                B._next_seq.pop(sid,None)

    def test_legacy_store_never_supplies_root_approval(self):
        talkto='/root/sandhome/.aiza/eeeeeeeeee01/talkto_out.jsonl'
        fd=os.open('/tmp',os.O_RDONLY | os.O_DIRECTORY)
        with patch.dict(os.environ,{'AIZA_TALKTO':talkto}),patch.object(H.os,'geteuid',return_value=0),patch.object(H,'open_session_dir',return_value=(fd,str(Path(talkto).parent))),patch.object(H,'wait_answer') as wait:
            self.assertFalse(H.codex_permission({'tool_name':'Bash','tool_input':{'command':'pwd'}}))
            wait.assert_not_called()

    def test_long_command_cannot_be_approved_from_a_truncated_card(self):
        talkto='/root/.aiza-state/sessions/eeeeeeeeee01/talkto_out.jsonl'
        fd=os.open('/tmp',os.O_RDONLY | os.O_DIRECTORY)
        with patch.dict(os.environ,{'AIZA_TALKTO':talkto}),patch.object(H.os,'geteuid',return_value=0),patch.object(H,'open_session_dir',return_value=(fd,str(Path(talkto).parent))),patch.object(H,'wait_answer') as wait:
            self.assertFalse(H.codex_permission({'tool_name':'Bash','tool_input':{'command':'echo '+ 'x'*401}}))
            wait.assert_not_called()

    def test_timeout_closes_card_without_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            talkto=str(Path(tmp)/'talkto_out.jsonl'); appended=[]
            with patch.object(H,'status_size',return_value=0),patch.object(H.signal,'signal'),patch.object(H._th,'append',side_effect=lambda p,e:appended.append(e)):
                ask_id,answer=H.wait_answer(talkto,{'kind':'permission'},0)
                self.assertIsNone(answer)
            self.assertEqual(appended[-1]['how'],'timeout')
            self.assertEqual(appended[-1]['ask_done'],appended[0]['id'])

    def test_invisible_controls_rejected_extra_fields_preserved(self):
        talkto='/root/.aiza-state/sessions/eeeeeeeeee01/talkto_out.jsonl'
        for command in ['pwd\rhidden','pwd\x1b[0m','pwd\u202ehidden','pwd\u200bhidden']:
            fd=os.open('/tmp',os.O_RDONLY | os.O_DIRECTORY)
            with patch.dict(os.environ,{'AIZA_TALKTO':talkto}),patch.object(H.os,'geteuid',return_value=0),patch.object(H,'open_session_dir',return_value=(fd,str(Path(talkto).parent))),patch.object(H,'wait_answer') as wait:
                self.assertFalse(H.codex_permission({'tool_name':'Bash','tool_input':{'command':command}}))
                wait.assert_not_called()
        fd=os.open('/tmp',os.O_RDONLY | os.O_DIRECTORY)
        inp={'command':'pwd','sandbox_permissions':'require_escalated','additional_permissions':{'write':['/tmp/work']}}
        with patch.dict(os.environ,{'AIZA_TALKTO':talkto}),patch.object(H.os,'geteuid',return_value=0),patch.object(H,'open_session_dir',return_value=(fd,str(Path(talkto).parent))),patch.object(H,'wait_answer',return_value=('ask-1',{'terminal':True})) as wait:
            self.assertTrue(H.codex_permission({'tool_name':'Bash','tool_input':inp}))
            summary=wait.call_args.args[1]['summary']
            self.assertTrue(summary.startswith('sandbox の外で実行\n'))
            self.assertEqual(json.loads(summary.split('\n',1)[1])['input'],inp)

    def test_root_allow_requires_live_window_for_both_agents(self):
        for mode in ['codex','perm','pre']:
            answer={'answers':{'q':'a'}} if mode=='pre' else {'behavior':'allow'}
            for unlocked in [False,True]:
                buf=io.StringIO()
                with patch.object(H.os,'geteuid',return_value=0),patch.object(H,'root_window_open',return_value=unlocked),contextlib.redirect_stdout(buf),contextlib.redirect_stderr(io.StringIO()):
                    H.emit_answer('/unused',mode,{},answer)
                self.assertEqual(bool(buf.getvalue()),unlocked)
        with patch.object(H.os,'geteuid',return_value=0),patch.object(H,'root_window_open',return_value=False),contextlib.redirect_stdout(io.StringIO()) as buf:
            H.emit_answer('/unused','codex',{}, {'behavior':'deny','message':'no'})
            self.assertEqual(json.loads(buf.getvalue())['hookSpecificOutput']['decision']['behavior'],'deny')

    def stores(self, talkto, container, euid=1001):
        fd=os.open('/tmp',os.O_RDONLY | os.O_DIRECTORY)
        return [patch.dict(os.environ,{'AIZA_TALKTO':talkto}),patch.object(H.os,'geteuid',return_value=euid),
                patch.object(H,'in_container',return_value=container),
                patch.object(H,'open_session_dir',return_value=(fd,str(Path(talkto).parent)))]

    def test_where_each_place_may_ask(self):
        """2026-11-25 (the deployment notes): host users and devboxes too, each only from
        its own tree: the host store on the host, sandhome in a container."""
        host='/home/u/.aiza-state/sessions/eeeeeeeeee01/talkto_out.jsonl'
        legacy='/home/u/sandhome/.aiza/eeeeeeeeee01/talkto_out.jsonl'
        box='/home/u/mailbox/.aiza/eeeeeeeeee01/talkto_out.jsonl'
        for talkto,container,asks in [(host,False,True),(legacy,True,True),(legacy,False,False),(host,True,False),(box,True,False)]:
            with self.subTest(talkto=talkto,container=container),contextlib.ExitStack() as stack:
                for p in self.stores(talkto,container):stack.enter_context(p)
                wait=stack.enter_context(patch.object(H,'wait_answer',return_value=('ask-1',{'terminal':True})))
                self.assertEqual(H.codex_permission({'tool_name':'Bash','tool_input':{'command':'pwd'}}),asks)
                self.assertEqual(wait.called,asks)

    def test_non_root_allow_is_checked_like_claude(self):
        payload={'tool_name':'Bash','tool_input':{'command':'pwd'}}
        allow={'behavior':'allow'}
        # The host: the host's unlock window, at the moment of answering.
        for unlocked in [False,True]:
            buf=io.StringIO()
            with patch.object(H.os,'geteuid',return_value=1001),patch.object(H,'in_container',return_value=False),\
                    patch.object(H,'root_window_open',return_value=unlocked) as win,contextlib.redirect_stdout(buf),contextlib.redirect_stderr(io.StringIO()):
                H.emit_answer('/unused','codex',payload,allow,'ask-1')
            self.assertEqual(bool(buf.getvalue()),unlocked)
            self.assertEqual(win.call_args.args[1],('host','root'))
        # A devbox: only what the backend recorded for this card, never the file's word.
        for given,out in [(None,False),({'behavior':'deny'},False),({'behavior':'allow'},True)]:
            buf=io.StringIO()
            with patch.object(H.os,'geteuid',return_value=1001),patch.object(H,'in_container',return_value=True),\
                    patch.object(H,'backend_answer',return_value=given) as rec,contextlib.redirect_stdout(buf),contextlib.redirect_stderr(io.StringIO()):
                H.emit_answer('/unused','codex',payload,allow,'ask-1',ask={'kind':'permission','summary':'pwd'})
            self.assertEqual(bool(buf.getvalue()),out)
            rec.assert_called_once_with('/unused','ask-1',H.ask_hash({'kind':'permission','summary':'pwd'}))
        # A refusal needs no check anywhere.
        for container in [False,True]:
            with patch.object(H.os,'geteuid',return_value=1001),patch.object(H,'in_container',return_value=container),\
                    patch.object(H,'root_window_open',return_value=False),patch.object(H,'backend_answer',return_value=None),contextlib.redirect_stdout(io.StringIO()) as buf:
                H.emit_answer('/unused','codex',payload,{'behavior':'deny','message':'no'},'ask-1')
                self.assertEqual(json.loads(buf.getvalue())['hookSpecificOutput']['decision']['behavior'],'deny')

    def test_wait_failure_closes_card(self):
        appended=[]
        with patch.object(H,'status_size',return_value=0),patch.object(H.signal,'signal'),patch.object(H._th,'append',side_effect=lambda p,e:appended.append(e)),patch.object(H,'read_status',side_effect=OSError('test')):
            with self.assertRaises(OSError):H.wait_answer('/unused',{'kind':'permission'},1)
        self.assertEqual(appended[-1]['ask_done'],appended[0]['id'])


class NoTimeLimitTest(unittest.TestCase):
    """No time limit on a card (2026-11-25, the user): the hook waits until
    an answer, or until Claude/Codex (the parent, or the parent's parent
    behind Claude Code's sh -c) goes away."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.talkto = str(Path(self.tmp.name) / 'talkto_out.jsonl')
        self.addCleanup(self.tmp.cleanup)

    def test_no_limit_anywhere(self):
        self.assertEqual((H.WAIT_PERM, H.WAIT_PRE, H.WAIT_CODEX), (None, None, None))

    def wait(self, ppids, grands):
        ppids, grands = iter(ppids), iter(grands)
        last = {}
        def nxt(it, key):
            last[key] = next(it, last.get(key))
            return last[key]
        with patch.object(H.os, 'getppid', side_effect=lambda: nxt(ppids, 'p')), \
             patch.object(H, '_ppid_of', side_effect=lambda pid: nxt(grands, 'g')), \
             patch.object(H, 'POLL', 0.01):
            return H.wait_answer(self.talkto, {'kind': 'permission'}, None)

    def done_lines(self):
        return [json.loads(l) for l in Path(self.talkto).read_text().splitlines() if 'ask_done' in l]

    def test_ends_when_claude_goes_away(self):
        # sh -c stays, Claude Code under it goes: the sh's parent changes.
        ask_id, answer = self.wait([100] * 1000, [50, 50, 50, 1])
        self.assertIsNone(answer)
        self.assertEqual(self.done_lines(), [{'ask_done': ask_id, 'how': 'terminal'}])

    def test_ends_when_codex_goes_away(self):
        ask_id, answer = self.wait([100, 100, 100, 1], [50] * 1000)
        self.assertIsNone(answer)
        self.assertEqual(self.done_lines(), [{'ask_done': ask_id, 'how': 'terminal'}])

    def test_waits_while_they_are_there(self):
        def answer_later():
            time.sleep(0.3)
            line = Path(self.talkto).read_text().splitlines()[0]
            ask_id = json.loads(line)['id']
            with open(Path(self.talkto).with_name('talkto_status.jsonl'), 'a') as f:
                f.write(json.dumps({'id': ask_id, 'status': 'answer', 'answer': {'behavior': 'allow'}}) + '\n')
        th = threading.Thread(target=answer_later)
        th.start()
        ask_id, answer = self.wait([100] * 100000, [50] * 100000)
        th.join()
        self.assertEqual(answer, {'behavior': 'allow'})
        self.assertEqual(self.done_lines(), [])
