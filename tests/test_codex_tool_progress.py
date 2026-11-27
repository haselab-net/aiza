"""Tool progress exports names/classified basenames, never inputs or results."""
import json
from test_codex_chat import ReplayTest, row, meta, item, answer
from test_shared_search import B
from codex_chat import parse_chunk


def call(identity, name='exec', **kw):
    return row('response_item', {'type':'custom_tool_call','call_id':identity,
                                 'name':name,'input':'PRIVATE_CODE',**kw})

def command(identity, **kw):
    return item('CommandExecution',identity,command='PRIVATE_COMMAND',
                aggregated_output='PRIVATE_RESULT',**kw)


class ToolProgressTest(ReplayTest):
    def test_calls_expose_only_name_and_are_stable_across_positions(self):
        a=parse_chunk(meta()+call('one'),{})[1][0]
        b=parse_chunk(meta()+b'null\n'+call('one'),{})[1][0]
        self.assertEqual(a['text'],'exec')
        self.assertEqual(a['codex_event_id'],b['codex_event_id'])
        self.assertNotIn('PRIVATE',json.dumps(a))
        events=parse_chunk(row('session_meta',{'id':'legacy'})+row('response_item',{'type':'function_call',
            'call_id':'two','name':'functions.exec_command','arguments':json.dumps({'cmd':'PRIVATE'})}),{})[1]
        self.assertEqual(events[0]['text'],'functions.exec_command')

    def test_classified_command_uses_only_basename(self):
        for kind,label in [('read','Read'),('list_files','List'),('search','Search')]:
            ev=parse_chunk(meta()+command('c',parsed_cmd=[{'type':kind,'path':'/private/dir/file.py',
                'cmd':'PRIVATE_COMMAND','query':'PRIVATE_QUERY','name':'PRIVATE_NAME'}]),{})[1]
            self.assertEqual(ev[0]['text'],label+': file.py')
            self.assertNotIn('PRIVATE',json.dumps(ev))
        ev=parse_chunk(meta()+command('c',parsed_cmd=[{'type':'unknown','cmd':'PRIVATE'}]),{})[1]
        self.assertEqual(ev[0]['text'],'exec_command')

    def test_controls_urls_and_long_secret_names_are_not_exposed(self):
        for path in ['/a/evil\nline','/a/evil\u202ename','/a/evil\u2028name','https://x/credential?secret=foo']:
            ev=parse_chunk(meta()+command('c',parsed_cmd=[{'type':'read','path':path}]),{})[1]
            self.assertEqual(ev[0]['text'],'Read')
        ev=parse_chunk(meta()+command('c',parsed_cmd=[{'type':'read','path':'/a/'+'k'*40}]),{})[1]
        self.assertEqual(ev[0]['text'],'Read: …')
        self.assertEqual(parse_chunk(meta()+call('c',name='x\nPRIVATE'),{})[1],[])

    def test_tool_outputs_and_arbitrary_items_are_not_exported(self):
        data=meta()+row('response_item',{'type':'function_call_output','call_id':'c','output':'PRIVATE'})
        data+=item('Extension','e',query='PRIVATE',results='PRIVATE')
        self.assertEqual(parse_chunk(data,{})[1],[])

    def test_same_call_replayed_and_relay_switch_are_deduplicated(self):
        self.path.write_bytes(meta()+call('c')+answer('a','done'))
        self.consume()
        self.sources={};self.seen,self.users,self.old_assistant=B._codex_existing_events(self.sid)
        self.consume()
        self.assertEqual(sum(e['type']=='tool' for e in self.events()),1)
        events=parse_chunk(meta()+call('c'),{})[1]
        self.path=self.root/'codex-chat.jsonl'
        self.path.write_text(''.join(json.dumps({'type':'aiza_codex_event','event':e})+'\n' for e in events))
        self.consume()
        self.assertEqual(sum(e['type']=='tool' for e in self.events()),1)

    def test_upgrade_discards_old_tools_but_keeps_new_live_tools(self):
        # Existing reply from the older decoder; tool was never shown before.
        ev=parse_chunk(meta()+answer('a','done'),{})[1][0]
        B.append_event(self.sid,ev)
        self.seen,self.users,self.old_assistant=B._codex_existing_events(self.sid)
        self.path.write_bytes(meta()+call('old')+answer('a','done'))
        self.consume()
        self.assertFalse(any(e['type']=='tool' for e in self.events()))
        rec=json.loads(call('new'));rec['timestamp']='2026-11-14T08:00:01Z'
        with self.path.open('a') as f:f.write(json.dumps(rec)+'\n')
        self.consume()
        self.assertEqual([e['codex_event_id'] for e in self.events() if e['type']=='tool'],['thread-a:tool-call:new'])

    def test_floor_survives_chunks_and_old_tools_without_timestamp(self):
        ev=parse_chunk(meta()+answer('a','done'),{})[1][0];B.append_event(self.sid,ev)
        self.path.write_bytes(meta()+call('old'))
        self.consume()
        rec=json.loads(call('old-2'));rec.pop('timestamp')
        with self.path.open('a') as f:f.write(json.dumps(rec)+'\n')
        self.consume()
        self.assertFalse(any(e['type']=='tool' for e in self.events()))

    def test_native_shell_is_canonical_completed_item(self):
        raw=row('response_item',{'type':'function_call','call_id':'c',
            'name':'exec_command','arguments':'PRIVATE'})
        ui=command('c',parsed_cmd=[{'type':'read','path':'/a/example.py'}])
        events=parse_chunk(meta()+raw+ui,{})[1]
        self.assertEqual([e['text'] for e in events],['Read: example.py'])

    def test_floor_persists_validated_state_and_huge_value_is_safe(self):
        self.path.write_bytes(meta()+call('a'));self.consume()
        entry=self.sources[str(self.path)]
        entry['tool_floor']=123
        state=B._valid_codex_state({'version':2,'sources':self.sources})
        self.assertEqual(state['sources'][str(self.path)]['tool_floor'],123)
        entry['tool_floor']=10**400
        self.consume()  # malformed persisted state never crashes the reader
