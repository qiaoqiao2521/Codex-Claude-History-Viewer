import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

from app import Handler
from audit.briefing import build_briefing_llm_messages
from history_core.sources import Indexer
from history_core.web_briefing import build_window_briefing


class WebBriefingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); src = root / 'sessions'; src.mkdir()
        cache = root / 'cache'; cache.mkdir()
        records = [('2026-09-26T12:00:00Z','OUTSIDE TITLE'),
                   ('2026-09-26T16:00:00Z','START INCLUDED'),
                   ('2026-09-27T15:59:59.500Z','END INCLUDED'),
                   ('2026-09-27T16:00:00Z','TOMORROW EXCLUDED')]
        rows = [dict(type='session_meta',payload=dict(id='old',cwd='/p'),timestamp=records[0][0])]
        rows += [dict(type='response_item',timestamp=t,payload=dict(type='message',role='user',content=[dict(type='input_text',text=v)])) for t,v in records]
        (src/'old.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
        self.idx=Indexer(src,cache,'codex');self.addCleanup(self.idx.conn.close);self.idx.scan_sessions()
        self.backend=SimpleNamespace(indexer=self.idx,source='codex',system='linux')
        self.handler=object.__new__(Handler)
        self.handler.send_json=lambda data,status=200:(status,data)
        self.handler._audit_llm_configured=lambda:False
        self.handler._audit_llm_config=lambda:None

    def test_get_post_use_identical_window_and_do_not_read_whole_audits(self):
        with patch.object(self.idx,'build_session_audit',side_effect=AssertionError('whole audit forbidden')):
            code,get=self.handler.handle_briefing_get(urlparse('/briefing?date=2026-09-27&timezone=Asia%2FShanghai'),self.backend)
            status,post=self.handler.handle_briefing_generate(dict(date='2026-09-27',timezone='Asia/Shanghai',mode='heuristic'),self.backend)
        self.assertEqual((code,status),(200,200));self.assertEqual(get['briefing'],post['briefing'])
        report=get['briefing'];self.assertEqual(report['overview']['session_count'],1)
        self.assertEqual(report['overview']['message_count'],2)
        ev=report['items'][0]['evidence'];self.assertEqual([e['message_index'] for e in ev],[1,2])
        self.assertEqual([e['text'] for e in ev],['START INCLUDED','END INCLUDED'])
        self.assertEqual([e['timestamp_local'] for e in ev],['2026-09-27T00:00:00.000+08:00','2026-09-27T23:59:59.500+08:00'])
        self.assertIn('2026-09-27T23:59:59.500+08:00',get['markdown'])
        self.assertEqual(report['window']['end_local'],'2026-09-28T00:00:00.000+08:00')
        self.assertNotIn('OUTSIDE TITLE',json.dumps(get));self.assertNotIn('TOMORROW EXCLUDED',json.dumps(post))
        self.assertNotIn('tokens_total',report['overview'])
        self.assertNotIn('finished cleanly',post['narrative']['narrative'])

    def test_timezone_changes_window_not_host_environment(self):
        utc=build_window_briefing(self.backend,'2026-09-27','UTC')
        self.assertEqual([e['text'] for e in utc['items'][0]['evidence']],['END INCLUDED','TOMORROW EXCLUDED'])
        dst=build_window_briefing(self.backend,'2026-03-08','America/New_York')
        self.assertEqual(dst['window']['end_ms']-dst['window']['start_ms'],23*3600000)

    def test_invalid_date_timezone_and_project_filter(self):
        for query in ('date=2026-02-30&timezone=UTC','date=2026-09-27&timezone=Invalid/Zone'):
            status,data=self.handler.handle_briefing_get(urlparse('/briefing?'+query),self.backend)
            self.assertEqual(status,400)
        report=build_window_briefing(self.backend,'2026-09-27','UTC',project='/other')
        self.assertEqual(report['items'],[]);self.assertTrue(report['partial'])

    def test_unavailable_unsupported_and_missing_times_are_not_complete_empty(self):
        for source,error,reason in [('opencode',None,'unsupported'),('codex','refresh failed','source_unavailable')]:
            backend=SimpleNamespace(source=source,indexer=self.idx,last_refresh_error=error)
            result=build_window_briefing(backend,'2026-09-27','UTC')
            self.assertEqual(result['coverage']['reason'],reason);self.assertTrue(result['partial'])
        with self.idx.conn:
            self.idx.conn.execute("UPDATE messages SET activity_ts_ms=NULL WHERE text='END INCLUDED'")
        result=build_window_briefing(self.backend,'2026-09-27','UTC')
        self.assertEqual(result['coverage']['messages_without_verified_time'],1)

    def test_revision_change_rejects_whole_result(self):
        with patch('history_core.web_briefing.index_revision',side_effect=['before','after']):
            with self.assertRaisesRegex(ValueError,'revision'):
                build_window_briefing(self.backend,'2026-09-27','UTC')

    def test_llm_payload_does_not_send_public_transcript_excerpts(self):
        report=build_window_briefing(self.backend,'2026-09-27','UTC')
        payload=json.dumps(build_briefing_llm_messages(report))
        self.assertNotIn('END INCLUDED',payload);self.assertNotIn('TOMORROW EXCLUDED',payload)
        self.assertIn('message_count',payload)

    def test_query_failure_and_revision_change_are_not_empty_successes(self):
        import sqlite3
        for exception, expected in [(sqlite3.OperationalError('budget'),503), (ValueError('index_revision_changed'),409)]:
            with patch('history_core.web_briefing.build_window_briefing',side_effect=exception):
                status, data=self.handler.handle_briefing_get(urlparse('/briefing?date=2026-09-27'),self.backend)
                self.assertEqual(status,expected);self.assertNotIn('briefing',data)
                status, data=self.handler.handle_briefing_generate(dict(date='2026-09-27'),self.backend)
                self.assertEqual(status,expected);self.assertNotIn('briefing',data)
