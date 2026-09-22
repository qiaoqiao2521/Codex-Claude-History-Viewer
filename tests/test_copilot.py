"""Synthetic Copilot parser contracts; no account, model or private store needed."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from history_core.copilot import parse_copilot_session_bytes, parse_copilot_session_file


def encode(events):
    return ('\n'.join(json.dumps(event) for event in events) + '\n').encode()


def event(kind, event_id, **data):
    return {'type': kind, 'id': event_id, 'timestamp': '2026-09-22T10:00:00Z', 'data': data}


def start(**changes):
    data = {'sessionId': 'synthetic-copilot', 'version': 1, 'context': {'cwd': '/tmp/synthetic-project', 'gitRoot': '/tmp'}}
    data.update(changes)
    return event('session.start', 'start', **data)


class CopilotParserTests(unittest.TestCase):
    def test_messages_tools_failure_and_original_refs(self):
        events = [start(), event('user.message', 'u', content='Fix parser'),
                  event('assistant.message', 'a', content='Checking now', toolRequests=[{'toolCallId': 'c', 'name': 'bash', 'arguments': {'command': 'false'}}]),
                  event('tool.execution_start', 'call', toolCallId='c', toolName='bash', arguments={'command': 'false'}),
                  event('tool.execution_complete', 'result', toolCallId='c', success=False, result={'content': 'failed', 'exitCode': 2}),
                  event('assistant.message', 'done', content='Failure remains.'),
                  event('session.shutdown', 'stop', currentTokens=777, tokenDetails={'output': {'tokenCount': 99}})]
        parsed = parse_copilot_session_bytes(encode(events))
        self.assertEqual(parsed['id'], 'synthetic-copilot')
        self.assertEqual(parsed['cwd'], '/tmp/synthetic-project')
        self.assertEqual(parsed['message_count'], 3)
        self.assertEqual(parsed['title'], 'Fix parser')
        calls = [row for row in parsed['messages'] if row['kind'] == 'tool_use']
        self.assertEqual(len(calls), 1, 'toolRequests must not double-count actual execution')
        self.assertEqual(calls[0]['tool_args'], {'command': 'false'})
        result = next(row for row in parsed['messages'] if row['kind'] == 'tool_result')
        self.assertEqual(result['tool_name'], 'bash')
        self.assertEqual(result['tool_call_id'], 'c')
        self.assertEqual(result['tool_result_text'], 'failed')
        self.assertTrue(result['tool_result_error'])
        self.assertEqual(result['tool_result_exit_codes'], [2])
        self.assertEqual(result['raw_ref'], {'line_no': 5, 'record_id': 'result'})
        self.assertIsNone(parsed['usage'])
        self.assertEqual(parsed['usage_status'], 'unknown_counter_semantics')

    def test_generic_success_is_not_exit_zero_or_text_exit_proof(self):
        for payload in [dict(success=True, result={'content': 'Exit code: 0', 'code': 0}), dict(result={'content': 'okay', 'status': 200})]:
            parsed = parse_copilot_session_bytes(encode([start(), event('tool.execution_complete', 'done', **payload)]))
            result = parsed['messages'][0]
            self.assertEqual(result['tool_result_exit_codes'], [])
            self.assertEqual(result['tool_name'], 'tool')
            self.assertEqual(result['tool_result_error'], False if 'success' in payload else None)

    def test_native_exit_fields_and_error_outcome_are_independent(self):
        rows = [event('tool.execution_complete', 'good', success=True, result={'exit_code': 0}),
                event('tool.execution_complete', 'contradiction', success=True, result={'exitCode': 7}),
                event('tool.execution_complete', 'bool', result={'exit_code': True}),
                event('tool.execution_complete', 'failure', success=False, result={'exit_code': 0})]
        parsed = parse_copilot_session_bytes(encode([start(), *rows]))
        self.assertEqual([m['tool_result_exit_codes'] for m in parsed['messages']], [[0], [7], [], [0]])
        self.assertEqual([m['tool_result_error'] for m in parsed['messages']], [False, True, None, True])

    def test_duplicate_event_id_first_occurrence_and_parent_locator(self):
        user = event('user.message', 'same', content='original')
        user['parentId'] = 'start'
        replay = event('user.message', 'same', content='changed replay')
        parsed = parse_copilot_session_bytes(encode([start(), user, user, replay]))
        self.assertEqual(parsed['message_count'], 1)
        self.assertEqual(parsed['duplicate_event_count'], 2)
        self.assertEqual(parsed['messages'][0]['text'], 'original')
        self.assertEqual(parsed['messages'][0]['raw_ref'], {'line_no': 2, 'record_id': 'same', 'parent_id': 'start'})
        self.assertNotIn('changed replay', parsed['search_blob'])

    def test_unkeyed_events_remain_distinct_and_partial_tail_is_visible(self):
        user = {'type': 'user.message', 'data': {'content': 'unkeyed'}}
        parsed = parse_copilot_session_bytes(encode([start(), user, user]) + b'{"malformed": SECRET_WITHOUT_LEAK')
        self.assertEqual(parsed['message_count'], 2)
        self.assertEqual(parsed['malformed_line_count'], 1)
        self.assertEqual(parsed['messages'][-1]['raw_ref']['line_no'], 4)
        self.assertNotIn('SECRET_WITHOUT_LEAK', parsed['search_blob'])
        self.assertIn('skipped 1 malformed', parsed['search_blob'])

    def test_no_metadata_or_opaque_credentials_in_transcript(self):
        events = [start(credentials={'token': 'HEADER_SECRET'}),
                  event('session.info', 'info', message='TRACE_SECRET'),
                  event('hook.end', 'hook', output='HOOK_SECRET'),
                  event('assistant.message', 'a', content='visible answer', transformedContent='TRANSFORMED_SECRET', encryptedContent='ENCRYPTED_SECRET', reasoningOpaque='OPAQUE_SECRET', toolTelemetry={'authorization': 'TELEMETRY_SECRET'}),
                  event('tool.execution_complete', 't', success=True, result={'content': 'visible output', 'auth': {'token': 'RESULT_SECRET'}}, toolTelemetry={'key': 'TOOL_SECRET'})]
        parsed = parse_copilot_session_bytes(encode(events))
        serialized = json.dumps(parsed)
        self.assertNotIn('SECRET', serialized)
        self.assertIn('visible answer', parsed['search_blob'])
        self.assertIn('visible output', parsed['search_blob'])
        self.assertEqual(len(parsed['messages']), 2)

    def test_only_explicit_absolute_session_start_cwd(self):
        for header in [start(context={'gitRoot': '/repo'}), start(context={'cwd': 'relative'}), start(context={})]:
            parsed = parse_copilot_session_bytes(encode([header]), '/tempting/workspace/events.jsonl')
            self.assertIsNone(parsed['cwd'])
        self.assertEqual(parse_copilot_session_bytes(encode([start(context={}, cwd='/explicit')]))['cwd'], '/explicit')

    def test_require_valid_session_identity_and_reject_mixed_sessions(self):
        for rows in [[], [event('user.message', 'u', content='no header')], [start(sessionId=None)], [start(), event('session.start', 'second', sessionId='other')]]:
            with self.assertRaises(ValueError):
                parse_copilot_session_bytes(encode(rows))

    def test_textual_content_blocks_and_results_exclude_binary_metadata(self):
        rows = [event('user.message', 'u', content=[{'type': 'text', 'text': 'visible'}, {'type': 'image', 'data': 'BINARY_SECRET'}]),
                event('tool.execution_complete', 't', result={'content': 'summary', 'detailedContent': 'details', 'stderr': 'error detail', 'error': {'message': 'native error'}, 'blob': 'BINARY_SECRET'})]
        parsed = parse_copilot_session_bytes(encode([start(), *rows]))
        self.assertEqual(parsed['messages'][0]['text'], 'visible')
        self.assertEqual(parsed['messages'][1]['tool_result_text'], 'summary\ndetails\nerror detail\nnative error')
        self.assertNotIn('BINARY_SECRET', json.dumps(parsed))

    def test_unknown_or_malformed_event_shapes_do_not_break_valid_recording(self):
        rows = [start(), {'type': {'unexpected': 'shape'}, 'data': {}}, event('assistant.message', 'empty', content=None), event('credentials.refresh', 'auth', token='SECRET')]
        parsed = parse_copilot_session_bytes(encode(rows))
        self.assertEqual(parsed['messages'], [])
        self.assertNotIn('SECRET', json.dumps(parsed))

    def test_explicit_error_payload_without_success_flag_remains_failure(self):
        rows = [event('tool.execution_complete', 'one', error={'message': 'explicit failure'}), event('tool.execution_complete', 'two', result={'error': {'message': 'native failure'}})]
        parsed = parse_copilot_session_bytes(encode([start(), *rows]))
        self.assertTrue(all(row['tool_result_error'] is True for row in parsed['messages']))
        self.assertTrue(all(row['tool_result_exit_codes'] == [] for row in parsed['messages']))

    def test_file_entrypoint_is_read_only_and_missing_is_none(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            path.write_bytes(encode([start(), event('user.message', 'u', content='Synthetic only')]))
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            before_names = list(Path(temporary).iterdir())
            parsed = parse_copilot_session_file(path)
            self.assertEqual(parsed['file_path'], str(path))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertEqual(list(Path(temporary).iterdir()), before_names)
            self.assertIsNone(parse_copilot_session_file(Path(temporary) / 'missing.jsonl'))


if __name__ == '__main__':
    unittest.main()
