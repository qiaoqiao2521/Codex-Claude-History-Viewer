"""Public marker reads expose bounded recorded metadata, never message bodies."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from history_core import HistoryReader
from history_core.markers import MAX_METADATA_CHARS, read_markers
from history_core.trace_markers import DECLARED_MARKER_PREFIX, LEARNING_OUTPUT_STYLE_PREFIX

REPO = Path(__file__).resolve().parents[1]


class TraceMarkersReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.path = self.source / 'markers.jsonl'
        records = [{'type': 'session_meta', 'timestamp': '2026-10-10T00:00:00Z',
                    'payload': {'id': 'marker-session', 'cwd': '/synthetic/markers'}}]
        payloads = [
            {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'USER_BODY_NOT_RETURNED'}]},
            {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': 'PRIVATE_REASONING_NOT_RETURNED'}]},
            {'type': 'function_call', 'name': 'Skill', 'call_id': 'native-call-1',
             'arguments': json.dumps({'skill': 'obsidian'})},
            {'type': 'function_call_output', 'call_id': 'native-call-1', 'output': 'RESULT_BODY_NOT_RETURNED'},
            {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text',
             'text': DECLARED_MARKER_PREFIX + json.dumps({'name': 'conversation-distill', 'path': '/synthetic/SKILL.md', 'version': 'v1'})}]},
            {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text',
             'text': LEARNING_OUTPUT_STYLE_PREFIX + ' CONTEXT_BODY_NOT_RETURNED'}]},
            {'type': 'function_call', 'name': 'Skill', 'call_id': 'native-call-2',
             'arguments': json.dumps({'skill': 'test-tool'})},
        ]
        for index, payload in enumerate(payloads, start=1):
            records.append({'type': 'response_item', 'timestamp': f'2026-10-10T00:00:{index:02d}Z',
                            'payload': payload})
        self.path.write_text('\n'.join(json.dumps(record) for record in records) + '\n')
        self.original = self.path.read_bytes()
        self.reader = HistoryReader('codex', self.source, self.root / 'cache')
        self.addCleanup(self.reader.close)
        self.reader.refresh()
        self.indexer = self.reader._HistoryReader__indexer

    def tearDown(self):
        self.assertEqual(self.path.read_bytes(), self.original)

    def put_metadata(self, message_index, metadata):
        message_id = self.indexer.conn.execute(
            'SELECT id FROM messages WHERE session_id=? ORDER BY ts_ms,id LIMIT 1 OFFSET ?',
            ('marker-session', message_index)).fetchone()[0]
        raw = metadata if isinstance(metadata, str) else json.dumps(metadata)
        self.indexer.conn.execute('UPDATE messages SET activity_meta_json=? WHERE id=?', (raw, message_id))
        self.indexer.conn.commit()

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'history_core', '--source', 'codex',
            '--source-path', str(self.source), '--data-dir', str(self.root / 'cache'), 'markers', *args],
            cwd=REPO, capture_output=True, text=True)

    def test_public_reader_uses_absolute_ordinals_and_native_locators(self):
        result = self.reader.markers(name='obsidian', kind='skill', session_id='marker-session')
        self.assertEqual(result['count'], 1)
        item = result['items'][0]
        self.assertEqual(item['source'], 'codex')
        self.assertEqual(item['message_index'], 2)
        self.assertEqual(item['marker_index'], 0)
        self.assertEqual(item['call_id'], 'native-call-1')
        self.assertEqual(item['raw_ref']['line_no'], 4)
        self.assertEqual(item['cwd'], '/synthetic/markers')
        self.assertEqual(item['event'], 'invocation_requested')
        self.assertEqual(item['evidence_origin'], 'native_tool_call')
        self.assertEqual(result['index_revision'], self.reader.search(brief=True)['index_revision'])
        rendered = json.dumps(result)
        for sentinel in ('USER_BODY_NOT_RETURNED', 'PRIVATE_REASONING_NOT_RETURNED',
                         'RESULT_BODY_NOT_RETURNED', 'CONTEXT_BODY_NOT_RETURNED'):
            self.assertNotIn(sentinel, rendered)

    def test_queries_do_not_refresh_write_rows_or_create_marker_tables(self):
        before = self.indexer.conn.total_changes
        tables = self.indexer.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        statements = []
        self.indexer.conn.set_trace_callback(statements.append)
        try:
            with patch.object(self.indexer, 'maybe_update_index', side_effect=AssertionError('implicit refresh')):
                self.reader.markers()
        finally:
            self.indexer.conn.set_trace_callback(None)
        self.assertEqual(self.indexer.conn.total_changes, before)
        self.assertEqual(self.indexer.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(), tables)
        self.assertTrue(statements)
        self.assertTrue(all(statement.lstrip().upper().startswith(('SELECT', 'WITH')) for statement in statements))
        self.assertTrue(all('m.text' not in statement and 'tool_summary_json' not in statement for statement in statements))

    def test_empty_filter_does_not_claim_zero_triggers_or_assess_effects(self):
        result = self.reader.markers(name='unrecorded-skill')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['count_basis'], 'returned_recorded_markers')
        self.assertEqual(result['coverage'], 'recorded_markers_only')
        self.assertTrue(result['partial'])
        self.assertTrue(result['uncaptured_triggers_possible'])
        self.assertEqual(result['effect_assessment'], 'not_performed')
        self.assertEqual(result['current_verification'], 'not_performed')
        self.assertEqual(result['freshness'], 'unknown')

    def test_project_filter_uses_recorded_marker_context_and_cli(self):
        self.put_metadata(2, {'trace_markers': [{'kind': 'skill', 'name': 'obsidian', 'event': 'invocation_requested'}],
                              'trace_context': {'cwd': '/synthetic/selected', 'basis': 'recorded_context'}})
        result = self.reader.markers(project='/synthetic/selected')
        self.assertEqual([item['message_index'] for item in result['items']], [2])
        self.assertEqual(result['items'][0]['cwd'], '/synthetic/selected')
        self.assertEqual(self.reader.markers(project='/synthetic/missing')['items'], [])
        cli = self.cli('--project', '/synthetic/selected')
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['count'], 1)

    def test_paging_requires_explicit_revision_and_retains_stable_order(self):
        first = self.reader.markers(limit=1)
        self.assertTrue(first['has_more'])
        self.assertEqual(first['next_offset'], 1)
        with self.assertRaisesRegex(ValueError, 'index_revision_required'):
            self.reader.markers(limit=1, offset=1)
        items = list(first['items'])
        page = first
        while page['next_offset'] is not None:
            page = self.reader.markers(limit=1, offset=page['next_offset'], index_revision=first['index_revision'])
            items.extend(page['items'])
        self.assertEqual(items, self.reader.markers()['items'])
        self.assertEqual([item['message_index'] for item in items], [6, 5, 4, 2])

    def test_revision_changes_before_or_during_query_are_rejected(self):
        revision = self.reader.markers()['index_revision']
        with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
            self.reader.markers(index_revision='not-current')
        with patch.object(self.reader, '_HistoryReader__revision', side_effect=[revision, 'changed']):
            with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
                self.reader.markers(index_revision=revision)

    def test_cli_filter_and_explicit_revision_page(self):
        filtered = self.cli('--name', 'obsidian', '--kind', 'skill', '--session', 'marker-session')
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        item = json.loads(filtered.stdout)['items'][0]
        self.assertEqual(item['message_index'], 2)
        self.assertEqual(item['call_id'], 'native-call-1')
        first = self.cli('--limit', '1')
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        missing = self.cli('--limit', '1', '--offset', '1')
        self.assertEqual(missing.returncode, 2)
        self.assertIn('index_revision_required', missing.stderr)
        second = self.cli('--limit', '1', '--offset', '1', '--index-revision', result['index_revision'])
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)['items'][0]['message_index'], 5)

    def test_sql_filters_are_literal_and_partial_capture_is_always_explicit(self):
        self.put_metadata(0, {'trace_markers': [
            {'kind': 'skill', 'event': 'agent_declared', 'name': "x' OR 1=1 --", 'evidence_origin': 'agent_marker'},
            {'kind': 'output_style', 'event': 'context_injected', 'name': 'style', 'evidence_origin': 'recorded_prompt'}]})
        literal = self.reader.markers(name="x' OR 1=1 --", kind='skill')
        self.assertEqual(len(literal['items']), 1)
        self.assertEqual(literal['items'][0]['message_index'], 0)
        self.assertEqual(self.reader.markers(name='style', kind='skill')['items'], [])
        self.assertEqual(self.reader.markers(session_id='missing-session')['items'], [])
        self.assertTrue(literal['partial'])

    def test_malformed_metadata_unknown_kinds_and_non_arrays_are_ignored(self):
        for raw in ('{bad json', '{"trace_markers": {"kind":"skill"}}',
                    {'trace_markers': ['not-json', None, {'kind': 'other', 'event': 'x', 'name': 'bad'},
                                       {'kind': 'skill', 'event': {}, 'name': 'bad'}]}):
            with self.subTest(raw=raw):
                self.put_metadata(0, raw)
                self.assertFalse(any(item['message_index'] == 0 for item in self.reader.markers()['items']))

    def test_fields_are_whitelisted_bounded_and_redacted_before_clipping(self):
        secret = 'SYNTHETIC_MARKER_SECRET'
        self.put_metadata(0, {'trace_markers': [{'kind': 'skill', 'event': 'agent_declared',
            'name': 'bounded', 'path': 'A' * 500 + ' token=' + secret, 'version': 'V' * 300,
            'name_truncated': True, 'evidence_origin': 'agent_marker', 'body': 'PRIVATE_METADATA_BODY'}],
            'raw_ref': {'line_no': 2, 'record_id': 'record-1', 'json_pointer': '/message/content/0', 'body': 'PRIVATE_REF_BODY'},
            'tool_call_id': 'token=' + secret, 'trace_context': {'cwd': '/recorded/context',
                'turn_id': 'turn-1', 'basis': 'recorded_context', 'body': 'PRIVATE_CONTEXT_BODY'},
            'body': 'PRIVATE_REASONING_METADATA'})
        item = self.reader.markers(name='bounded')['items'][0]
        self.assertEqual(item['cwd'], '/recorded/context')
        self.assertEqual(item['turn_id'], 'turn-1')
        self.assertEqual(item['raw_ref']['json_pointer'], '/message/content/0')
        self.assertLessEqual(len(item['path']), 512)
        self.assertLessEqual(len(item['version']), 128)
        self.assertTrue(item['metadata_truncated'])
        self.assertTrue({'name', 'path', 'version'} <= set(item['truncated_fields']))
        self.assertNotIn(secret, json.dumps(item))
        self.assertTrue(item['path'].endswith('token=[REDA'))
        self.assertEqual(item['call_id'], 'token=[REDACTED]')
        self.assertFalse(any('PRIVATE_' in value for value in item.values() if isinstance(value, str)))

    def test_oversized_metadata_is_omitted_with_explicit_budget(self):
        self.put_metadata(0, {'trace_markers': [{'kind': 'skill', 'event': 'agent_declared', 'name': 'oversized'}],
                              'extra': 'X' * MAX_METADATA_CHARS})
        result = self.reader.markers(name='oversized')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['metadata_budget_chars'], MAX_METADATA_CHARS)
        self.assertEqual(result['oversized_metadata_policy'], 'omitted')
        self.assertTrue(result['uncaptured_triggers_possible'])

    def test_invalid_arguments_closed_reader_and_unsupported_sources_fail_explicitly(self):
        for args, message in (({'limit': True}, 'invalid_marker_limit'),
                              ({'limit': 101}, 'invalid_marker_limit'),
                              ({'offset': -1}, 'invalid_marker_offset'),
                              ({'offset': 100001, 'index_revision': self.reader.markers()['index_revision']}, 'invalid_marker_offset'),
                              ({'name': ''}, 'invalid_marker_name'),
                              ({'name': 'x' * 129}, 'invalid_marker_name'),
                              ({'kind': 'other'}, 'invalid_marker_kind'),
                              ({'session_id': True}, 'invalid_marker_session')):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, message):
                self.reader.markers(**args)
        with self.assertRaisesRegex(ValueError, 'markers_source_unsupported'):
            read_markers(SimpleNamespace(source='opencode'))
        with HistoryReader('gemini', self.source, self.root / 'gemini-cache') as reader:
            with self.assertRaisesRegex(ValueError, 'markers_source_unsupported'):
                reader.markers()
        self.reader.close()
        with self.assertRaisesRegex(ValueError, 'reader_closed'):
            self.reader.markers()

    def test_claude_native_skill_keeps_call_id_block_pointer_and_source(self):
        source = self.root / 'claude'
        source.mkdir()
        path = source / 'native.jsonl'
        records = [{'type': 'assistant', 'uuid': 'record-native', 'sessionId': 'claude-session',
            'cwd': '/synthetic/claude', 'timestamp': '2026-10-10T00:00:00Z',
            'message': {'role': 'assistant', 'content': [
                {'type': 'thinking', 'thinking': 'PRIVATE_CLAUDE_THINKING'},
                {'type': 'tool_use', 'name': 'Skill', 'id': 'claude-skill-call', 'input': {'skill': 'obsidian'}}]}}]
        path.write_text('\n'.join(json.dumps(record) for record in records) + '\n')
        original = path.read_bytes()
        with HistoryReader('claude', source, self.root / 'claude-cache') as reader:
            reader.refresh()
            result = reader.markers(name='obsidian')
        self.assertEqual(len(result['items']), 1)
        item = result['items'][0]
        self.assertEqual(item['source'], 'claude')
        self.assertEqual(item['session_id'], 'claude-session')
        self.assertEqual(item['message_index'], 1)
        self.assertEqual(item['call_id'], 'claude-skill-call')
        self.assertEqual(item['raw_ref']['record_id'], 'record-native')
        self.assertEqual(item['raw_ref']['json_pointer'], '/message/content/1')
        self.assertNotIn('PRIVATE_CLAUDE_THINKING', json.dumps(result))
        self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
