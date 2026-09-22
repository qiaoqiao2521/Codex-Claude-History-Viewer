"""Lightweight project browsing contracts, using synthetic local histories."""
from contextlib import ExitStack
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode, urlparse

from app import Handler
from history_core import reuse
from history_core.sources import Indexer, parse_claude_session_file


class ProjectSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = {}
        self.indexers = []
        self.tick = 0
        for source in ('codex', 'claude'):
            folder = self.root / source
            folder.mkdir()
            cache = self.root / (source + '-cache')
            cache.mkdir()
            kwargs = {'parse_file_fn': parse_claude_session_file} if source == 'claude' else {}
            idx = Indexer(folder, cache, source, **kwargs)
            self.addCleanup(idx.conn.close)
            self.sources[source] = idx
            self.indexers.append(('linux', source, idx))

    def add_session(self, source, sid, project='/repo/one'):
        self.tick += 1
        stamp = 1789992000000 + self.tick * 1000
        if source == 'codex':
            rows = [
                {'type': 'session_meta', 'timestamp': stamp, 'payload': {'id': sid, 'cwd': project}},
                {'type': 'response_item', 'timestamp': stamp + 1,
                 'payload': {'type': 'message', 'role': 'user',
                             'content': [{'type': 'input_text', 'text': 'synthetic ' + sid}]}}]
        else:
            rows = [{'type': 'user', 'timestamp': stamp, 'sessionId': sid, 'cwd': project,
                     'message': {'role': 'user', 'content': 'synthetic ' + sid}}]
        path = self.root / source / (sid + '.jsonl')
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def refresh(self):
        for idx in self.sources.values():
            idx.scan_sessions()

    def test_same_id_across_sources_has_distinct_locators_and_no_audit_work(self):
        self.add_session('codex', 'shared')
        self.add_session('claude', 'shared')
        self.add_session('claude', 'other-project', '/other/one')
        self.refresh()
        with ExitStack() as stack:
            for target in ('history_core.reuse.service.handoff', 'history_core.reuse._snippets'):
                stack.enter_context(patch(target, side_effect=AssertionError('directory must stay lightweight')))
            for idx in self.sources.values():
                stack.enter_context(patch.object(idx, 'build_session_audit', side_effect=AssertionError('no audit')))
            page = reuse.sessions(self.indexers, project='/repo/one')
        self.assertEqual(len(page['items']), 2)
        identities = {(item['source'], item['store_id'], item['id']) for item in page['items']}
        self.assertEqual(len(identities), 2)
        required = {'system', 'source', 'store_id', 'id', 'title', 'project', 'updated_at',
                    'content_status', 'source_revision'}
        for item in page['items']:
            self.assertLessEqual(required, item.keys())
            self.assertEqual(item['source_revision'], reuse.index_revision(self.sources[item['source']]))
            self.assertEqual(item['project'], '/repo/one')
            self.assertNotIn('evidence', item)
            self.assertNotIn('snippets', item)
        self.assertFalse(page['partial'])
        self.assertFalse(page['has_more'])

    def test_empty_project_selects_only_unbound_history(self):
        self.add_session('codex', 'unbound', '')
        self.add_session('claude', 'bound')
        self.refresh()
        page = reuse.sessions(self.indexers, project='')
        self.assertEqual([item['id'] for item in page['items']], ['unbound'])
        self.assertEqual(page['project'], '')
        with self.assertRaisesRegex(ValueError, 'project_required'):
            reuse.sessions(self.indexers, project=None)

    def test_default_fifty_session_pages_include_all_sources_without_duplicates(self):
        for number in range(57):
            self.add_session('codex' if number % 2 else 'claude', 's%02d' % number)
        self.refresh()
        first = reuse.sessions(self.indexers, project='/repo/one')
        self.assertEqual(len(first['items']), 50)
        self.assertTrue(first['has_more'])
        second = reuse.sessions(self.indexers, project='/repo/one', cursor=first['next_cursor'])
        self.assertEqual(len(second['items']), 7)
        self.assertFalse(second['has_more'])
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(len({item['id'] for item in first['items'] + second['items']}), 57)
        self.assertEqual(first['revision'], second['revision'])
        timestamps = [item['updated_at'] for item in first['items'] + second['items']]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_source_filter_excludes_other_source_errors_and_revision_changes(self):
        self.add_session('codex', 'a')
        self.add_session('codex', 'b')
        self.add_session('claude', 'c')
        self.refresh()
        missing = SimpleNamespace(source='pi', sessions_dir=self.root / 'missing')
        indexers = self.indexers + [('linux', 'pi', missing)]
        errors = [{'system': 'linux', 'source': 'gemini', 'error': 'permission_denied'}]
        first = reuse.sessions(indexers, project='/repo/one', source='codex', limit=1, errors=errors)
        self.assertFalse(first['partial'])
        self.assertEqual(first['errors'], [])
        self.add_session('claude', 'changed')
        self.sources['claude'].scan_sessions()
        second = reuse.sessions(indexers, project='/repo/one', source='codex', limit=1,
                                cursor=first['next_cursor'], errors=errors)
        self.assertEqual({row['source'] for row in first['items'] + second['items']}, {'codex'})
        self.assertEqual(first['revision'], second['revision'])
        with self.assertRaisesRegex(ValueError, 'invalid_source'):
            reuse.sessions(indexers, project='/repo/one', source='made-up')

    def test_cursor_rejects_project_source_and_selected_revision_changes(self):
        for sid in ('a', 'b'):
            self.add_session('codex', sid)
        self.refresh()
        first = reuse.sessions(self.indexers, project='/repo/one', source='codex', limit=1)
        for overrides in ({'project': '/repo/two'}, {'source': None}, {'limit': 2}):
            kwargs = dict(project='/repo/one', source='codex', limit=1, cursor=first['next_cursor'])
            kwargs.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, '(cursor_query|index_revision)_changed'):
                reuse.sessions(self.indexers, **kwargs)
        self.add_session('codex', 'new')
        self.sources['codex'].scan_sessions()
        with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
            reuse.sessions(self.indexers, project='/repo/one', source='codex', limit=1, cursor=first['next_cursor'])

    def test_candidate_bound_and_metadata_coverage_remain_explicit(self):
        for number in range(4):
            self.add_session('codex', 's%d' % number)
        self.refresh()
        self.sources['codex']._coverage = {'s3': {'content_status': 'metadata_only'}}
        with patch('history_core.reuse.MAX_CANDIDATES', 3):
            page = reuse.sessions(self.indexers, project='/repo/one')
        self.assertEqual(len(page['items']), 3)
        self.assertTrue(page['truncated'])
        self.assertTrue(page['partial'])
        self.assertFalse(page['has_more'])
        self.assertEqual(page['candidate_limit_per_source'], 3)
        self.assertEqual(page['items'][0]['content_status'], 'metadata_only')
        self.assertEqual(page['content_warnings'][0]['incomplete_sessions'], 1)

    def test_query_failure_disables_cursor_and_rejects_continuation(self):
        for source in self.sources:
            for number in range(2):
                self.add_session(source, source + str(number))
        self.refresh()
        first = reuse.sessions(self.indexers, project='/repo/one', limit=1)
        original = reuse._candidates
        def fail_one(idx, *args, **kwargs):
            if idx.source == 'claude':
                raise sqlite3.OperationalError('interrupted')
            return original(idx, *args, **kwargs)
        with patch('history_core.reuse._candidates', side_effect=fail_one):
            page = reuse.sessions(self.indexers, project='/repo/one', limit=1)
            self.assertTrue(page['partial'])
            self.assertEqual(page['pagination_status'], 'restart_after_source_error')
            self.assertFalse(page['has_more'])
            self.assertIsNone(page['next_cursor'])
            with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
                reuse.sessions(self.indexers, project='/repo/one', limit=1, cursor=first['next_cursor'])

    def handler_request(self, **params):
        handler = object.__new__(Handler)
        handler._source_backends = {
            ('linux', source): SimpleNamespace(indexer=idx, ensure_ready=lambda: None,
                                               sessions_dir=idx.sessions_dir)
            for source, idx in self.sources.items()}
        handler.send_json = lambda data, status=200: (status, data)
        return handler, urlparse('/api/reuse/sessions?' + urlencode(params))

    def test_handler_preserves_empty_project_default_limit_and_validates_parameters(self):
        self.add_session('codex', 'unbound', '')
        self.refresh()
        handler, parsed = self.handler_request(project='')
        status, page = handler.handle_reuse_get(parsed)
        self.assertEqual(status, 200)
        self.assertEqual([item['id'] for item in page['items']], ['unbound'])
        for params, error in (({}, 'project_required'), ({'project': '', 'limit': 'no'}, 'invalid_limit'),
                              ({'project': '', 'limit': 101}, 'invalid_limit'),
                              ({'project': '', 'source': 'unknown'}, 'invalid_source')):
            with self.subTest(params=params):
                handler, parsed = self.handler_request(**params)
                self.assertEqual(handler.handle_reuse_get(parsed), (400, {'error': error}))

    def test_handler_source_filter_never_initializes_unselected_backends(self):
        self.add_session('codex', 'selected')
        self.refresh()
        handler, parsed = self.handler_request(project='/repo/one', source='codex')
        handler._source_backends[('linux', 'claude')].ensure_ready = lambda: self.fail('unselected source initialized')
        status, page = handler.handle_reuse_get(parsed)
        self.assertEqual(status, 200)
        self.assertEqual([item['source'] for item in page['items']], ['codex'])
        self.assertFalse(page['partial'])
        # Alias normalization also happens before backend readiness work.
        handler, parsed = self.handler_request(project='/repo/one', source='cbc')
        with patch.object(handler, '_reuse_sources', return_value=([], [])) as capture:
            status, page = handler.handle_reuse_get(parsed)
        capture.assert_called_once_with(requested_source='codebuddy')
        self.assertEqual(status, 200)
        self.assertEqual(page['source'], 'codebuddy')


if __name__ == '__main__':
    unittest.main()
