"""Public tool-reuse behavior against synthetic recordings, never private logs."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from history_core import HistoryReader, service
from history_core.sources import Indexer


REPO = Path(__file__).resolve().parents[1]


class ToolReuseBriefTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'sessions'
        self.source.mkdir()
        self.cache = self.root / 'cache'

    def record(self, sid, events, stamp=1791590400000):
        rows = [{'type': 'session_meta', 'timestamp': stamp,
                 'payload': {'id': sid, 'cwd': '/synthetic'}}]
        rows.extend({'type': 'response_item', 'timestamp': stamp + n,
                     'payload': event} for n, event in enumerate(events, 1))
        path = self.source / (sid + '.jsonl')
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows))
        return path

    @staticmethod
    def message(text, role='user'):
        return {'type': 'message', 'role': role,
                'content': [{'type': 'input_text', 'text': text}]}

    @staticmethod
    def call(command, cid='call-one'):
        return {'type': 'function_call', 'name': 'shell_command', 'call_id': cid,
                'arguments': json.dumps({'command': command})}

    @staticmethod
    def result(output, cid='call-one', code=0):
        return {'type': 'function_call_output', 'call_id': cid,
                'output': {'output': output, 'metadata': {'exit_code': code}}}

    def reader(self):
        reader = HistoryReader('codex', self.source, self.cache)
        self.addCleanup(reader.close)
        reader.refresh()
        return reader

    def test_old_tool_beats_recent_title_mentions_without_changing_default_search(self):
        self.record('old-tool', [self.message('Check artifact'),
                                self.call('readback verifier artifact.bin'),
                                self.result('READBACK_OK')], stamp=1790816400000)
        for n in range(3):
            self.record('new-chat-%d' % n, [self.message('readback verifier question')],
                        stamp=1791590400000 + n * 10000)
        reader = self.reader()
        normal = reader.search(query='readback verifier', limit=3)
        brief = reader.search(query='readback verifier', limit=3, brief=True)
        self.assertEqual([item['id'] for item in normal['items']],
                         ['new-chat-2', 'new-chat-1', 'new-chat-0'])
        self.assertEqual(brief['items'][0]['id'], 'old-tool')
        self.assertEqual(len(brief['items']), 3)
        self.assertTrue(brief['has_more'])
        self.assertGreater(brief['items'][0]['tool_match_terms'], 0)

    def test_tool_relevance_pages_stay_complete_without_a_500_candidate_cap(self):
        for n in range(503):
            events = [self.message('Check artifact')]
            if n % 2:
                events += [self.call('readback verifier'), self.result('checked')]
            else:
                events += [self.message('readback verifier mention', role='assistant')]
            self.record('s%03d' % n, events)
        reader = self.reader()
        ids, offset, revision = [], 0, None
        while True:
            page = reader.search(query='readback verifier', brief=True, limit=100,
                                 offset=offset, index_revision=revision)
            revision = page['index_revision']
            self.assertLessEqual(len(page['items']), 100)
            ids.extend(item['id'] for item in page['items'])
            if not page['has_more']:
                break
            offset = page['next_offset']
        self.assertEqual(len(ids), 503)
        self.assertEqual(len(set(ids)), 503)
        self.assertEqual(ids[:251], ['s%03d' % n for n in range(1, 503, 2)])

    def test_short_result_keeps_error_header_and_explicit_status(self):
        self.record('short', [self.message('Check artifact'), self.call('check_artifact'),
                              self.result('x' * 55 + ' READBACK_OK', code=7)])
        snippet = self.reader().search(query='READBACK_OK', brief=True)['items'][0]['snippets'][0]
        self.assertIn('Status: error', snippet['text'])
        self.assertIn('Exit code: 7', snippet['text'])
        self.assertFalse(snippet['truncated'])
        self.assertFalse(snippet['has_more_before'])
        self.assertFalse(snippet['has_more_after'])
        self.assertEqual(snippet['kind'], 'tool_result')
        self.assertEqual(snippet['call_id'], 'call-one')
        self.assertIsInstance(snippet['ts_ms'], int)
        self.assertEqual(snippet['tool_summary']['exit_status'], 'error')
        self.assertEqual(snippet['tool_summary']['exit_code'], 7)

    def test_long_result_discloses_real_window_and_keeps_status(self):
        self.record('long', [self.message('Check artifact'), self.call('check_artifact'),
                             self.result('x' * 900 + ' READBACK_OK', code=7)])
        item = self.reader().search(query='READBACK_OK', brief=True)['items'][0]
        snippet = item['snippets'][0]
        self.assertTrue(snippet['truncated'])
        self.assertTrue(snippet['has_more_before'])
        self.assertFalse(snippet['has_more_after'])
        self.assertGreater(snippet['excerpt_start'], 0)
        self.assertEqual(snippet['excerpt_end'], snippet['text_chars'])
        self.assertEqual(snippet['excerpt_offset_basis'], 'indexed_text')
        self.assertLessEqual(len(snippet['text']), 240)
        self.assertEqual(snippet['tool_summary']['exit_status'], 'error')
        self.assertEqual(snippet['tool_summary']['exit_code'], 7)

    def test_marker_without_recorded_exit_status_stays_unknown(self):
        result = self.result('READBACK_OK')
        result['output'].pop('metadata')
        self.record('unknown', [self.message('Check artifact'), self.call('check_artifact'), result])
        snippet = self.reader().search(query='READBACK_OK', brief=True)['items'][0]['snippets'][0]
        self.assertEqual(snippet['tool_summary']['exit_status'], 'unknown')
        self.assertIsNone(snippet['tool_summary']['exit_code'])

    def test_matched_window_masks_a_secret_that_starts_before_the_window(self):
        self.record('secret-window', [self.message('Check artifact'), self.call('check_artifact'),
                                     self.result('token=' + 'A' * 400 + 'needle' + 'B' * 400)])
        item = self.reader().search(query='needle', brief=True)['items'][0]
        snippet = item['snippets'][0]
        self.assertTrue(snippet['has_more_before'])
        self.assertTrue(snippet['has_more_after'])
        self.assertEqual(snippet['text'], '*' * 240)
        self.assertNotIn('AAAA', json.dumps(item))
        self.assertNotIn('BBBB', json.dumps(item))

    def test_related_window_and_call_id_are_masked_before_display(self):
        cid = 'ghp_' + 'F' * 40
        self.record('secret-related', [self.message('Check artifact'),
                                      self.call('sha256sum artifact.bin', cid=cid),
                                      self.result('password=' + 'A' * 600, cid=cid)])
        item = self.reader().search(query='sha256sum', brief=True)['items'][0]
        self.assertEqual(item['snippets'][0]['call_id'], '[REDACTED]')
        self.assertEqual(item['related_tool_messages'][0]['call_id'], '[REDACTED]')
        self.assertNotIn(cid, json.dumps(item))
        self.assertNotIn('AAAA', json.dumps(item))
        self.assertTrue(item['related_tool_messages'][0]['has_more_after'])

    def test_nul_inside_a_long_message_keeps_true_source_offsets(self):
        self.record('nul', [self.message('Check artifact'), self.call('check_artifact'),
                            self.result('needle\x00' + 'x' * 600)])
        snippet = self.reader().search(query='needle', brief=True)['items'][0]['snippets'][0]
        self.assertIn('needle', snippet['text'])
        self.assertTrue(snippet['has_more_after'])
        self.assertGreater(snippet['text_chars'], 600)
        self.assertLess(snippet['excerpt_end'], snippet['text_chars'])

    def test_oversized_call_id_is_bounded_for_display_but_still_pairs(self):
        cid = 'c' * 100000
        self.record('large-id', [self.message('Check artifact'),
                                self.call('PUBLIC_LOOKUP', cid=cid), self.result('done', cid=cid)])
        item = self.reader().search(query='PUBLIC_LOOKUP', brief=True)['items'][0]
        for message in [item['snippets'][0], item['related_tool_messages'][0]]:
            self.assertEqual(len(message['call_id']), 128)
            self.assertTrue(message['call_id_truncated'])
        self.assertLess(len(json.dumps(item)), 3000)

    def test_input_and_result_queries_include_only_the_same_call_counterpart(self):
        self.record('pairs', [self.message('Check artifact'),
                              self.call('sha256sum artifact.bin', cid='wanted'),
                              self.call('unrelated_operation', cid='other'),
                              self.result('unrelated output', cid='other'),
                              self.result('12ab artifact.bin', cid='wanted')])
        reader = self.reader()
        for query, related_kind, related_text in (
                ('sha256sum', 'tool_result', '12ab artifact.bin'),
                ('12ab', 'tool_use', 'sha256sum artifact.bin')):
            with self.subTest(query=query):
                item = reader.search(query=query, brief=True)['items'][0]
                self.assertEqual(len(item['snippets']), 1)
                self.assertEqual(len(item['related_tool_messages']), 1)
                related = item['related_tool_messages'][0]
                self.assertEqual(related['call_id'], 'wanted')
                self.assertEqual(related['kind'], related_kind)
                self.assertIn(related_text, related['text'])
                self.assertEqual(related['related_to_message_indexes'],
                                 [item['snippets'][0]['message_index']])
                self.assertFalse(item['related_tool_messages_truncated'])

    def test_missing_call_id_does_not_guess_adjacent_messages(self):
        call = self.call('sha256sum artifact.bin')
        result = self.result('12ab artifact.bin')
        call.pop('call_id'); result.pop('call_id')
        self.record('missing-id', [self.message('Check artifact'), call, result])
        item = self.reader().search(query='sha256sum', brief=True)['items'][0]
        self.assertIsNone(item['snippets'][0]['call_id'])
        self.assertEqual(item['related_tool_messages'], [])

    def test_related_messages_are_bounded_and_do_not_displace_matching_snippets(self):
        self.record('chunks', [self.message('Check artifact'), self.call('sha256sum artifact.bin')]
                    + [self.result('chunk-%d' % n) for n in range(5)])
        item = self.reader().search(query='sha256sum', brief=True)['items'][0]
        self.assertEqual(len(item['snippets']), 1)
        self.assertEqual(len(item['related_tool_messages']), 3)
        self.assertTrue(item['related_tool_messages_truncated'])
        self.assertEqual([entry['message_index'] for entry in item['related_tool_messages']], [2, 3, 4])

    def test_short_chinese_and_cross_word_queries_keep_literal_and_semantics(self):
        self.record('chinese', [self.message('检查文件'), self.call('回读 ' + 'x' * 650 + ' 校验'),
                                self.result('完成')])
        reader = self.reader()
        for query in ('回读', '回读 校验'):
            with self.subTest(query=query):
                item = reader.search(query=query, brief=True)['items'][0]
                self.assertIn('回读', item['snippets'][0]['text'])
                self.assertTrue(item['snippets'][0]['has_more_after'])
                self.assertEqual(item['related_tool_messages'][0]['kind'], 'tool_result')

    def test_brief_candidate_budget_failure_is_explicit(self):
        path = self.record('budget', [self.message('Check artifact'), self.call('readback verifier')])
        cache = self.root / 'direct-cache'; cache.mkdir()
        idx = Indexer(self.source, cache, 'codex')
        self.addCleanup(idx.conn.close)
        idx.scan_sessions()
        with patch('history_core.reuse.query_budget', side_effect=sqlite3.OperationalError('interrupted')):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'interrupted'):
                service.search(idx, query='readback verifier', brief=True)
        self.assertTrue(path.exists())

    def test_real_candidate_budget_interrupt_recovers_for_the_next_read(self):
        self.record('budget', [self.message('Check artifact'), self.call('readback verifier')])
        cache = self.root / 'direct-cache'; cache.mkdir()
        idx = Indexer(self.source, cache, 'codex')
        self.addCleanup(idx.conn.close)
        idx.scan_sessions()
        with idx.conn:
            idx.conn.executemany('INSERT INTO messages(session_id,ts_ms,role,kind,text) VALUES(?,?,?,?,?)',
                                 [('budget', n + 1791590401000, 'assistant', 'reasoning_summary',
                                   'readback verifier unexecuted thought') for n in range(4000)])
        calls = 0

        def clock():
            nonlocal calls
            calls += 1
            return calls * 3

        with patch('history_core.reuse.time.monotonic', side_effect=clock):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'interrupted'):
                service.search(idx, query='readback verifier', brief=True)
        self.assertGreater(calls, 1)
        page = service.search(idx, query='readback verifier', brief=True)
        self.assertEqual(page['items'][0]['id'], 'budget')
        self.assertEqual(len(page['items'][0]['snippets']), 1)

    def test_fresh_cli_fixture_returns_paired_evidence_without_source_writes(self):
        path = self.record('cli', [self.message('检查文件'), self.call('sha256sum artifact.bin'),
                                  self.result('12ab artifact.bin', code=7)])
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        prefix = [sys.executable, '-B', '-m', 'history_core', '--source', 'codex',
                  '--source-path', str(self.source), '--data-dir', str(self.cache)]
        for command in (['refresh'], ['search', '--query', 'sha256sum', '--brief', '--limit', '3']):
            process = subprocess.run(prefix + command, cwd=REPO, capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            response = json.loads(process.stdout)
        self.assertEqual(response['source'], 'codex')
        self.assertTrue(response['index_revision'])
        related = response['items'][0]['related_tool_messages'][0]
        self.assertIn('12ab artifact.bin', related['text'])
        self.assertEqual(related['tool_summary']['exit_status'], 'error')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
