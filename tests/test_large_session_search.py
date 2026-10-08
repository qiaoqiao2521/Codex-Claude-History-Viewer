"""Search complete cached messages without rebuilding or copying full bodies."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode, urlparse
from unittest.mock import patch

from app import Handler
from history_core import reuse, service
from history_core.sources import Indexer, MAX_SEARCH_CHARS, parse_codex_session_file


class LargeSessionSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'sessions'
        self.source.mkdir()
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.idx = Indexer(self.source, self.cache, 'codex', parser_version=5)
        self.addCleanup(lambda: self.idx.conn.close())

    def seed(self, sid, messages, blob='', title='Example', project='/fixture', pinned=0):
        # Represents an existing cache whose parser stored only a body prefix.
        with self.idx.conn:
            self.idx.conn.execute(
                'INSERT INTO sessions(id,file_path,start_ts_ms,end_ts_ms,cwd,title,message_count,search_blob,parser_version,pinned) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (sid, str(self.source / (sid + '.jsonl')), 1, 2, project, title, len(messages), blob, 5, pinned))
            self.idx.conn.executemany('INSERT INTO messages(session_id,ts_ms,role,kind,text) VALUES(?,?,?,?,?)',
                                     [(sid, n, 'assistant', kind, text) for n, (kind, text) in enumerate(messages)])

    def assert_search_ids(self, query, expected):
        self.assertEqual({row['id'] for row in self.idx.query_sessions(q=query)}, set(expected))
        self.assertEqual({row['id'] for row in self.idx.list_sessions_page(q=query)['items']}, set(expected))
        self.assertEqual({row['id'] for row in service.search(self.idx, query=query)['items']}, set(expected))
        page = reuse.search([('linux', 'codex', self.idx)], query=query)
        self.assertEqual({row['id'] for row in page['items']}, set(expected))

    def test_parser_capped_cache_finds_both_languages_after_prefix(self):
        path = self.source / 'large.jsonl'
        rows = [{'type': 'session_meta', 'timestamp': 1, 'payload': {'id': 'large', 'cwd': '/fixture'}}]
        for n, text in enumerate(['Early ' + 'x' * MAX_SEARCH_CHARS, '后置系统 lateenglish']):
            rows.append({'type': 'response_item', 'timestamp': n + 2, 'payload': {
                'type': 'message', 'role': 'user' if n == 0 else 'assistant',
                'content': [{'type': 'input_text', 'text': text}]}})
        path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in rows))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        parsed = parse_codex_session_file(path)
        self.assertNotIn('后置系统', parsed['search_blob'])
        self.assertNotIn('lateenglish', parsed['search_blob'])
        with patch('history_core.sources.build_audit_for_file', return_value=None):
            self.idx.scan_sessions()
        for query in ['后置系统', 'lateenglish', 'Early 后置系统', '后置系统 lateenglish']:
            with self.subTest(query=query): self.assert_search_ids(query, ['large'])
        self.assertEqual(self.idx.search_session_messages('large', '后置系统')['match_count'], 1)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_raw_fallback_and_harness_context_do_not_recall_public_evidence(self):
        self.seed('raw', [('raw_json:event_msg:imported', '双千兆 fallbackneedle')])
        self.seed('context', [('context', '双千兆 contextonly')])
        self.assert_search_ids('双千兆', [])
        self.assert_search_ids('fallbackneedle', [])
        self.assert_search_ids('contextonly', [])

    def test_old_blob_cannot_recall_thinking_and_system_records(self):
        for sid, kind in [('thought', 'reasoning_summary'), ('thinking', 'thinking'),
                          ('raw', 'raw_json:unknown'), ('context', 'context:memory')]:
            self.seed(sid, [(kind, 'noise_only')], blob='noise_only')
        self.seed('system', [('message', 'noise_only')], blob='noise_only')
        with self.idx.conn:
            self.idx.conn.execute("UPDATE messages SET role='system' WHERE session_id='system'")
        self.assert_search_ids('noise_only', [])

    def test_literal_wildcards_and_backslash_do_not_broaden_search(self):
        self.seed('literal', [('message', r'100% disk_a path\leaf')])
        self.seed('decoy', [('message', '1000 diskXa pathleaf')], blob='1000 diskXa pathleaf')
        for query in ['100%', 'disk_a', r'path\leaf']:
            with self.subTest(query=query): self.assert_search_ids(query, ['literal'])

    def test_old_cache_read_needs_no_reparse_or_writes(self):
        self.seed('old', [('message', 'missingfromblob 系统')], blob='short prefix')
        self.idx.conn.close()
        self.idx = Indexer(self.source, self.cache, 'codex', parser_version=5,
                           parse_file_fn=lambda _: self.fail('read must not reparse'))
        revision = reuse.index_revision(self.idx)
        changes = self.idx.conn.total_changes
        self.idx.conn.execute('PRAGMA query_only=ON')
        self.assert_search_ids('missingfromblob', ['old'])
        self.assertEqual(reuse.index_revision(self.idx), revision)
        self.assertEqual(self.idx.conn.total_changes, changes)

    def test_handler_decodes_chinese_and_shared_service_paginates(self):
        for sid in ['a', 'b', 'c']:
            self.seed(sid, [('message', '系统 tailmatch')], pinned=int(sid == 'a'))
        handler = object.__new__(Handler)
        handler.send_json = lambda obj, **kwargs: obj
        backend = SimpleNamespace(indexer=self.idx)
        first = handler.handle_sessions(urlparse('/api/sessions?' + urlencode({'q': '系统', 'limit': 1})), backend)
        self.assertEqual({item['id'] for item in first['sessions']}, {'a', 'b'})
        self.assertTrue(first['has_more'])
        second = service.search(self.idx, query='系统', limit=1, offset=first['next_offset'], stable_order=True)
        self.assertEqual([item['id'] for item in second['items']], ['c'])
        matches = handler.handle_session_search('a', urlparse('/api/session/a/search?' + urlencode({'q': '系统'})), backend)
        self.assertEqual(matches['match_count'], 1)


if __name__ == '__main__':
    unittest.main()
