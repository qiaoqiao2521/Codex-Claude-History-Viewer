"""Native trigger evidence survives indexing without creating evaluation data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from history_core import HistoryReader
from history_core.sources import parse_codex_session_file, parse_claude_session_file
from history_core.trace_markers import LEARNING_OUTPUT_STYLE_PREFIX, DECLARED_MARKER_PREFIX


class TraceMarkerParserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, rows):
        source = self.root / name
        source.mkdir()
        path = source / 'fixture.jsonl'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return source, path

    def test_codex_actual_context_and_declaration_keep_native_locations(self):
        def message(role, text):
            return {'type': 'response_item', 'timestamp': '2026-10-10T00:00:00Z',
                    'payload': {'type': 'message', 'role': role, 'content': [{'type': 'input_text', 'text': text}]}}
        _, path = self.write('codex', [
            {'type': 'session_meta', 'payload': {'id': 'codex-markers', 'cwd': '/repo/original'}},
            message('developer', LEARNING_OUTPUT_STYLE_PREFIX + '\nSYNTHETIC_PRIVATE_CONTEXT'),
            message('user', LEARNING_OUTPUT_STYLE_PREFIX),
            {'type': 'turn_context', 'payload': {'cwd': '/repo/selected', 'turn_id': 'turn-2'}},
            message('assistant', DECLARED_MARKER_PREFIX + json.dumps({'name': 'example-skill', 'path': '/repo/skills/example/SKILL.md', 'version': '2'})),
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'Skill', 'call_id': 'native-skill', 'arguments': '{"skill":"another-skill"}'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'exec_command', 'arguments': '{"cmd":"cat /repo/skills/read-only/SKILL.md"}'}},
        ])
        raw = path.read_bytes()
        rows = parse_codex_session_file(path)['messages']
        tagged = [row for row in rows if row.get('trace_markers')]
        self.assertEqual([r['trace_markers'][0]['event'] for r in tagged], ['context_injected', 'agent_declared', 'invocation_requested'])
        self.assertEqual([r['raw_ref']['line_no'] for r in tagged], [2, 5, 6])
        self.assertEqual(tagged[1]['trace_context']['cwd'], '/repo/selected')
        self.assertEqual(tagged[1]['trace_context']['turn_id'], 'turn-2')
        self.assertEqual(tagged[2]['tool_call_id'], 'native-skill')
        self.assertEqual(path.read_bytes(), raw)

    def test_claude_sessionstart_and_skill_blocks_keep_call_and_block_identity(self):
        _, path = self.write('claude', [
            {'type': 'attachment', 'sessionId': 'claude-markers', 'cwd': '/repo/claude', 'uuid': 'hook-record',
             'attachment': {'type': 'hook_additional_context', 'hookEvent': 'SessionStart', 'content': [LEARNING_OUTPUT_STYLE_PREFIX + '\nPRIVATE_HOOK_CONTEXT']}},
            {'type': 'attachment', 'sessionId': 'claude-markers', 'attachment': {'type': 'hook_success', 'hookEvent': 'SessionStart', 'exitCode': 0}},
            {'type': 'assistant', 'sessionId': 'claude-markers', 'uuid': 'call-record', 'cwd': '/repo/current', 'message': {'role': 'assistant', 'content': [
                {'type': 'text', 'text': 'A normal discussion of another skill'},
                {'type': 'tool_use', 'id': 'skill-1', 'name': 'Skill', 'input': {'skill': 'project:example', 'args': 'NOT_MARKER_METADATA'}},
            ]}},
            {'type': 'user', 'sessionId': 'claude-markers', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'skill-1', 'content': 'Failure to load skill', 'is_error': True}]}},
        ])
        raw = path.read_bytes()
        rows = parse_claude_session_file(path)['messages']
        tagged = [row for row in rows if row.get('trace_markers')]
        self.assertEqual(len(tagged), 2)
        self.assertEqual(tagged[0]['trace_markers'][0]['evidence_origin'], 'recorded_hook_context')
        self.assertEqual(tagged[0]['raw_ref']['json_pointer'], '/attachment/content/0')
        self.assertEqual(tagged[1]['raw_ref']['json_pointer'], '/message/content/1')
        self.assertEqual(tagged[1]['trace_context']['cwd'], '/repo/current')
        self.assertEqual(tagged[1]['tool_call_id'], 'skill-1')
        self.assertEqual(rows[-1]['tool_call_id'], 'skill-1')
        self.assertEqual(tagged[1]['trace_markers'][0]['event'], 'invocation_requested')
        self.assertNotIn('NOT_MARKER_METADATA', json.dumps(tagged[1]['trace_markers']))
        self.assertEqual(path.read_bytes(), raw)

    def test_later_claude_hook_block_and_missing_codex_turn_id_are_precise(self):
        _, path = self.write('later-block', [
            {'type': 'attachment', 'sessionId': 'later-block', 'attachment': {
                'type': 'hook_additional_context', 'hookEvent': 'SessionStart',
                'content': ['Other hook context', LEARNING_OUTPUT_STYLE_PREFIX]}}
        ])
        rows = parse_claude_session_file(path)['messages']
        self.assertEqual(rows[0]['raw_ref']['json_pointer'], '/attachment/content/1')
        self.assertEqual(rows[0]['trace_markers'][0]['event'], 'context_injected')
        _, path = self.write('later-turn', [
            {'type': 'session_meta', 'payload': {'id': 'later-turn', 'cwd': '/repo/base'}},
            {'type': 'turn_context', 'payload': {'cwd': '/repo/old', 'turn_id': 'old-turn'}},
            {'type': 'turn_context', 'payload': {'cwd': '/repo/new'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': DECLARED_MARKER_PREFIX + '{"name":"turn-skill"}'}]}}
        ])
        row = parse_codex_session_file(path)['messages'][-1]
        self.assertEqual(row['trace_context']['cwd'], '/repo/new')
        self.assertIsNone(row['trace_context']['turn_id'])

    def test_refresh_restores_markers_in_formal_prior_cache_without_new_tables(self):
        for source, old_version in (('codex', 7), ('claude', 5)):
            with self.subTest(source=source):
                if source == 'codex':
                    rows = [{'type': 'session_meta', 'payload': {'id': 'cache-markers', 'cwd': '/repo/cache'}},
                            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': DECLARED_MARKER_PREFIX + '{"name":"cache-skill"}'}]}}]
                else:
                    rows = [{'type': 'assistant', 'sessionId': 'cache-markers', 'cwd': '/repo/cache', 'message': {'role': 'assistant', 'content': DECLARED_MARKER_PREFIX + '{"name":"cache-skill"}'}}]
                directory, path = self.write(source, rows)
                raw = path.read_bytes()
                cache = self.root / (source + '-cache')
                with patch('history_core.reader.parser_version', return_value=old_version):
                    with HistoryReader(source, directory, cache) as reader:
                        reader.refresh()
                import sqlite3
                database = next(cache.rglob('index.sqlite'))
                with sqlite3.connect(database) as conn:
                    before_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
                    conn.execute("UPDATE messages SET activity_meta_json='{}'")
                with HistoryReader(source, directory, cache) as reader:
                    before = reader.search(query='cache-skill')['index_revision']
                    reader.refresh()
                    after = reader.search(query='cache-skill')['index_revision']
                    self.assertNotEqual(before, after)
                with sqlite3.connect(database) as conn:
                    meta = json.loads(conn.execute('SELECT activity_meta_json FROM messages').fetchone()[0])
                    self.assertEqual(meta['trace_markers'][0]['name'], 'cache-skill')
                    self.assertEqual(before_tables, conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall())
                self.assertEqual(path.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
