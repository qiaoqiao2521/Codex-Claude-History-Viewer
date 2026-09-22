"""ZCode's native schema, ordering and HTTP evidence contract (synthetic only)."""
import hashlib
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import Handler
from audit import AUDIT_VERSION
from history_core import reuse, service
from history_core.evidence import source_store_id
from history_core.zcode import ZCodeIndexer


# Real ZCode has no project table and no session-level agent/model/token fields.
SCHEMA = '''
CREATE TABLE session (
 id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, slug TEXT, directory TEXT,
 title TEXT, version TEXT, share_url TEXT, summary_additions INTEGER,
 summary_deletions INTEGER, summary_files INTEGER, summary_diffs TEXT,
 time_created INTEGER, time_updated INTEGER
);
CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
 time_updated INTEGER, data TEXT, sequence INTEGER);
CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
 time_created INTEGER, time_updated INTEGER, data TEXT, sequence INTEGER);
'''
TS = 1788220800000


class ZCodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'native.sqlite'
        with sqlite3.connect(self.path) as conn:
            conn.executescript(SCHEMA)
            conn.executemany('INSERT INTO session (id, directory, title, time_created, time_updated) VALUES (?, ?, ?, ?, ?)', [
                ('shared-id', '/synthetic/zcode', 'ZCODE_TITLE_ONLY', TS, TS + 5000),
                ('model-lower', '/synthetic/other', '', TS + 1, TS + 6000),
                ('empty', '/synthetic/empty', 'Empty native session', TS + 2, TS + 7000)])
            messages = [
                ('user', 'shared-id', 900, 0, {'role': 'user', 'tokens': {'input': 999999}}),
                ('assistant-first', 'shared-id', 500, 1, {'role': 'assistant', 'agent': 'build', 'modelID': 'model-upper', 'cost': .1,
                    'tokens': {'input': 100, 'output': 10, 'reasoning': 3, 'cache': {'read': 80, 'write': 5}}}),
                ('assistant-last', 'shared-id', 100, 2, {'role': 'assistant', 'agent': 'review', 'modelID': 'model-last', 'cost': .2,
                    'tokens': {'input': 200, 'output': 20, 'reasoning': 7, 'cache': {'read': 150, 'write': 0}}}),
                ('lower', 'model-lower', 700, 0, {'role': 'assistant', 'agent': 'plan', 'modelId': 'model-lower-case',
                    'tokens': {'input': 50, 'output': 5, 'cache': {'read': 40}}})]
            conn.executemany('INSERT INTO message VALUES (?, ?, ?, ?, ?, ?)', [
                (mid, sid, TS + time, TS + time, json.dumps(data), seq) for mid, sid, time, seq, data in reversed(messages)])
            parts = [
                ('u', 'user', 'shared-id', 900, 0, {'type': 'text', 'text': 'ZCODE_USER_FIRST'}),
                ('reason', 'assistant-first', 'shared-id', 800, 0, {'type': 'reasoning', 'text': 'ZCODE_REASON_SECOND'}),
                ('answer', 'assistant-first', 'shared-id', 300, 1, {'type': 'text', 'text': 'ZCODE_BODY_THIRD'}),
                ('timeline', 'assistant-first', 'shared-id', 100, 2, {'type': 'timeline', 'text': 'ZCODE_TIMELINE_ONLY', 'timelineType': 'model-switch'}),
                ('step', 'assistant-first', 'shared-id', 100, 3, {'type': 'step-finish', 'tokens': {'input': 999999, 'output': 999999}}),
                ('failure', 'assistant-last', 'shared-id', 100, 0, {'type': 'tool', 'tool': 'bash', 'state': {
                    'status': 'error', 'input': {'command': 'python3 -m unittest'}, 'error': 'ZCODE_FAILURE_DETAIL', 'metadata': {'exit': 2}}}),
                ('lower-text', 'lower', 'model-lower', 700, 0, {'type': 'text', 'text': 'MODEL_LOWER_TEXT'})]
            conn.executemany('INSERT INTO part VALUES (?, ?, ?, ?, ?, ?, ?)', [
                (pid, mid, sid, TS + time, TS + time, json.dumps(data), seq) for pid, mid, sid, time, seq, data in reversed(parts)])
        self.original_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.idx = ZCodeIndexer(self.path)
        self.addCleanup(self.idx.conn.close)

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.original_hash)
        for suffix in ('-journal', '-wal', '-shm'):
            self.assertFalse(Path(str(self.path) + suffix).exists())

    def test_minimal_schema_projection_and_model_casing(self):
        self.assertEqual(self.idx.source, 'zcode')
        self.assertEqual(self.idx.build_session_audit('shared-id')['model'], 'model-last')
        self.assertEqual(self.idx.build_session_audit('model-lower')['model'], 'model-lower-case')
        self.assertEqual(self.idx.list_sessions_page()['items'][0]['id'], 'empty')
        row = self.idx.conn.execute("SELECT * FROM session WHERE id='shared-id'").fetchone()
        self.assertEqual(row['agent'], 'review')
        self.assertAlmostEqual(row['cost'], .3)
        self.assertEqual(len(self.idx.list_projects_page()['items']), 3)
        self.assertEqual(self.idx.get_session_messages_page('empty')['messages'], [])
        self.assertIsNone(self.idx.get_session_metadata('not-present'))

    def test_sequence_wins_over_reverse_timestamps_and_ignored_timeline(self):
        messages = self.idx.get_session_messages_page('shared-id')['messages']
        self.assertEqual(len(messages), 4)
        self.assertEqual([m['text'] for m in messages[:3]], [
            'ZCODE_USER_FIRST', 'ZCODE_REASON_SECOND', 'ZCODE_BODY_THIRD'])
        self.assertEqual([m['message_index'] for m in messages], list(range(4)))
        self.assertEqual(messages[3]['kind'], 'tool_result')
        self.assertNotIn('ZCODE_TIMELINE_ONLY', json.dumps(messages))
        events = self.idx._load_audit_events('shared-id')
        self.assertEqual([e.message_index for e in events], [0, 1, 2, 3, 3])
        self.assertEqual(events[-1].tool_result_exit_codes, [2])
        self.assertTrue(events[-1].tool_result_error)
        self.assertEqual(events[-1].tool_result_text, 'ZCODE_FAILURE_DETAIL')

    def test_failed_tool_display_and_audit_preserve_failure(self):
        message = self.idx.get_session_message('shared-id', 3)
        self.assertIn('ZCODE_FAILURE_DETAIL', message['text'])
        audit = self.idx.build_session_audit('shared-id')
        self.assertEqual(audit['source'], 'zcode')
        self.assertEqual(audit['commands'][0]['status'], 'fail')
        self.assertEqual(audit['commands'][0]['exit_code'], 2)
        self.assertEqual(audit['outcome_signal'], 'incomplete')
        self.assertIn('ZCODE_FAILURE_DETAIL', json.dumps(audit))

    def test_native_cache_rejects_old_audit_version_without_source_change(self):
        audit = self.idx.build_session_audit('shared-id')
        cache_key, _ = self.idx._audit_cache['shared-id']
        self.idx._audit_cache['shared-id'] = ((cache_key[0], 3), {**audit, 'outcome_signal': 'completed'})
        fresh = self.idx.build_session_audit('shared-id')
        self.assertEqual(fresh['outcome_signal'], 'incomplete')
        self.assertEqual(fresh['errors'], audit['errors'])
        self.assertEqual(self.idx._audit_cache['shared-id'][0][1], AUDIT_VERSION)

    def test_usage_aggregates_assistant_envelopes_once_without_cache_or_parts(self):
        usage = self.idx.query_usage()
        self.assertTrue(usage['has_usage_data'])
        self.assertEqual(usage['totals'], {'session_count': 3, 'input': 350, 'output': 35,
            'cached': 275, 'reasoning': 10, 'total': 385})
        self.assertEqual(usage['top_sessions'][0]['tokens_total'], 330)
        self.assertEqual(self.idx.query_usage(cwd='/synthetic/zcode')['totals']['total'], 330)
        self.assertEqual(self.idx.query_usage(start_ms=TS + 1)['totals']['total'], 55)
        self.assertEqual(self.idx.query_usage(cwd='/synthetic/empty')['has_usage_data'], False)
        indexed = {x['id']: x for x in self.idx.list_sessions_page()['items']}
        self.assertEqual(indexed['shared-id']['tokens_total'], 330)

    def test_reuse_native_snippet_indices_identity_and_handoff(self):
        store = source_store_id('linux', 'zcode', self.idx)
        for query, expected in [('ZCODE_USER_FIRST', 0), ('ZCODE_REASON_SECOND', 1), ('ZCODE_BODY_THIRD', 2), ('ZCODE_FAILURE_DETAIL', 3)]:
            with self.subTest(query=query):
                result = reuse.search([('linux', 'zcode', self.idx)], query=query)
                self.assertEqual(result['errors'], [])
                self.assertFalse(result['partial'])
                item = result['items'][0]
                self.assertEqual((item['system'], item['source'], item['store_id'], item['id']),
                    ('linux', 'zcode', store, 'shared-id'))
                self.assertEqual(item['snippet_status'], 'matched')
                self.assertEqual(item['snippets'][0]['message_index'], expected)
                self.assertIn(query, self.idx.get_session_message(item['id'], expected)['text'])
        title = reuse.search([('linux', 'zcode', self.idx)], query='ZCODE_TITLE_ONLY')['items'][0]
        self.assertEqual(title['snippets'], [])
        timeline = reuse.search([('linux', 'zcode', self.idx)], query='ZCODE_TIMELINE_ONLY')['items'][0]
        self.assertEqual(timeline['snippets'], [])
        bundle = service.handoff(self.idx, 'shared-id')
        self.assertEqual(bundle['payload']['provenance']['source'], 'zcode')
        self.assertIn('zcode:shared-id', json.dumps(bundle))

    def test_web_source_and_revision_bound_message_match_reuse(self):
        backend = SimpleNamespace(indexer=self.idx, root_dir=self.path.parent, sessions_dir=self.path,
            last_refresh_error=None, last_refreshed_at='2026-09-22T00:00:00Z', refreshing=False,
            ensure_ready=lambda: None)
        class Quiet(Handler):
            def log_message(self, *args):
                pass
        def handler(*args, **kwargs):
            return Quiet(*args, source_backends={('linux', 'zcode'): backend}, runtime_system='linux', demo=True, **kwargs)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            def get(path):
                with urlopen('http://127.0.0.1:' + str(server.server_port) + path, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    return json.load(response)
            found = get('/api/reuse/search?' + urlencode({'q': 'ZCODE_BODY_THIRD', 'source': 'zcode'}))
            self.assertEqual(found['errors'], [])
            item = found['items'][0]
            self.assertEqual(item['source'], 'zcode')
            self.assertEqual(item['snippets'][0]['message_index'], 2)
            query = '?' + urlencode({'source_revision': item['source_revision']})
            full = get('/api/linux/zcode/session/shared-id/message/2' + query)
            self.assertIn('ZCODE_BODY_THIRD', json.dumps(full))
            audited = get('/api/linux/zcode/session/shared-id/audit')
            self.assertEqual(audited['audit']['source'], 'zcode')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)

    def test_source_database_remains_read_only(self):
        self.assertIn('session', {r[0] for r in self.idx.conn.execute('SELECT name FROM sqlite_temp_master')})
        self.assertNotIn('tokens_input', {r[1] for r in self.idx.conn.execute('PRAGMA main.table_info(session)')})
        with self.assertRaises(sqlite3.OperationalError):
            self.idx.conn.execute("UPDATE main.session SET title='changed'")
        self.idx.query_usage()
        self.idx.list_sessions_page()
        self.idx.build_session_audit('shared-id')


if __name__ == '__main__':
    unittest.main()
