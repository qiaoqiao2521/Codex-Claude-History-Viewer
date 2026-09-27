"""Real Handler and indexed-source integration for conversation navigation."""
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import urlencode, urlparse

from app import Handler
from history_core import reuse
from history_core.evidence import source_store_id
from history_core.sources import Indexer, OpenCodeIndexer, parse_claude_session_file


class ConversationRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.indexers = {}
        self.tick = 0
        self.readiness = []
        for source in ('codex', 'claude'):
            folder = self.root / source
            folder.mkdir()
            cache = self.root / (source + '-cache')
            cache.mkdir()
            kwargs = {'parse_file_fn': parse_claude_session_file} if source == 'claude' else {}
            indexer = Indexer(folder, cache, source, **kwargs)
            self.addCleanup(indexer.conn.close)
            self.indexers[source] = indexer

    def seed(self, source, sid, title='Investigate repeated search failure', *, fail=False):
        self.tick += 1
        stamp = 1789992000000 + self.tick * 1000
        if source == 'codex':
            rows = [
                {'type': 'session_meta', 'timestamp': stamp,
                 'payload': {'id': sid, 'cwd': '/synthetic/project'}},
                {'type': 'response_item', 'timestamp': stamp + 1,
                 'payload': {'type': 'message', 'role': 'user',
                             'content': [{'type': 'input_text', 'text': title}]}}]
            if fail:
                rows.extend([
                    {'type': 'response_item', 'timestamp': stamp + 2,
                     'payload': {'type': 'function_call', 'name': 'exec_command', 'call_id': 'run-test',
                                 'arguments': json.dumps({'cmd': 'pytest'})}},
                    {'type': 'response_item', 'timestamp': stamp + 3,
                     'payload': {'type': 'function_call_output', 'call_id': 'run-test',
                                 'output': 'Error: Permission denied; tests failed; exit code: 1'}}])
            rows.append({'type': 'response_item', 'timestamp': stamp + 4,
                         'payload': {'type': 'message', 'role': 'assistant',
                                     'content': [{'type': 'output_text', 'text': '决定使用本地缓存; source codex'}]}})
        else:
            rows = [
                {'type': 'user', 'timestamp': stamp, 'sessionId': sid, 'cwd': '/synthetic/project',
                 'message': {'role': 'user', 'content': title}},
                {'type': 'assistant', 'timestamp': stamp + 4, 'sessionId': sid, 'cwd': '/synthetic/project',
                 'message': {'role': 'assistant', 'content': '决定使用本地缓存; source claude'}}]
        path = self.indexers[source].sessions_dir / (sid + '.jsonl')
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
        return path

    def refresh(self):
        for indexer in self.indexers.values():
            indexer.scan_sessions()

    def handler(self):
        handler = object.__new__(Handler)
        handler._source_backends = {
            ('linux', source): SimpleNamespace(
                indexer=indexer, sessions_dir=getattr(indexer, 'sessions_dir', indexer.db_path),
                ensure_ready=lambda selected=source: self.readiness.append(selected))
            for source, indexer in self.indexers.items()}
        handler.send_json = lambda data, status=200: (status, data)
        return handler

    def request(self, endpoint='key-messages', **params):
        parsed = urlparse('/api/reuse/' + endpoint + '?' + urlencode(params))
        return self.handler().handle_reuse_get(parsed)

    def locator(self, source, sid='shared'):
        indexer = self.indexers[source]
        return {'system': 'linux', 'source': source, 'session': sid,
                'store_id': source_store_id('linux', source, indexer),
                'source_revision': reuse.index_revision(indexer)}

    def test_handler_passes_complete_identity_and_real_absolute_reader_positions(self):
        paths = [self.seed(source, 'shared', 'Request from ' + source) for source in self.indexers]
        self.refresh()
        hashes = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        for source, indexer in self.indexers.items():
            locator = self.locator(source)
            before_changes = indexer.conn.total_changes
            self.readiness.clear()
            status, data = self.request(**locator)
            self.assertEqual(status, 200)
            self.assertEqual(self.readiness, [source], 'unselected sources must not initialize')
            self.assertEqual(data['status'], 'available')
            for key in ('system', 'source', 'store_id', 'source_revision'):
                self.assertEqual(data[key], locator[key])
            self.assertEqual(data['id'], 'shared')
            self.assertFalse(data['partial'])
            self.assertEqual([item['message_index'] for item in data['items']], [0, 1])
            self.assertEqual(data['items'][0]['text'], 'Request from ' + source)
            for item in data['items']:
                original = indexer.get_session_message('shared', item['message_index'])
                self.assertEqual(item['text'], original['text'])
                self.assertEqual(item['role'], original['role'])
            self.assertEqual(indexer.conn.total_changes, before_changes)
        self.assertEqual({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, hashes)

    def test_handler_rejects_wrong_store_and_wrong_system_without_other_source_data(self):
        for source in self.indexers:
            self.seed(source, 'shared', 'Request from ' + source)
        self.refresh()
        for override in ({'store_id': self.locator('claude')['store_id']}, {'system': 'missing-system'}):
            with self.subTest(override=override):
                status, data = self.request(**(self.locator('codex') | override))
                self.assertEqual(status, 400)
                self.assertEqual(data, {'error': 'selection_source_unavailable'})

    def test_handler_missing_revision_is_a_bad_request(self):
        self.seed('codex', 'shared')
        self.refresh()
        missing = self.locator('codex')
        missing.pop('source_revision')
        self.assertEqual(self.request(**missing), (400, {'error': 'source_revision_required'}))

    def test_handler_rejects_stale_revision_and_index_changes_as_conflicts(self):
        self.seed('codex', 'shared')
        self.refresh()
        locator = self.locator('codex')
        self.assertEqual(self.request(**(locator | {'source_revision': '0' * 64})),
                         (409, {'error': 'index_revision_changed'}))
        self.seed('codex', 'later')
        self.refresh()
        self.assertEqual(self.request(**locator), (409, {'error': 'index_revision_changed'}))

    def test_native_database_is_explicitly_unsupported_without_being_mutated(self):
        path = self.root / 'opencode.sqlite'
        with sqlite3.connect(path) as conn:
            conn.execute('CREATE TABLE session(id TEXT PRIMARY KEY, title TEXT)')
            conn.execute("INSERT INTO session VALUES('native', 'Native synthetic task')")
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        indexer = OpenCodeIndexer(path)
        self.addCleanup(indexer.conn.close)
        self.indexers['opencode'] = indexer
        locator = self.locator('opencode', 'native')
        status, data = self.request(**locator)
        self.assertEqual(status, 200)
        self.assertEqual(data['status'], 'unsupported')
        self.assertEqual(data['reason'], 'source_message_index_unsupported')
        self.assertEqual(data['items'], [])
        self.assertIsNone(data['total_messages'])
        for key in ('system', 'source', 'store_id', 'source_revision'):
            self.assertEqual(data[key], locator[key])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_group_membership_precedes_pagination_and_failed_member_survives(self):
        expected = set()
        for number in range(27):
            source = 'codex' if number % 2 == 0 else 'claude'
            sid = f's{number:02d}'
            self.seed(source, sid, fail=number == 0)
            expected.add((source, sid))
        for source in self.indexers:
            self.seed(source, 'same-id')
            expected.add((source, 'same-id'))
        self.seed('claude', 'different', 'Investigate a payment callback')
        self.refresh()
        all_indexers = [('linux', source, indexer) for source, indexer in self.indexers.items()]
        first = reuse.sessions(all_indexers, project='/synthetic/project', limit=20)
        second = reuse.sessions(all_indexers, project='/synthetic/project', limit=20,
                                cursor=first['next_cursor'])
        self.assertEqual(len(first['items']), 20)
        self.assertEqual(len(second['items']), 10)
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(first['revision'], second['revision'])
        combined = first['items'] + second['items']
        grouped = [item for item in combined if 'related_group' in item]
        self.assertEqual({(item['source'], item['id']) for item in grouped}, expected)
        self.assertEqual(len(grouped), 29)
        self.assertEqual(len({(item['system'], item['source'], item['store_id'], item['id'])
                              for item in combined}), 30)
        self.assertEqual({item['related_group']['total'] for item in grouped}, {29})
        self.assertEqual(len({item['related_group']['id'] for item in grouped}), 1)
        self.assertTrue(any(item['id'] == 's00' for item in second['items']), 'old failed member stays reachable')
        failure = self.indexers['codex'].get_session_message('s00', 2)
        self.assertIn('Error: Permission denied', failure['text'])
        self.assertEqual(failure['kind'], 'tool_result')
        self.assertFalse(first['partial'])
        self.assertFalse(second['partial'])
        # Exercise the Handler too: it must preserve full-set totals on page one.
        status, response = self.request('sessions', project='/synthetic/project', limit=20)
        self.assertEqual(status, 200)
        self.assertEqual(response['items'], first['items'])


if __name__ == '__main__':
    unittest.main()
