"""Synthetic native/source capability matrix; no personal database access."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from history_core import reuse
from history_core.evidence import source_store_id
from history_core.sources import (HermesStateIndexer, OpenCodeIndexer, Indexer,
                                  parse_openclaw_session_file, MESSAGE_INLINE_FULL_THRESHOLD)


OPENCODE_SCHEMA = '''
CREATE TABLE session (
 id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, slug TEXT, directory TEXT,
 title TEXT, version TEXT, share_url TEXT, summary_additions INTEGER,
 summary_deletions INTEGER, summary_files INTEGER, summary_diffs TEXT,
 time_created INTEGER, time_updated INTEGER, agent TEXT, model TEXT, cost REAL,
 tokens_input INTEGER, tokens_output INTEGER, tokens_reasoning INTEGER,
 tokens_cache_read INTEGER, tokens_cache_write INTEGER
);
CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, time_created INTEGER, data TEXT);
CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, name TEXT);
'''
HERMES_SCHEMA = '''
CREATE TABLE sessions (
 id TEXT PRIMARY KEY, source TEXT, user_id TEXT, model TEXT,
 started_at REAL, ended_at REAL, message_count INTEGER, title TEXT
);
CREATE TABLE messages (
 id INTEGER PRIMARY KEY, session_id TEXT, timestamp REAL, role TEXT,
 content TEXT, reasoning TEXT, tool_calls TEXT, tool_name TEXT
);
'''


class NativeReuseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.db_paths = []

    def tearDown(self):
        for path, before in self.db_paths:
            self.assertEqual(path.read_bytes(), before, 'native source bytes changed')
            self.assertFalse(Path(str(path) + '-journal').exists())
            self.assertFalse(Path(str(path) + '-wal').exists())
            self.assertFalse(Path(str(path) + '-shm').exists())

    def opencode(self):
        path = self.root / 'opencode.db'
        with sqlite3.connect(path) as db:
            db.executescript(OPENCODE_SCHEMA)
            db.executemany('INSERT INTO session (id, directory, title, time_created, time_updated) VALUES (?, ?, ?, 1000000000000, 1000000001000)', [
                ('shared-id', '/synthetic/one/repo', 'OPENCODE_TITLE_ONLY'),
                ('other', '/synthetic/two/repo', 'Another same-basename project')])
            db.executemany('INSERT INTO message VALUES (?, ?, ?, ?)', [
                ('m-z', 'shared-id', 1000000000000, json.dumps({'role': 'user'})),
                ('m-a', 'shared-id', 1000000000000, json.dumps({'role': 'assistant'}))])
            # Insert in reverse order; equal timestamps must still locate p-a at index zero.
            parts = [
                ('p-z', 'm-z', {'type': 'text', 'text': 'OPENCODE_BODY_SECOND'}),
                ('p-b', 'm-a', {'type': 'reasoning', 'text': 'OPENCODE_REASON_BODY'}),
                ('p-a', 'm-a', {'type': 'text', 'text': 'OPENCODE_BODY_FIRST'}),
                ('p-0', 'm-z', {'type': 'step-start'})]
            db.executemany('INSERT INTO part VALUES (?, ?, ?, ?, ?)', [
                (pid, mid, 'shared-id', 1000000000000, json.dumps(data)) for pid, mid, data in parts])
        self.db_paths.append((path, path.read_bytes()))
        idx = OpenCodeIndexer(path)
        self.addCleanup(idx.conn.close)
        return idx

    def hermes(self):
        path = self.root / 'hermes.db'
        with sqlite3.connect(path) as db:
            db.executescript(HERMES_SCHEMA)
            db.executemany('INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
                ('shared-id', 'cli', 'synthetic', 'none', 1000000000, 1000000001, 4, 'HERMES_TITLE_ONLY'),
                ('other', 'telegram', 'synthetic', 'none', 1000000000, 1000000001, 0, 'another')])
            db.executemany('INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
                (30, 'shared-id', 1000000000, 'assistant', 'HERMES_CONTENT_BOTH', 'HERMES_REASON_BOTH', None, None),
                (10, 'shared-id', 1000000000, 'user', 'HERMES_CONTENT_ONLY', None, None, None),
                (20, 'shared-id', 1000000000, 'assistant', '', 'HERMES_REASON_ONLY', None, None),
                (40, 'shared-id', 1000000001, 'assistant', 'A' * 7000, 'B' * 7000 + ' REASON_TAIL', None, None)])
        self.db_paths.append((path, path.read_bytes()))
        idx = HermesStateIndexer(path)
        self.addCleanup(idx.conn.close)
        return idx

    def assert_match(self, idx, query, expected_index):
        result = reuse.search([('linux', idx.source, idx)], query=query)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(result['items']), 1, result)
        item = result['items'][0]
        self.assertEqual(item['store_id'], source_store_id('linux', idx.source, idx))
        self.assertTrue(item['snippets'], item)
        snippet = item['snippets'][0]
        self.assertEqual(snippet['message_index'], expected_index, snippet)
        self.assertIn(query, snippet['text'])
        # The full-message API used by a deep link must show the same evidence.
        message = idx.get_session_message(item['id'], expected_index)
        self.assertEqual(message['message_index'], expected_index)
        self.assertIn(query, message['text'])
        return item

    def test_opencode_body_reasoning_and_flattened_indices_with_timestamps_tied(self):
        idx = self.opencode()
        for query, index in [('OPENCODE_BODY_FIRST', 0), ('OPENCODE_REASON_BODY', 1), ('OPENCODE_BODY_SECOND', 2)]:
            with self.subTest(query=query):
                self.assert_match(idx, query, index)
        title = reuse.search([('linux', 'opencode', idx)], query='OPENCODE_TITLE_ONLY')['items'][0]
        self.assertEqual(title['snippets'], [])
        self.assertEqual(title['snippet_status'], 'metadata_match_or_excerpt_unavailable')

    def test_hermes_content_reasoning_and_tied_indices_match_full_message(self):
        idx = self.hermes()
        for query, index in [('HERMES_CONTENT_ONLY', 0), ('HERMES_REASON_ONLY', 1),
                             ('HERMES_CONTENT_BOTH', 2), ('HERMES_REASON_BOTH', 2)]:
            with self.subTest(query=query):
                self.assert_match(idx, query, index)
        title = reuse.search([('linux', 'hermes', idx)], query='HERMES_TITLE_ONLY')['items'][0]
        self.assertEqual(title['snippets'], [])
        # The session includes a 14k message: bounded is an honest explanation
        # even when this particular query matched metadata only.
        self.assertEqual(title['snippet_status'], 'bounded')

    def test_hermes_both_fields_visible_and_combined_preview_length_is_truthful(self):
        idx = self.hermes()
        short = idx.get_session_message('shared-id', 2)
        self.assertIn('HERMES_CONTENT_BOTH', short['text'])
        self.assertIn('HERMES_REASON_BOTH', short['text'])
        self.assertEqual(short['char_count'], len(short['text']))
        page = idx.get_session_messages_page('shared-id', offset=3, limit=1)['messages'][0]
        full = idx.get_session_message('shared-id', 3)
        self.assertGreater(full['char_count'], MESSAGE_INLINE_FULL_THRESHOLD)
        self.assertEqual(page['char_count'], full['char_count'])
        self.assertTrue(page['is_truncated'])
        self.assertFalse(full['is_truncated'])
        self.assertLess(len(page['text']), 5000)
        self.assertIn('REASON_TAIL', full['text'])
        self.assertEqual(full['char_count'], len(full['text']))

    def test_projects_same_basename_stay_distinct_and_cross_source_ids_do_not_collide(self):
        oc, hermes = self.opencode(), self.hermes()
        entries = [('linux', 'opencode', oc), ('linux', 'hermes', hermes)]
        result = reuse.projects(entries)
        self.assertEqual(result['errors'], [])
        counts = {item['project']: item['session_count'] for item in result['items']}
        self.assertEqual(counts, {'/synthetic/one/repo': 1, '/synthetic/two/repo': 1, '': 2})
        result = reuse.search(entries, query='TITLE_ONLY')
        self.assertEqual({(x['source'], x['id']) for x in result['items']}, {('opencode', 'shared-id'), ('hermes', 'shared-id')})
        self.assertEqual(len({x['store_id'] for x in result['items']}), 2)

    def test_native_timeline_opencode_unknown_revision_and_hermes_unsupported_audit(self):
        oc, hermes = self.opencode(), self.hermes()
        result = reuse.timeline([('linux', 'opencode', oc), ('linux', 'hermes', hermes)], project='/synthetic/one/repo')
        self.assertEqual(result['errors'], [])
        items = {x['source']: x for x in result['items']}
        self.assertEqual(set(items), {'opencode'})
        self.assertEqual(items['opencode']['evidence_status'], 'available')
        self.assertEqual(items['opencode']['provenance']['content_revision'], 'unknown')
        self.assertTrue(all(x['current_verification'] == 'unknown' for x in result['items']))
        unbound = reuse.timeline([('linux', 'opencode', oc), ('linux', 'hermes', hermes)], project='')
        self.assertEqual(unbound['errors'], [])
        self.assertEqual(len(unbound['items']), 2)
        for item in unbound['items']:
            self.assertEqual(item['source'], 'hermes')
            self.assertEqual(item['project'], '')
            self.assertEqual(item['evidence_status'], 'audit_not_supported_or_unavailable')
            self.assertEqual(item['status'], 'unknown')
            self.assertEqual(item['evidence'], [])
            self.assertEqual(item['current_verification'], 'unknown')

    def test_native_file_history_is_explicitly_unsupported(self):
        oc, hermes = self.opencode(), self.hermes()
        result = reuse.timeline([('linux', 'opencode', oc), ('linux', 'hermes', hermes)], project='/synthetic/one/repo', file_path='src/a.py')
        self.assertEqual(result['items'], [])
        self.assertTrue(result['partial'])
        self.assertEqual({(x['source'], x['error']) for x in result['errors']}, {
            ('opencode', 'file_history_not_indexed'), ('hermes', 'file_history_not_indexed')})

    def test_native_revision_changes_invalidate_old_pagination(self):
        idx = self.hermes()
        entries = [('linux', 'hermes', idx)]
        first = reuse.timeline(entries, project='', limit=1)
        self.assertIsNotNone(first['next_cursor'])
        # Deliberate external producer write. This is the only permitted source mutation in this test.
        with sqlite3.connect(idx.db_path) as writer:
            writer.execute("UPDATE sessions SET ended_at=ended_at+1 WHERE id='other'")
        self.db_paths = [(path, path.read_bytes()) for path, _ in self.db_paths]
        with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
            reuse.timeline(entries, project='', cursor=first['next_cursor'], limit=1)

    def test_hermes_transport_source_must_not_invent_a_bound_project(self):
        idx = self.hermes()
        entries = [('linux', 'hermes', idx)]
        result = reuse.projects(entries)
        self.assertEqual(result['errors'], [])
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['project'], '')
        self.assertEqual(result['items'][0]['session_count'], 2)
        self.assertEqual(reuse.search(entries, query='HERMES_CONTENT_ONLY')['items'][0]['project'], '')
        timeline = reuse.timeline(entries, project='')
        self.assertEqual(len(timeline['items']), 2)
        self.assertTrue(all(item['project'] == '' for item in timeline['items']))

    def test_openclaw_jsonl_body_search_location_project_and_readonly(self):
        sessions = self.root / 'claw/sessions'; sessions.mkdir(parents=True)
        path = sessions / 'shared-id.jsonl'
        records = [
            {'type': 'session', 'id': 'shared-id', 'cwd': '/synthetic/claw/repo', 'timestamp': '2026-09-22T01:00:00Z'},
            {'type': 'message', 'timestamp': '2026-09-22T01:00:01Z', 'message': {'role': 'user', 'content': 'OPENCLAW_TITLE'}},
            {'type': 'message', 'timestamp': '2026-09-22T01:00:01Z', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'OPENCLAW_BODY_中文'}]}}]
        path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records)+'\n')
        before = path.read_bytes()
        cache = self.root / 'cache'; cache.mkdir()
        idx = Indexer(sessions, cache, 'openclaw', parse_file_fn=parse_openclaw_session_file, parser_version=1)
        self.addCleanup(idx.conn.close); idx.maybe_update_index(0)
        self.assert_match(idx, 'OPENCLAW_BODY_中文', 1)
        entries = [('linux', 'openclaw', idx)]
        self.assertEqual(reuse.projects(entries)['items'][0]['project'], '/synthetic/claw/repo')
        timeline = reuse.timeline(entries, project='/synthetic/claw/repo')
        self.assertEqual(timeline['items'][0]['evidence_status'], 'available')
        self.assertTrue(timeline['items'][0]['provenance']['content_revision'].startswith('sha256:'))
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
