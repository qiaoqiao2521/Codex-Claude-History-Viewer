"""Synthetic provider records based on locally installed Gemini 0.59 and pi 0.73."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from history_core.extra_parsers import (iter_gemini_records, iter_pi_records,
    parse_extra_session_bytes, parse_gemini_session_file, parse_pi_session_file)

TS = '2026-09-22T10:00:00.000Z'


def jsonl(*rows):
    return ('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows) + '\n').encode()


def gemini_meta(**extra):
    return dict(sessionId='gemini-one', projectHash='synthetic-hash', startTime=TS, lastUpdated=TS, **extra)


def gm(mid, text='', **extra):
    return dict(id=mid, timestamp=TS, type='gemini', content=text, **extra)


def pi_header(**extra):
    return dict(type='session', version=3, id='pi-one', timestamp=TS, cwd='/synthetic/repo', **extra)


def pm(eid, parent, role, content, **extra):
    return dict(type='message', id=eid, parentId=parent, timestamp=TS,
                message=dict(role=role, content=content, timestamp=1790071200000, **extra))


class ExtraParserTests(unittest.TestCase):
    def test_gemini_legacy_json_maps_messages_tokens_and_unknown_project(self):
        data = gemini_meta(messages=[dict(id='u', type='user', timestamp=TS, content=[{'text':'修复 SQLite'}]),
            gm('a','Fixed',tokens={'input':100,'output':20,'cached':70,'thoughts':5,'total':125})])
        result = parse_extra_session_bytes(json.dumps(data).encode(), 'gemini')
        self.assertIsNone(result['cwd'])  # projectHash is not a filesystem path.
        self.assertEqual(result['title'], '修复 SQLite')
        self.assertEqual(result['message_count'], 2)
        self.assertEqual(result['usage'], {'input':100,'output':20,'cached':70,'reasoning':5,'total':125})
        refs = list(iter_gemini_records(json.dumps(data).encode()))
        self.assertEqual(refs[1]['raw_ref']['json_pointer'], '/messages/1')
        self.assertEqual(refs[1]['message']['id'], 'a')

    def test_gemini_jsonl_id_updates_dedup_text_and_tokens(self):
        raw = jsonl(gemini_meta(directories=['/synthetic/repo']),
                    gm('a','partial',tokens={'total':10}), gm('a','complete',tokens={'total':20}),
                    {'$set': {'summary':'Saved title'}})
        result = parse_extra_session_bytes(raw, 'gemini')
        self.assertEqual(result['cwd'], '/synthetic/repo')
        self.assertEqual(result['title'], 'Saved title')
        self.assertEqual(result['message_count'], 1)
        self.assertEqual(result['usage']['total'], 20)
        self.assertNotIn('partial', result['search_blob'])
        self.assertEqual(list(iter_gemini_records(raw))[0]['raw_ref']['line_no'], 3)

    def test_gemini_rewind_is_inclusive_and_reset_messages_is_authoritative(self):
        raw = jsonl(gemini_meta(), gm('a','kept',tokens={'total':1}), gm('b','removed',tokens={'total':50}),
                    gm('c','also removed',tokens={'total':99}), {'$rewindTo':'b'}, gm('d','new branch',tokens={'total':3}))
        self.assertEqual([x['message']['id'] for x in iter_gemini_records(raw)], ['a','d'])
        self.assertEqual(parse_extra_session_bytes(raw,'gemini')['usage']['total'],4)
        raw += jsonl({'$set': {'messages':[gm('fresh','replacement',tokens={'total':8})]}})
        result = parse_extra_session_bytes(raw, 'gemini')
        self.assertEqual(result['message_count'], 1)
        self.assertEqual(result['usage']['total'], 8)
        self.assertNotIn('kept', result['search_blob'])
        self.assertEqual(list(iter_gemini_records(raw))[0]['raw_ref']['json_pointer'], '/$set/messages/0')
        raw += jsonl({'$rewindTo':'not-found'})
        self.assertEqual(list(iter_gemini_records(raw)), [])

    def test_gemini_tool_calls_keep_native_fields_and_unknown_outcome(self):
        raw = jsonl(gemini_meta(), gm('a', toolCalls=[
            {'id':'call-1','name':'run_shell_command','args':{'command':'pytest'},'result':{'functionResponse':{'response':{'exitCode':7,'output':'failed'}}},'status':'error'},
            {'id':'call-2','name':'read_file','args':{'file_path':'src/a.py'},'result':'returned data'},
            {'id':'call-3','name':'read_file','args':{'file_path':'src/b.py'},'result':'Exit code: 0'}]))
        result = parse_extra_session_bytes(raw, 'gemini')
        uses = [x for x in result['messages'] if x['kind']=='tool_use']
        returns = [x for x in result['messages'] if x['kind']=='tool_result']
        self.assertEqual(uses[0]['tool_args'], {'command':'pytest'})
        self.assertEqual(returns[0]['tool_result_exit_codes'], [7])
        self.assertTrue(returns[0]['tool_result_error'])
        self.assertEqual(returns[1]['tool_result_status'], 'unknown')
        self.assertIsNone(returns[1]['tool_result_error'])
        self.assertEqual(returns[2]['tool_result_exit_codes'], [])
        self.assertEqual(returns[2]['tool_result_text'], 'Exit code: 0')

    def test_pi_all_branches_keep_each_entry_once_and_summary_is_not_usage(self):
        usage = {'input':2,'output':3,'cacheRead':5,'cacheWrite':7,'totalTokens':17}
        raw = jsonl(pi_header(), pm('u',None,'user','Start'),
                    pm('a','u','assistant',[{'type':'text','text':'failed branch'}],usage=usage),
                    pm('b','u','assistant',[{'type':'text','text':'other branch'}],usage=usage),
                    {'type':'branch_summary','id':'s','parentId':'b','timestamp':TS,'summary':'old branch summarized','tokensBefore':999},
                    {'type':'compaction','id':'c','parentId':'s','timestamp':TS,'summary':'compressed context','tokensBefore':999},
                    pm('b','u','assistant',[{'type':'text','text':'updated other branch'}],usage=usage))
        result = parse_extra_session_bytes(raw,'pi')
        self.assertEqual(result['message_count'], 3)
        self.assertEqual(result['usage'], {'input':4,'output':6,'cached':24,'reasoning':0,'total':34})
        self.assertEqual(len(list(iter_pi_records(raw))),5)
        self.assertEqual(result['search_blob'].count('updated other branch'),1)
        self.assertIn('pi entry a; parent u',result['search_blob'])
        self.assertIn('pi entry b; parent u',result['search_blob'])
        self.assertEqual(result['branch_policy'],'all_unique_persisted_entries')

    def test_pi_thinking_not_duplicated_and_images_not_dumped(self):
        raw = jsonl(pi_header(), pm('a',None,'assistant',[{'type':'text','text':'answer'},
                {'type':'thinking','thinking':'THOUGHT_ONCE','thinkingSignature':'SECRET_SIGNATURE'},
                {'type':'image','data':'BASE64_PRIVATE','mimeType':'image/png'}]))
        result = parse_extra_session_bytes(raw,'pi')
        self.assertEqual(result['search_blob'].count('THOUGHT_ONCE'),1)
        self.assertNotIn('BASE64_PRIVATE',result['search_blob'])
        self.assertNotIn('SECRET_SIGNATURE',result['search_blob'])
        self.assertEqual(result['message_count'],1)

    def test_pi_native_tool_result_failure_and_explicit_exit(self):
        raw = jsonl(pi_header(), pm('a',None,'assistant',[{'type':'toolCall','id':'t','name':'bash','arguments':{'command':'false'}}]),
                    pm('r','a','toolResult',[{'type':'text','text':'failure'}],toolCallId='t',toolName='bash',isError=True,details={'exitCode':2}),
                    pm('unknown','r','toolResult',[{'type':'text','text':'unconfirmed'}],toolCallId='u',toolName='custom'))
        result = parse_extra_session_bytes(raw,'pi')
        returns = [x for x in result['messages'] if x['kind']=='tool_result']
        self.assertEqual(returns[0]['tool_result_text'],'failure')
        self.assertEqual(returns[0]['tool_result_exit_codes'],[2])
        self.assertTrue(returns[0]['tool_result_error'])
        self.assertEqual(returns[1]['tool_result_status'],'unknown')
        self.assertIsNone(returns[1]['tool_result_error'])
        self.assertEqual(returns[0]['raw_ref']['parent_id'],'a')

    def test_pi_session_info_title_v1_and_future_version(self):
        raw = jsonl({'type':'session','id':'legacy','cwd':'/synthetic/repo','timestamp':TS},
                    {'type':'message','message':{'role':'user','content':'old prompt','timestamp':1790071200000}},
                    {'type':'session_info','name':'Named session'})
        result = parse_extra_session_bytes(raw,'pi')
        self.assertEqual(result['title'],'Named session')
        self.assertEqual(result['message_count'],1)
        with self.assertRaisesRegex(ValueError,'unsupported_pi_session_version'):
            parse_extra_session_bytes(jsonl(dict(pi_header(),version=999)),'pi')

    def test_pi_inherited_fork_does_not_double_count_copied_ancestor_usage(self):
        raw = jsonl(pi_header(parentSession='/unread/parent.jsonl'), pm('a',None,'assistant',[{'type':'text','text':'copied history'}],usage={'totalTokens':200}))
        result = parse_extra_session_bytes(raw,'pi')
        self.assertIsNone(result['usage'])
        self.assertEqual(result['usage_status'],'unknown_inherited_session')
        self.assertIn('copied history',result['search_blob'])

    def test_malformed_tail_is_bounded_warning_and_invalid_input_is_rejected(self):
        for source, header in [('pi',pi_header()),('gemini',gemini_meta())]:
            with self.subTest(source=source):
                result=parse_extra_session_bytes(jsonl(header)+b'{broken secret-body',source)
                self.assertEqual(result['malformed_line_count'],1)
                self.assertNotIn('secret-body',result['search_blob'])
                with self.assertRaises(ValueError):parse_extra_session_bytes(b'{broken',source)
                with self.assertRaises(ValueError):parse_extra_session_bytes(jsonl({'unrelated':'config'}),source)

    def test_real_path_entrypoints_are_read_only_and_missing_file_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            for source,header,parser in [('pi',pi_header(),parse_pi_session_file),('gemini',gemini_meta(),parse_gemini_session_file)]:
                path=Path(tmp)/(source+'.jsonl');raw=jsonl(header);path.write_bytes(raw)
                result=parser(path)
                self.assertEqual(result['file_path'],str(path));self.assertEqual(path.read_bytes(),raw)
                path.unlink();self.assertIsNone(parser(path))

    def test_multiple_gemini_directories_do_not_invent_single_project(self):
        raw=jsonl(gemini_meta(directories=['/synthetic/one','/synthetic/two']))
        self.assertIsNone(parse_extra_session_bytes(raw,'gemini')['cwd'])


if __name__ == '__main__':
    unittest.main()
