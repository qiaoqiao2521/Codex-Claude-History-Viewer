import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from history_core.mcode import parse_mcode_session_bytes, parse_mcode_session_file
from history_core.mcode_review import mcode_review_snapshot
from history_core.sources import Indexer


class McodeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'sessions'
        self.folder = self.source / '2026/09/session'
        self.folder.mkdir(parents=True)
        self.cache = self.root / 'cache'
        self.cache.mkdir()
        self.path = self.folder / 'messages.jsonl'
        self.manifest = self.folder / 'manifest.json'
        self.header = {'schemaVersion': 1, 'sessionId': 'm1',
                       'paths': {'messages': '/must/not/read'}, 'parentSessionId': 'parent'}
        self.requirement = 'Original requirement ' + '完整需求' * 180
        self.rows = [
            self.row('u1', 'user', 3000, [{'type': 'text', 'text': self.requirement}]),
            self.row('a1', 'assistant', 2000, [
                {'type': 'thinking', 'thinking': 'PRIVATE_THOUGHT'},
                {'type': 'redactedThinking', 'data': 'PRIVATE_REDACTED'},
                {'type': 'text', 'text': 'PUBLIC RESPONSE <system-reminder>PRIVATE_REMINDER</system-reminder>'}]),
            self.row('call', 'assistant', 3000, [{'type': 'toolCall', 'id': 'tool1',
                      'name': 'write', 'arguments': {'file_path': 'result.txt', 'password': 'SENSITIVE_ARGUMENT'}}]),
            self.row('result', 'toolResult', 4000, [{'type': 'text', 'text': 'PUBLIC FAILURE'}],
                     toolCallId='tool1', isError=True),
            self.row('u2', 'user', 5000, [{'type': 'text', 'text': 'Correction: preserve the original format'}]),
            self.row('a2', 'assistant', None, [{'type': 'text', 'text': 'TIMESTAMP MISSING'}]),
            self.row('sys', 'system', 6000, [{'type': 'text', 'text': 'PRIVATE_SYSTEM'}]),
        ]
        self.write()
        self.indexer = Indexer(self.source, self.cache, 'mcode',
                               parse_file_fn=parse_mcode_session_file,
                               file_filter_fn=lambda path: path.name == 'messages.jsonl',
                               parser_version=1)
        self.addCleanup(self.indexer.conn.close)
        self.indexer.scan_sessions(build_audits=False)

    @staticmethod
    def row(identity, role, timestamp, content, **fields):
        return {'message_id': identity, 'turn_id': 'turn1',
                'message': {'role': role, 'timestamp': timestamp, 'content': content, **fields}}

    def write(self):
        self.manifest.write_text(json.dumps(self.header))
        self.path.write_text('\n'.join(json.dumps(row, ensure_ascii=False) for row in self.rows) + '\n')

    def snapshot(self):
        return mcode_review_snapshot(self.indexer, 'm1')

    def fingerprints(self):
        return [(hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for path in (self.path, self.manifest)]

    def test_public_snapshot_matches_ui_order_and_preserves_full_requirement(self):
        before = self.fingerprints()
        snapshot = self.snapshot()
        messages = snapshot['messages']
        cached = self.indexer.conn.execute(
            'SELECT role,kind,ts_ms,text FROM messages WHERE session_id=? ORDER BY ts_ms,id', ('m1',)).fetchall()
        self.assertEqual([m['message_index'] for m in messages], list(range(6)))
        self.assertEqual([[m[k] for k in ('role', 'kind', 'ts_ms', 'text')] for m in messages],
                         [list(row) for row in cached])
        self.assertEqual([m['raw_ref']['message_id'] for m in messages],
                         ['a1', 'a2', 'u1', 'call', 'result', 'u2'])
        self.assertEqual(messages[2]['text'], self.requirement)
        self.assertEqual(messages[3]['raw_ref'], {'line_no': 3, 'message_id': 'call', 'block_index': 0})
        self.assertEqual(snapshot['audit']['first_user_prompt'], self.requirement)
        self.assertEqual(snapshot['audit']['last_user_prompt'], 'Correction: preserve the original format')
        self.assertEqual(snapshot['audit']['tools_used']['write'], 1)
        self.assertEqual(snapshot['audit']['errors']['count'], 1)
        self.assertEqual([e['message_index'] for e in snapshot['audit']['evidence'] if e['type'] == 'user_prompt'], [2, 5])
        serialized = json.dumps(snapshot)
        for secret in ('PRIVATE_THOUGHT', 'PRIVATE_REDACTED', 'PRIVATE_REMINDER',
                       'PRIVATE_SYSTEM', 'SENSITIVE_ARGUMENT'):
            self.assertNotIn(secret, serialized)
        self.assertIn('[REDACTED]', serialized)
        self.assertEqual(snapshot['provenance']['status'], 'captured')
        self.assertFalse(snapshot['provenance']['truncated'])
        self.assertEqual(before, self.fingerprints())

    def test_byte_parser_is_the_same_public_projection(self):
        self.assertEqual(parse_mcode_session_file(self.path),
                         parse_mcode_session_bytes(self.path.read_bytes(), self.manifest.read_bytes(), self.path))

    def test_message_change_requires_refresh_and_changes_revision(self):
        old = self.snapshot()['provenance']['content_revision']
        self.rows[4]['message']['content'][0]['text'] = 'Updated correction'
        self.write()
        with self.assertRaisesRegex(ValueError, 'source_changed_since_index'):
            self.snapshot()
        self.indexer.scan_sessions(build_audits=False)
        self.assertNotEqual(old, self.snapshot()['provenance']['content_revision'])

    def test_manifest_change_alone_requires_refresh_and_changes_revision(self):
        old = self.snapshot()['provenance']['content_revision']
        self.header['parentSessionId'] = 'new-parent'
        self.manifest.write_text(json.dumps(self.header))
        with self.assertRaisesRegex(ValueError, 'source_changed_since_index'):
            self.snapshot()
        self.indexer.scan_sessions(build_audits=False)
        self.assertNotEqual(old, self.snapshot()['provenance']['content_revision'])

    def test_identity_change_cannot_reuse_old_session(self):
        self.header['sessionId'] = 'm2'
        self.manifest.write_text(json.dumps(self.header))
        with self.assertRaisesRegex(ValueError, 'source_changed_since_index'):
            self.snapshot()
        self.indexer.scan_sessions(build_audits=False)
        with self.assertRaisesRegex(ValueError, 'selection_session_unavailable'):
            self.snapshot()

    def test_both_file_read_budgets_fail_closed(self):
        for budget in ('MAX_MESSAGES_BYTES', 'MAX_MANIFEST_BYTES'):
            with self.subTest(budget=budget), patch('history_core.mcode_review.' + budget, 10):
                with self.assertRaisesRegex(ValueError, 'handoff_source_limit_exceeded'):
                    self.snapshot()

    def test_changes_during_capture_fail_closed(self):
        original = parse_mcode_session_bytes
        def change_manifest(content, manifest_content, path):
            parsed = original(content, manifest_content, path)
            self.manifest.write_text(self.manifest.read_text() + ' ')
            return parsed
        with patch('history_core.mcode_review.parse_mcode_session_bytes', side_effect=change_manifest):
            with self.assertRaisesRegex(ValueError, 'source_changed_during_read'):
                self.snapshot()

    def test_same_content_replacement_during_capture_fails_closed(self):
        original = parse_mcode_session_bytes
        def replace_recording(content, manifest_content, path):
            parsed = original(content, manifest_content, path)
            replacement = self.folder / 'replacement'
            replacement.write_bytes(content)
            replacement.replace(self.path)
            return parsed
        with patch('history_core.mcode_review.parse_mcode_session_bytes', side_effect=replace_recording):
            with self.assertRaisesRegex(ValueError, 'source_changed_during_read'):
                self.snapshot()

    def test_manifest_symlink_rejected(self):
        outside = self.root / 'outside.json'
        self.manifest.rename(outside)
        self.manifest.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'source_symlink_not_allowed'):
            self.snapshot()

    def test_source_directory_symlink_rejected(self):
        outside = self.root / 'outside'
        self.folder.rename(outside)
        self.folder.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'source_symlink_not_allowed'):
            self.snapshot()

    def test_non_regular_manifest_rejected_without_waiting(self):
        self.manifest.unlink()
        os.mkfifo(self.manifest)
        with self.assertRaisesRegex(ValueError, 'source_regular_file_required'):
            self.snapshot()

    def test_cached_path_outside_selected_root_rejected(self):
        self.indexer.conn.execute('UPDATE sessions SET file_path=? WHERE id=?',
                                  (str(self.root / 'outside/messages.jsonl'), 'm1'))
        with self.assertRaisesRegex(ValueError, 'cached_source_path_outside_selection'):
            self.snapshot()

    def test_cached_body_or_locator_corruption_rejected(self):
        for field, value in (('text', 'INJECTED'), ('activity_meta_json', '{}')):
            with self.subTest(field=field):
                self.indexer.conn.execute('SAVEPOINT test_cache')
                try:
                    self.indexer.conn.execute('UPDATE messages SET ' + field + '=? WHERE session_id=?', (value, 'm1'))
                    with self.assertRaisesRegex(ValueError, 'selection_stale'):
                        self.snapshot()
                finally:
                    self.indexer.conn.execute('ROLLBACK TO test_cache')
                    self.indexer.conn.execute('RELEASE test_cache')

    def test_numeric_secret_arguments_do_not_break_parser_or_escape_masking(self):
        self.rows[2]['message']['content'][0]['arguments'] = {'password': 1234567}
        self.write()
        self.indexer.scan_sessions(build_audits=False)
        self.assertNotIn('1234567', json.dumps(self.snapshot()))

    def test_malformed_record_rejects_review_instead_of_hiding_possible_correction(self):
        with self.path.open('a') as stream:
            stream.write('{malformed\n')
        self.indexer.scan_sessions(build_audits=False)
        with self.assertRaisesRegex(ValueError, 'selection_source_content_unsupported'):
            self.snapshot()

    def test_unknown_public_block_rejects_review(self):
        self.rows.append(self.row('future', 'user', 7000, [{'type': 'future-request', 'text': 'Unparsed correction'}]))
        self.write()
        self.indexer.scan_sessions(build_audits=False)
        with self.assertRaisesRegex(ValueError, 'selection_source_content_unsupported'):
            self.snapshot()

    def test_identical_duplicate_record_does_not_invent_an_extra_requirement(self):
        self.rows.append(self.rows[0])
        self.write()
        self.indexer.scan_sessions(build_audits=False)
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot['messages']), 6)
        self.assertEqual(snapshot['provenance']['parser_warnings']['duplicate_messages'], 1)


if __name__ == '__main__':
    unittest.main()
