"""Public chat parity and durable replay of Codex's completed UI records."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import runpy
from unittest.mock import patch
from test_shared_search import B
from codex_chat import parse_chunk


def row(kind,payload):
    return (json.dumps({'type':kind,'timestamp':'2026-11-14T08:00:00Z','payload':payload})+'\n').encode()

def meta():return row('session_meta',{'id':'thread-a','history_mode':'paginated','source':'cli'})
def item(kind,identity,**kw):return row('event_msg',{'type':'item_completed','item':{'type':kind,'id':identity,**kw}})
def answer(identity,text):return item('AgentMessage',identity,content=[{'type':'Text','text':text}],phase='final_answer')
def human(identity,text):return item('UserMessage',identity,content=[{'type':'text','text':text}])


class DecoderTest(unittest.TestCase):
    def test_paginated_is_single_canonical_source(self):
        data=(meta()+human('u1','質問')+answer('a1','答え')+
              row('response_item',{'type':'message','id':'a1','role':'assistant','content':[{'type':'output_text','text':'答え'}]})+
              row('event_msg',{'type':'task_complete','last_agent_message':'答え'}))
        used,events=parse_chunk(data,{})
        self.assertEqual(used,len(data));self.assertEqual([e['text'] for e in events],['質問','答え'])
        self.assertEqual(len(set(e['codex_event_id'] for e in events)),2)

    def test_only_public_reasoning_no_instructions_tools_or_raw_reasoning(self):
        data=meta()+item('Reasoning','r1',summary_text=['public summary'],raw_content=['PRIVATE'])
        data+=row('response_item',{'type':'message','role':'developer','content':[{'type':'input_text','text':'PRIVATE'}]})
        data+=item('CommandExecution','c1',aggregated_output='PRIVATE')
        data+=item('Reasoning','r2',summary_text=[],raw_content=['PRIVATE'])
        self.assertEqual([e['text'] for e in parse_chunk(data,{})[1]],['public summary'])

    def test_partial_scalar_and_bad_json(self):
        complete=meta()+b'null\n[]\n42\nBAD\n'+answer('a','ok')
        pending=answer('b','あとで')
        state={};used,events=parse_chunk(complete+pending[:20],state)
        self.assertEqual(used,len(complete));self.assertEqual([e['text'] for e in events],['ok'])
        self.assertEqual([e['text'] for e in parse_chunk(pending,state,used)[1]],['あとで'])

    def test_legacy_uses_user_events_not_model_input(self):
        data=row('session_meta',{'id':'legacy'})
        data+=row('response_item',{'type':'message','role':'user','content':[{'type':'input_text','text':'instructions'}]})
        data+=row('event_msg',{'type':'user_message','message':'hello'})
        data+=row('response_item',{'type':'message','id':'a','role':'assistant','content':[{'type':'output_text','text':'world'}]})
        self.assertEqual([e['text'] for e in parse_chunk(data,{})[1]],['hello','world'])


class ReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sid='aabb00112233'
        self.sdir=self.root/self.sid;self.sdir.mkdir();(self.sdir/'events.jsonl').write_text('')
        self.old=B.session_roots;B.session_roots=lambda:[self.root]
        self.sources={};self.seen=set();self.users=[];self.old_assistant=[]
        self.path=self.root/'rollout-test.jsonl'
    def tearDown(self):
        B.session_roots=self.old;B._pending_user.pop(self.sid,None);self.tmp.cleanup()
    def consume(self):B._consume_codex_source(self.sid,str(self.path),self.sources,self.seen,self.users,self.old_assistant)
    def events(self):return [json.loads(l) for l in (self.sdir/'events.jsonl').read_text().splitlines()]
    def test_checkpoint_crash_and_repeated_identical_replies(self):
        self.path.write_bytes(meta()+answer('a','same')+answer('b','same'))
        self.consume();self.sources={}
        self.seen,self.users,self.old_assistant=B._codex_existing_events(self.sid)
        self.consume()
        self.assertEqual([e['text'] for e in self.events()],['same','same'])
    def test_existing_web_user_and_new_terminal_user(self):
        sent=B.append_event(self.sid,{'type':'user_message','text':'web'})
        self.seen,self.users,self.old_assistant=B._codex_existing_events(self.sid)
        self.path.write_bytes(meta()+human('u1','web')+answer('a','ok')+human('u2','terminal')+human('u3','web'))
        self.consume()
        self.assertEqual([e['text'] for e in self.events() if e['type']=='user_message'],['web','terminal','web'])
        self.sources={};self.seen,self.users,self.old_assistant=B._codex_existing_events(self.sid);self.consume()
        self.assertEqual(len([e for e in self.events() if e['type']=='user_message']),3)
    def test_relay_switch_deduplicates_direct_rollout(self):
        self.path.write_bytes(meta()+answer('a','one'));self.consume()
        ev=parse_chunk(meta()+answer('a','one')+answer('b','two'),{})[1]
        self.path=self.root/'codex-chat.jsonl';self.path.write_text(''.join(json.dumps({'type':'aiza_codex_event','event':e})+'\n' for e in ev))
        self.consume();self.assertEqual([e['text'] for e in self.events()],['one','two'])


def at(rowbytes, ts):
    rec=json.loads(rowbytes);rec['timestamp']=ts;return (json.dumps(rec)+'\n').encode()
def commentary(identity,text):return item('AgentMessage',identity,content=[{'type':'Text','text':text}],phase='commentary')
def reasoning(identity,text):return item('Reasoning',identity,summary_text=[text])


class _NowTimer:
    """threading.Timer that runs at once (the decision delay is not under test)."""
    def __init__(self,delay,fn,args=()):self.fn,self.args=fn,args
    def start(self):self.fn(*self.args)


class CodexTaskTest(ReplayTest):
    """The to-do list follows Codex's public record (the deployment notes)."""
    T0='2026-11-14T10:00:00Z'; T1='2026-11-14T10:01:00Z'; T2='2026-11-14T10:02:00Z'
    def setUp(self):
        super().setUp()
        self.pushes=[]
        self.p=[patch.object(B.threading,'Timer',_NowTimer),
                patch.object(B,'send_push_notification',lambda sid,msg:self.pushes.append(msg)),
                patch.object(B,'load_meta',lambda sid:{'id':sid})]
        for x in self.p:x.start()
    def tearDown(self):
        for x in self.p:x.stop()
        super().tearDown()
    def task(self):return B.load_task(self.sid)
    def feed(self,*rows):
        with open(self.path,'ab') as f:
            for r in rows:f.write(r)
        self.consume()
    def test_user_turn_then_final_with_status_line(self):
        B.save_task(self.sid,{'state':'done','text':'','ts':1,'seen':True})
        self.feed(meta(),at(human('u1','do it'),self.T0))
        self.assertEqual(self.task()['state'],'working')
        self.feed(at(commentary('c1','looking'),self.T1),at(reasoning('r1','hmm'),self.T1))
        self.assertEqual(self.task()['state'],'working')
        self.feed(at(answer('a1','done.\n状態: 要判断 — 見てほしい'),self.T2))
        t=self.task();self.assertEqual((t['state'],t['text'],t['declared']),('you','見てほしい',True))
    def test_event_time_not_read_time(self):
        self.feed(meta(),at(answer('a1','ok\n状態: 済み — 終わり'),self.T0))
        from codex_chat import timestamp
        self.assertEqual(self.task()['ts'],timestamp(self.T0))
        self.assertEqual(self.pushes,[])            # written long ago: no buzz
    def test_final_without_status_line_is_undeclared(self):
        self.feed(meta(),at(answer('a1','just stopped'),self.T0))
        t=self.task();self.assertEqual((t['state'],t['declared']),('you',False))
    def test_old_final_does_not_override_newer_states(self):
        from codex_chat import timestamp
        for newer in ({'state':'working','text':'','ts':timestamp(self.T2),'seen':True},
                      {'state':'you','text':'permission','ts':timestamp(self.T2),'declared':True,'prompt':True},
                      {'state':'done','text':'','ts':timestamp(self.T2),'seen':True,'by_hand':True}):
            self.path.write_bytes(b'');self.sources={};self.seen=set()
            B.save_task(self.sid,dict(newer))
            self.feed(meta(),at(answer('a1','old\n状態: 要判断 — old'),self.T0))
            self.assertEqual(self.task(),newer)
    def test_replay_of_same_final_is_not_rewritten(self):
        self.feed(meta(),at(answer('a1','x\n状態: 済み — x'),self.T0))
        B.task_update(self.sid,{'seen':True});before=self.task()
        self.sources={};self.seen=set();self.consume()
        self.assertEqual(self.task(),before)
    def test_only_newest_of_a_batch(self):
        B.save_task(self.sid,{'state':'done','text':'','ts':1,'seen':True})
        self.feed(meta(),at(answer('a1','x\n状態: 要判断 — first'),self.T0),at(human('u1','next'),self.T1))
        self.assertEqual(self.task()['state'],'working')
    def test_recent_you_pushes(self):
        import datetime
        now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        self.feed(meta(),at(answer('a1','x\n状態: 要判断 — 見て'),now))
        self.assertEqual(self.pushes,['要判断: 見て'])

    def test_stop_return_is_aiza_note_and_working(self):
        # The Stop hook's one return reaches Codex's record as a user turn; the
        # chat shows aiza's note, never the owner's words, and Codex works on.
        from codex_chat import timestamp
        self.feed(meta(),at(answer('a1','途中です'),self.T0),at(human('u1',B.CODEX_STOP_REMINDER),self.T1))
        last=self.events()[-1]
        self.assertEqual((last['type'],last['text'],last['aiza_stop_return']),('system',B.CODEX_STOP_NOTE,True))
        self.assertNotIn('user_message',[e['type'] for e in self.events()])
        self.assertEqual(self.task()['state'],'working')
        B.save_task(self.sid,None);B._codex_task_backfill(self.sid)
        self.assertEqual(self.task()['state'],'working')
        # Anything but the exact words stays a user message.
        self.feed(meta(),at(human('u2','[aigw 状態確認] 送って'),self.T2))
        self.assertEqual(self.events()[-1]['type'],'user_message')

    def test_hook_and_backend_have_the_same_words(self):
        hook=(Path(__file__).resolve().parent.parent/'bin'/'aiza-codex-hook').read_text()
        if 'STOP_REMINDER' not in hook:
            self.skipTest('the hook has no Stop return yet')
        self.assertEqual(runpy.run_path(str(Path(__file__).resolve().parent.parent/'bin'/'aiza-codex-hook'),
                                        run_name='x')['STOP_REMINDER'],B.CODEX_STOP_REMINDER)

    def test_user_turn_without_a_task_is_working(self):
        self.feed(meta(),at(human('u1','go'),self.T0))
        self.assertEqual(self.task()['state'],'working')
    def test_phase_final_counts_and_no_phase_does_not(self):
        legacy=row('response_item',{'type':'message','role':'assistant','id':'m1',
                   'content':[{'type':'output_text','text':'x\n状態: 済み — legacy'}]})
        self.path.write_bytes(row('session_meta',{'id':'thread-b'})+at(legacy,self.T0));self.consume()
        self.assertIsNone(self.task())
        final=item('AgentMessage','a9',content=[{'type':'Text','text':'x\n状態: 済み — f'}],phase='final')
        self.feed(meta(),at(final,self.T1))
        self.assertEqual(self.task()['state'],'done')
    def test_backfill_from_the_chat_keeps_newer_and_equal(self):
        from codex_chat import timestamp
        self.feed(meta(),at(answer('a1','x\n状態: 済み — f'),self.T1))
        B.save_task(self.sid,{'state':'working','text':'','ts':timestamp(self.T0),'seen':True})
        B._codex_task_backfill(self.sid)
        self.assertEqual(self.task()['state'],'done')
        B.task_update(self.sid,{'seen':True});kept=self.task()
        B._codex_task_backfill(self.sid)
        self.assertEqual(self.task(),kept)
        hand={'state':'you','text':'','ts':timestamp(self.T2),'seen':True,'by_hand':True}
        B.save_task(self.sid,dict(hand));B._codex_task_backfill(self.sid)
        self.assertEqual(self.task(),hand)
    def test_backfill_counts_a_web_sent_turn(self):
        from codex_chat import timestamp
        B.save_task(self.sid,{'state':'done','text':'','ts':1,'seen':True})
        sent=B.append_event(self.sid,{'type':'user_message','text':'web','ts':timestamp(self.T2)})
        self.seen,self.users,self.old_assistant=B._codex_existing_events(self.sid)
        self.feed(meta(),at(answer('a1','x\n状態: 済み — f'),self.T1),at(human('u1','web'),self.T2))
        B.save_task(self.sid,{'state':'done','text':'','ts':1,'seen':True})
        B._codex_task_backfill(self.sid)
        self.assertEqual(self.task()['state'],'working')

    def test_ended_session_keeps_an_equal_state(self):
        from codex_chat import timestamp
        ts=timestamp(self.T0);kept={'state':'you','text':'','ts':ts,'seen':True,'by_hand':True}
        B.save_task(self.sid,dict(kept))
        with patch.object(B,'load_meta',lambda sid:{'id':sid,'stopped':True}):
            B._task_decide_stop(self.sid,None,ts,False,True)
        self.assertEqual(self.task(),kept)

    def test_bad_times_never_set_the_state(self):
        import time as _t
        B.save_task(self.sid,{'state':'done','text':'','ts':1,'seen':True})
        before=self.task()
        bad=[_t.time()+86400*365*70,float('nan'),float('inf'),-5.0,0,10**400]
        for i,ts in enumerate(bad):
            B.task_codex_events(self.sid,[{'type':'user_message','text':'x','ts':ts},
                                         {'type':'agent_output','phase':'final_answer','text':'状態: 要判断 — x','ts':ts}])
            self.assertEqual(self.task(),before,ts)
        line=json.dumps({'type':'event_msg','timestamp':'2100-01-01T00:00:00Z','payload':{'type':'item_completed',
              'item':{'type':'UserMessage','id':'u9','content':[{'type':'text','text':'future'}]}}})+'\n'
        self.feed(meta(),line.encode())
        self.assertEqual(self.task(),before)
        self.assertIn('future',[e['text'] for e in self.events()])   # still shown in the chat
        for ts in (float('nan'),float('inf'),-1):
            B.save_task(self.sid,{'state':'you','ts':ts});self.assertEqual(self.task(),before)
    def test_final_snooze_line_sets_until(self):
        import datetime
        now=datetime.datetime.now(datetime.timezone.utc)
        when=(now+datetime.timedelta(days=2)).astimezone()
        self.feed(meta(),at(answer('a1',f'x\n状態: 寝かせ {when.month}/{when.day} 9:00 — 返事待ち'),
                          now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')))
        t=self.task()
        self.assertEqual((t['state'],t['text'],t['declared']),('snooze','返事待ち',True))
        self.assertEqual(datetime.datetime.fromtimestamp(t['until']).replace(second=0),
                         when.replace(hour=9,minute=0,second=0,microsecond=0,tzinfo=None))
        self.assertEqual(self.pushes,[])


class RelayTest(unittest.TestCase):
    def test_private_relay_and_partial_record(self):
        hook=Path(__file__).resolve().parents[1]/'bin/aiza-codex-hook'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);session=root/'session';session.mkdir()
            transcript=root/'rollout-test.jsonl';data=meta()+human('u','hi')+answer('a','hello')
            transcript.write_bytes(data+answer('b','partial')[:25])
            env=dict(os.environ,AIZA_TALKTO=str(session/'talkto_out.jsonl'))
            relay = runpy.run_path(str(hook))
            with patch.dict(os.environ, env):
                for _ in range(2): relay['sync'](str(transcript), 'thread-a')
            spool=session/'codex-chat.jsonl';rows=[json.loads(l) for l in spool.read_text().splitlines()]
            self.assertEqual([r['event']['text'] for r in rows],['hi','hello'])
            self.assertEqual(spool.stat().st_mode & 0o777,0o600)
            transcript.write_bytes(data+answer('b','partial'))
            with patch.dict(os.environ, env): relay['sync'](str(transcript), 'thread-a')
            self.assertEqual(len(spool.read_text().splitlines()),3)

if __name__=='__main__':unittest.main()
