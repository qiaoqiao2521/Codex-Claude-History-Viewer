"""Search-to-message reads stay bounded, public and revision-bound."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from history_core import HistoryReader
from history_core.messages import read_message

REPO = Path(__file__).resolve().parents[1]


class MessageReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.path = self.source / 'cross-day.jsonl'
        records = [
            {'type': 'session_meta', 'timestamp': '2026-10-01T00:00:00Z',
             'payload': {'id': 'cross-day', 'cwd': '/synthetic/reuse'}},
            {'type': 'response_item', 'timestamp': '2026-10-01T00:00:01Z',
             'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Inspect the artifact'}]}},
            {'type': 'response_item', 'timestamp': '2026-10-01T00:00:02Z',
             'payload': {'type': 'reasoning', 'summary': [{'type': 'summary_text', 'text': 'PRIVATE_REASONING'}]}},
            {'type': 'response_item', 'timestamp': '2026-10-02T00:00:00Z',
             'payload': {'type': 'function_call', 'name': 'exec_command', 'call_id': 'paired-fixture',
                         'arguments': json.dumps({'cmd': 'verify artifact'})}},
            {'type': 'response_item', 'timestamp': '2026-10-02T00:00:01Z',
             'payload': {'type': 'function_call_output', 'call_id': 'paired-fixture',
                         'output': 'Exit code: 7\nWall time: 0.1 seconds\nOutput:\n' + 'Z'*4300 + ' PUBLIC_FAILED'}},
        ]
        self.path.write_text('\n'.join(json.dumps(x) for x in records) + '\n')
        self.original = self.path.read_bytes()
        self.reader = HistoryReader('codex', self.source, self.root/'cache')
        self.addCleanup(self.reader.close)
        self.reader.refresh()

    def tearDown(self):
        if not getattr(self, 'changed_source', False):
            self.assertEqual(self.path.read_bytes(), self.original)

    def revision(self):
        return self.reader.search(query='PUBLIC_FAILED', brief=True)['index_revision']

    def test_search_revision_expands_cross_day_message_in_bounded_pages(self):
        page = self.reader.search(query='PUBLIC_FAILED', brief=True)
        match = page['items'][0]['snippets'][0]
        first = self.reader.message('cross-day', match['message_index'], index_revision=page['index_revision'])
        self.assertEqual(first['kind'], 'tool_result')
        self.assertEqual(first['call_id'], 'paired-fixture')
        self.assertEqual(first['tool_summary']['exit_code'], 7)
        self.assertEqual(first['tool_summary']['exit_status'], 'error')
        self.assertEqual(first['text_offset_basis'], 'indexed_text')
        self.assertEqual(len(first['text']), first['body_page_chars'])
        self.assertFalse(first['has_more_before'])
        self.assertTrue(first['has_more_after'])
        self.assertEqual(first['freshness'], 'unknown')
        self.assertEqual(first['current_verification'], 'not_performed')
        chunks = [first['text']]
        current = first
        while current['next_text_offset'] is not None:
            current = self.reader.message('cross-day', match['message_index'],
                index_revision=page['index_revision'], text_offset=current['next_text_offset'])
            self.assertLessEqual(len(current['text']), current['body_page_chars'])
            self.assertTrue(current['has_more_before'])
            chunks.append(current['text'])
        self.assertFalse(current['has_more_after'])
        self.assertEqual(len(''.join(chunks)), first['char_count'])
        self.assertIn('PUBLIC_FAILED', ''.join(chunks))

    def test_private_message_still_has_absolute_index_but_cannot_expand(self):
        with self.assertRaisesRegex(ValueError, 'message_not_public'):
            self.reader.message('cross-day', 1, index_revision=self.revision())

    def test_refresh_invalidates_old_search_locator(self):
        old = self.revision()
        self.changed_source = True
        with self.path.open('a') as out:
            out.write(json.dumps({'type': 'response_item', 'timestamp': '2026-10-03T00:00:00Z',
                'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'A later correction'}]}})+'\n')
        self.reader.refresh()
        with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
            self.reader.message('cross-day', 3, index_revision=old)

    def test_missing_revision_invalid_offset_and_missing_message_are_errors(self):
        revision = self.revision()
        for index, offset, error in ((True, 0, 'invalid_message_index'), (3, True, 'invalid_text_offset'),
                                     (3, 100000, 'text_offset_out_of_range'), (99, 0, 'message_not_found')):
            with self.subTest(index=index, offset=offset), self.assertRaisesRegex(ValueError, error):
                self.reader.message('cross-day', index, index_revision=revision, text_offset=offset)
        with self.assertRaisesRegex(ValueError, 'index_revision_required'):
            self.reader.message('cross-day', 3, index_revision='')

    def test_unindexed_source_does_not_fall_back_to_raw_native_database(self):
        with self.assertRaisesRegex(ValueError, 'message_evidence_source_unsupported'):
            read_message(SimpleNamespace(source='opencode'), 'cross-day', 3)

    def append_public(self, text, *, call_id=None):
        self.changed_source = True
        payload = {'type': 'message', 'role': 'user',
                   'content': [{'type': 'input_text', 'text': text}]}
        if call_id is not None:
            payload = {'type': 'function_call', 'name': 'exec_command',
                       'call_id': call_id, 'arguments': json.dumps({'cmd': text})}
        with self.path.open('a') as out:
            out.write(json.dumps({'type': 'response_item',
                'timestamp': '2026-10-03T00:00:00Z', 'payload': payload}) + '\n')
        self.reader.refresh()

    def test_secret_assignment_split_across_pages_and_arbitrary_offset_is_masked(self):
        secret = 'SYNTHETIC_VALUE_123456789'
        text = 'A'*1993 + '\n' + 'token=' + secret + '\nPUBLIC_END'
        self.append_public(text)
        revision = self.revision()
        first = self.reader.message('cross-day', 4, index_revision=revision)
        second = self.reader.message('cross-day', 4, index_revision=revision,
                                     text_offset=first['next_text_offset'])
        self.assertEqual(first['next_text_offset'], 2000)
        self.assertTrue(second['text'].startswith('*' * len(secret)))
        self.assertIn('PUBLIC_END', second['text'])
        arbitrary = self.reader.message('cross-day', 4, index_revision=revision, text_offset=2005)
        self.assertNotIn(secret[5:], arbitrary['text'])
        self.assertEqual(len(first['text'] + second['text']), len(text))

    def test_short_secrets_do_not_expand_page_budget(self):
        text = 'token=x\n' * 250
        self.append_public(text)
        result = self.reader.message('cross-day', 4, index_revision=self.revision())
        self.assertEqual(result['text'], 'token=*\n' * 250)
        self.assertEqual(len(result['text']), result['body_page_chars'])
        self.assertIsNone(result['next_text_offset'])

    def test_nul_does_not_hide_following_public_text(self):
        text = 'BEFORE\x00AFTER_NULL'
        self.append_public(text)
        result = self.reader.message('cross-day', 4, index_revision=self.revision())
        self.assertEqual(result['text'], text)
        self.assertEqual(result['char_count'], len(text))
        self.assertFalse(result['truncated'])

    def test_call_id_has_same_minimum_secret_masking_as_body(self):
        secret = 'SYNTHETIC_ID_SECRET'
        self.append_public('inspect only', call_id='token=' + secret)
        result = self.reader.message('cross-day', 4, index_revision=self.revision())
        self.assertEqual(result['call_id'], 'token=[REDACTED]')
        self.assertNotIn(secret, json.dumps(result))

    def test_long_call_id_is_explicitly_clipped_without_losing_the_message(self):
        self.append_public('inspect only', call_id='c' * 100000)
        result = self.reader.message('cross-day', 4, index_revision=self.revision())
        self.assertEqual(result['call_id'], 'c' * 128)
        self.assertTrue(result['call_id_truncated'])
        self.assertEqual(len(result['text']), result['body_page_chars'])
        self.assertTrue(result['has_more_after'])

    def test_cli_can_expand_search_without_activity_date_or_revision_conversion(self):
        prefix = [sys.executable, '-B', '-m', 'history_core', '--source', 'codex',
                  '--source-path', str(self.source), '--data-dir', str(self.root/'cache')]
        def run(*args):
            out = subprocess.run(prefix+list(args), cwd=REPO, capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout)
        page = run('search', '--query', 'PUBLIC_FAILED', '--brief')
        index = str(page['items'][0]['snippets'][0]['message_index'])
        result = run('message', 'cross-day', index, '--index-revision', page['index_revision'])
        self.assertEqual(result['index_revision'], page['index_revision'])
        self.assertEqual(result['source'], 'codex')
        self.assertEqual(result['call_id'], 'paired-fixture')
        second = run('message', 'cross-day', index, '--index-revision', page['index_revision'],
                     '--text-offset', str(result['next_text_offset']))
        self.assertTrue(second['has_more_before'])


if __name__ == '__main__':
    unittest.main()
