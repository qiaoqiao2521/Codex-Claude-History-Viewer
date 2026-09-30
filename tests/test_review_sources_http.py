"""Four selected CLI histories cross the actual review HTTP contract."""
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
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import Handler
from history_core.providers import parser_for
from history_core.sources import Indexer
import test_native_review as native_fixtures
from test_agy import blob, metadata, step


ORIGINAL = 'Original requirement: ' + '完整需求' * 170 + ' END_OF_ORIGINAL'
CORRECTION = 'Later requirement: preserve every field and do not overwrite files.'


class ReviewSourcesHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = native_fixtures.NativeReviewTests()
        self.native.setUp()
        self.addCleanup(self.native.doCleanups)
        self.stores = {}

    def file_indexer(self, source, root):
        cache = self.root / ('cache-' + source)
        cache.mkdir()
        indexer = Indexer(root, cache, source, parse_file_fn=parser_for(source))
        self.addCleanup(indexer.conn.close)
        indexer.maybe_update_index(max_age_seconds=0)
        return indexer

    def fixtures(self):
        cb = self.root / 'codebuddy'
        cb.mkdir()
        cb_path = cb / 'review.jsonl'
        rows = []
        for i, (role, body) in enumerate([('user', ORIGINAL), ('assistant', 'Historical done claim'), ('user', CORRECTION)]):
            rows.append({'type': 'message', 'id': str(i), 'sessionId': 'review', 'cwd': '/synthetic/repo',
                         'timestamp': 1790078400000 + i * 1000, 'role': role,
                         'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': body}]})
        cb_path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        self.stores['codebuddy'] = (self.file_indexer('codebuddy', cb), cb_path, [0, 2])

        agy, agy_path = self.native.agy()
        with sqlite3.connect(agy_path) as db:
            for row, text, timestamp in [(2, ORIGINAL, 1790000100), (0, CORRECTION, 1790000300)]:
                db.execute('UPDATE steps SET step_payload=? WHERE idx=?',
                           (step(14, blob(1, text), meta=metadata(timestamp=timestamp)), row))
        agy.scan_sessions()
        self.stores['agy'] = (agy, agy_path, [0, 3])

        zcode, zcode_path = self.native.zcode()
        with sqlite3.connect(zcode_path) as db:
            for pid, text in [('first', ORIGINAL), ('last', CORRECTION)]:
                db.execute('UPDATE part SET data=? WHERE id=?', (json.dumps({'type': 'text', 'text': text}), pid))
        self.stores['zcode'] = (zcode, zcode_path, [0, 3])

        mc = self.root / 'mcode'
        session = mc / 'session'
        session.mkdir(parents=True)
        (session / 'manifest.json').write_text(json.dumps({'schemaVersion': 1, 'layout': 'v2-final-dated-session',
                                                         'sessionId': 'review', 'parentSessionId': 'parent'}))
        mc_path = session / 'messages.jsonl'
        records = []
        for i, (role, body) in enumerate([('user', ORIGINAL), ('assistant', 'Historical done claim'), ('user', CORRECTION)]):
            content = [{'type': 'text', 'text': body}]
            if role == 'assistant':
                content.insert(0, {'type': 'thinking', 'thinking': 'PRIVATE_REASONING'})
            records.append({'message_id': 'm' + str(i), 'turn_id': 't' + str(i), 'message': {
                'role': role, 'timestamp': 1790078400000 + i * 1000, 'content': content}})
        mc_path.write_text('\n'.join(json.dumps(row) for row in records) + '\n')
        self.stores['mcode'] = (self.file_indexer('mcode', mc), mc_path, [0, 2])

    def serve(self):
        backends = {('linux', source): SimpleNamespace(
            indexer=indexer, root_dir=path.parent, sessions_dir=getattr(indexer, 'sessions_dir', path),
            last_refresh_error=None, last_refreshed_at='2026-09-30T00:00:00Z', refreshing=False,
            ensure_ready=lambda: None) for source, (indexer, path, _) in self.stores.items()}
        class Quiet(Handler):
            def log_message(self, *args):
                pass
        def handler(*args, **kwargs):
            return Quiet(*args, source_backends=backends, runtime_system='linux', demo=True, **kwargs)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(5)
        self.addCleanup(close)
        self.url = 'http://127.0.0.1:' + str(server.server_port)

    def request(self, endpoint, params=None, body=None):
        url = self.url + '/api/reuse/' + endpoint
        if params:
            url += '?' + urlencode(params)
        request = Request(url, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'} if body is not None else {})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def source_hashes(self, source):
        _, path, _ = self.stores[source]
        if source == 'agy':
            files = path.parent.parent.rglob('*')
        elif source in ('codebuddy', 'mcode'):
            files = path.parent.rglob('*')
        else:
            files = [path, Path(str(path) + '-wal'), Path(str(path) + '-shm')]
        return {str(file): hashlib.sha256(file.read_bytes()).hexdigest()
                for file in files if file.is_file()}

    def mutate(self, source):
        _, path, _ = self.stores[source]
        if source == 'agy':
            with sqlite3.connect(path) as db:
                db.execute('UPDATE steps SET step_payload=? WHERE idx=0',
                           (step(14, blob(1, 'New source correction'), meta=metadata(timestamp=1790000300)),))
        elif source == 'zcode':
            with sqlite3.connect(path) as db:
                db.execute('UPDATE part SET data=? WHERE id=?',
                           (json.dumps({'type': 'text', 'text': 'New source correction'}), 'last'))
        else:
            with path.open('a') as stream:
                stream.write('{}\n')

    def test_four_sources_search_select_review_and_stale_conflict(self):
        self.fixtures()
        self.serve()
        for source, (indexer, _, expected_indices) in self.stores.items():
            with self.subTest(source=source):
                before = self.source_hashes(source)
                status, found = self.request('search', {'q': 'Original requirement', 'source': 'cbc' if source == 'codebuddy' else source})
                self.assertEqual(status, 200, found)
                self.assertEqual(found['errors'], [])
                self.assertEqual(len(found['items']), 1)
                item = found['items'][0]
                self.assertEqual((item['source'], item['id']), (source, 'review'))
                params = {'system': 'linux', 'source': source, 'session': item['id'],
                          'store_id': item['store_id'], 'source_revision': item['source_revision']}
                status, evidence = self.request('evidence', params)
                self.assertEqual(status, 200, evidence)
                self.assertEqual(evidence['evidence_status'], 'available', evidence)
                provenance = evidence['provenance']
                self.assertEqual(provenance['status'], 'captured')
                self.assertEqual(provenance['source'], source)
                if source == 'mcode':
                    self.assertEqual(evidence['current_verification'], 'unknown')
                    self.assertNotIn('codex', json.dumps(provenance))
                    self.assertEqual(evidence['changed'], [])
                    self.assertEqual(evidence['verified'], [])
                params.update(content_revision=provenance['content_revision'],
                              context_revision=provenance['context_revision'], limit=1)
                status, first = self.request('review-requests', params)
                self.assertEqual(status, 200, first)
                self.assertEqual(first['total'], 2)
                self.assertEqual([row['message_index'] for row in first['items']], expected_indices[:1])
                self.assertTrue(first['items'][0]['text_truncated'])
                status, second = self.request('review-requests', {**params, 'offset': first['next_offset']})
                self.assertEqual(status, 200, second)
                self.assertEqual([row['message_index'] for row in second['items']], expected_indices[1:])
                self.assertIsNone(second['next_offset'])
                selections = [{key: value for key, value in {
                    'system': 'linux', 'source': source, 'session_id': item['id'], 'store_id': item['store_id'],
                    'content_revision': provenance['content_revision'], 'context_revision': provenance['context_revision'],
                    'message_index': row['message_index']}.items()}
                    for row in first['items'] + second['items']]
                status, packet = self.request('review-preview', body={'selections': selections})
                self.assertEqual(status, 200, packet)
                self.assertEqual(packet['code_verification'], 'not_performed')
                self.assertEqual(packet['authorization'], 'context_only')
                self.assertEqual([row['text'] for row in packet['items']], [ORIGINAL, CORRECTION])
                self.assertEqual([row['message_index'] for row in packet['items']], expected_indices)
                self.assertEqual([row['locator']['role'] for row in packet['items']], ['user', 'user'])
                self.assertNotIn('PRIVATE_REASONING', packet['markdown'])
                self.assertEqual(before, self.source_hashes(source))
                if source == 'codebuddy':
                    status, canonical = self.request('search', {'q': 'Original requirement', 'source': 'codebuddy'})
                    self.assertEqual(status, 200)
                    self.assertEqual([(x['source'], x['store_id'], x['id']) for x in canonical['items']],
                                     [(x['source'], x['store_id'], x['id']) for x in found['items']])
                self.mutate(source)
                status, conflict = self.request('review-preview', body={'selections': selections})
                self.assertEqual(status, 409, conflict)
                self.assertRegex(conflict['error'], 'stale|changed|revision')

    def test_mixed_packet_keeps_four_stores_with_the_same_native_session_id_separate(self):
        self.fixtures()
        self.serve()
        selections = []
        for source in self.stores:
            status, found = self.request('search', {'q': 'Original requirement', 'source': source})
            self.assertEqual(status, 200)
            item = found['items'][0]
            status, evidence = self.request('evidence', {'system': 'linux', 'source': source,
                'session': item['id'], 'store_id': item['store_id'], 'source_revision': item['source_revision']})
            self.assertEqual(status, 200)
            selections.append({'system': 'linux', 'source': source, 'session_id': 'review',
                'store_id': item['store_id'], 'message_index': 0,
                'content_revision': evidence['provenance']['content_revision']})
        status, packet = self.request('review-preview', body={'selections': selections})
        self.assertEqual(status, 200, packet)
        self.assertEqual({item['source'] for item in packet['items']}, set(self.stores))
        self.assertEqual(len({item['store_id'] for item in packet['items']}), 4)
        self.assertEqual([item['text'] for item in packet['items']], [ORIGINAL] * 4)
        self.assertEqual(len(packet['required_requirement']), 4)
        self.assertEqual(packet['code_verification'], 'not_performed')


if __name__ == '__main__':
    unittest.main()
