"""Native review snapshots use synthetic stores and never provider execution."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from history_core.agy import AgyIndexer
from history_core.native_review import native_review_snapshot
from history_core.zcode import ZCodeIndexer
from test_agy import blob, metadata, step
from test_zcode import SCHEMA, TS


class NativeReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def agy(self, *, unsupported=False):
        root = self.root / 'agy'
        (root / 'conversations').mkdir(parents=True)
        summaries = root / 'conversation_summaries.db'
        with sqlite3.connect(summaries) as db:
            db.execute('CREATE TABLE conversation_summaries(conversation_id TEXT PRIMARY KEY,title TEXT,step_count INTEGER,'
                       'last_modified_time TEXT,workspace_uris TEXT)')
            db.execute('INSERT INTO conversation_summaries VALUES(?,?,?,?,?)',
                       ('review', 'Synthetic review', 4, '2026-09-21T12:00:00Z', '["file:///synthetic/repo"]'))
        path = root / 'conversations' / 'review.db'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE steps(idx INTEGER PRIMARY KEY,step_type INTEGER,status INTEGER,step_format INTEGER,step_payload BLOB)')
            rows = [(0, 14, 3, 0, step(14, blob(1, 'Later requirement'), meta=metadata(timestamp=1790000300))),
                    (1, 15, 3, 0, step(15, blob(3, 'PRIVATE_REASONING') + blob(1, 'Assistant claim'), meta=metadata(timestamp=1790000200))),
                    (2, 14, 3, 0, step(14, blob(1, 'Original requirement'), meta=metadata(timestamp=1790000100)))]
            if unsupported:
                rows.append((3, 999, 3, 0, step(999, blob(1, 'Unknown correction'))))
            db.executemany('INSERT INTO steps VALUES(?,?,?,?,?)', rows)
        indexer = AgyIndexer(summaries)
        self.addCleanup(indexer.conn.close)
        return indexer, path

    def zcode(self):
        path = self.root / 'zcode.db'
        with sqlite3.connect(path) as db:
            db.executescript(SCHEMA)
            db.execute('INSERT INTO session(id,directory,title,time_created,time_updated) VALUES(?,?,?,?,?)',
                       ('review', '/synthetic/repo', 'Review', TS, TS + 1000))
            for mid, seq, role, stamp in [('user', 0, 'user', TS + 900), ('assistant', 1, 'assistant', TS + 500),
                                          ('correction', 2, 'user', TS + 100)]:
                db.execute('INSERT INTO message VALUES(?,?,?,?,?,?)',
                           (mid, 'review', stamp, stamp, json.dumps({'role': role}), seq))
            parts = [('first', 'user', 0, 'text', 'Original requirement'),
                     ('reason', 'assistant', 0, 'reasoning', 'PRIVATE_REASONING'),
                     ('answer', 'assistant', 1, 'text', 'Assistant claim'),
                     ('skip', 'assistant', 2, 'timeline', 'Ignored timeline'),
                     ('last', 'correction', 0, 'text', 'Later requirement')]
            for pid, mid, seq, kind, text in parts:
                db.execute('INSERT INTO part VALUES(?,?,?,?,?,?,?)',
                           (pid, mid, 'review', TS, TS, json.dumps({'type': kind, 'text': text}), seq))
        indexer = ZCodeIndexer(path)
        self.addCleanup(indexer.conn.close)
        return indexer, path

    def fingerprints(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_agy_keeps_ui_absolute_indices_and_full_original_text(self):
        indexer, _ = self.agy()
        before = self.fingerprints()
        snapshot = native_review_snapshot(indexer, 'review')
        self.assertEqual([m['message_index'] for m in snapshot['messages']], [0, 2, 3])
        self.assertEqual([m['text'] for m in snapshot['messages']],
                         ['Original requirement', 'Assistant claim', 'Later requirement'])
        for message in snapshot['messages']:
            displayed = indexer.get_session_message('review', message['message_index'])
            self.assertEqual(displayed['text'], message['text'])
        self.assertNotIn('PRIVATE_REASONING', json.dumps(snapshot['messages']))
        self.assertEqual(snapshot['messages'][0]['native_ref'], {'table': 'steps', 'step_index': 2})
        self.assertEqual(snapshot['provenance']['status'], 'captured')
        self.assertNotIn('line_no', json.dumps(snapshot['audit']))
        self.assertEqual(before, self.fingerprints())
        again = native_review_snapshot(indexer, 'review')
        self.assertEqual(snapshot['provenance']['content_revision'], again['provenance']['content_revision'])

    def test_zcode_keeps_sequence_order_and_absolute_indices_while_excluding_thinking(self):
        indexer, _ = self.zcode()
        before = self.fingerprints()
        snapshot = native_review_snapshot(indexer, 'review')
        self.assertEqual([m['message_index'] for m in snapshot['messages']], [0, 2, 3])
        self.assertEqual([m['text'] for m in snapshot['messages']],
                         ['Original requirement', 'Assistant claim', 'Later requirement'])
        for message in snapshot['messages']:
            self.assertEqual(message['text'], indexer.get_session_message('review', message['message_index'])['text'])
        self.assertNotIn('PRIVATE_REASONING', json.dumps(snapshot['messages']))
        self.assertNotIn('Ignored timeline', json.dumps(snapshot['messages']))
        self.assertEqual(snapshot['audit']['source'], 'zcode')
        self.assertEqual(before, self.fingerprints())
        self.assertEqual(snapshot['provenance']['content_revision'],
                         native_review_snapshot(indexer, 'review')['provenance']['content_revision'])

    def test_agy_source_change_requires_refresh_and_rebind(self):
        indexer, path = self.agy()
        original = native_review_snapshot(indexer, 'review')['provenance']['content_revision']
        with sqlite3.connect(path) as db:
            db.execute('UPDATE steps SET step_payload=? WHERE idx=0',
                       (step(14, blob(1, 'Changed requirement'), meta=metadata(timestamp=1790000300)),))
        with self.assertRaisesRegex(ValueError, 'source_changed_since_index'):
            native_review_snapshot(indexer, 'review')
        indexer.scan_sessions()
        fresh = native_review_snapshot(indexer, 'review')
        self.assertNotEqual(original, fresh['provenance']['content_revision'])
        self.assertEqual(fresh['messages'][-1]['text'], 'Changed requirement')

    def test_zcode_source_change_changes_revision_without_stale_audit_cache(self):
        indexer, path = self.zcode()
        original = native_review_snapshot(indexer, 'review')
        indexer.build_session_audit('review')
        with sqlite3.connect(path) as db:
            db.execute('UPDATE part SET data=? WHERE id=?',
                       (json.dumps({'type': 'text', 'text': 'Changed requirement'}), 'last'))
        fresh = native_review_snapshot(indexer, 'review')
        self.assertNotEqual(original['provenance']['content_revision'], fresh['provenance']['content_revision'])
        self.assertEqual(fresh['messages'][-1]['text'], 'Changed requirement')
        self.assertIn('Changed requirement', json.dumps(fresh['audit']))

    def test_limits_reject_before_flattening_and_do_not_silently_clip(self):
        indexer, _ = self.zcode()
        for name, value in [('MAX_SOURCE_BYTES', 1), ('MAX_SOURCE_ROWS', 1), ('MAX_DATABASE_BYTES', 1)]:
            with self.subTest(name=name), patch('history_core.native_review.' + name, value), \
                    patch.object(ZCodeIndexer, '_load_flat_messages', side_effect=AssertionError('must not flatten')):
                with self.assertRaisesRegex(ValueError, 'limit_exceeded'):
                    native_review_snapshot(indexer, 'review')
        agy, _ = self.agy()
        with patch('history_core.native_review.MAX_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'limit_exceeded'):
                native_review_snapshot(agy, 'review')

    def test_partial_agy_source_does_not_promise_complete_requirements(self):
        indexer, _ = self.agy(unsupported=True)
        with self.assertRaisesRegex(ValueError, 'selection_native_content_unsupported'):
            native_review_snapshot(indexer, 'review')

    def test_agy_revision_change_during_read_is_rejected(self):
        indexer, _ = self.agy()
        revision = indexer.source_revision()
        with patch.object(indexer, 'source_revision', side_effect=[revision, 'changed']):
            with self.assertRaisesRegex(ValueError, 'source_changed_during_read'):
                native_review_snapshot(indexer, 'review')

    def test_zcode_revision_change_during_read_is_rejected(self):
        indexer, _ = self.zcode()
        with patch('history_core.native_review._signature', side_effect=['before', 'after']):
            with self.assertRaisesRegex(ValueError, 'source_changed_during_read'):
                native_review_snapshot(indexer, 'review')

    def test_permission_failure_is_not_silently_an_empty_requirement_list(self):
        indexer, _ = self.zcode()
        with patch('history_core.native_review._read_only', side_effect=PermissionError('unreadable')):
            with self.assertRaises(PermissionError):
                native_review_snapshot(indexer, 'review')

    def test_wal_commits_are_visible_and_source_database_wal_shm_remain_unchanged(self):
        indexer, path = self.zcode()
        writer = sqlite3.connect(path)
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE part SET data=? WHERE id=?',
                       (json.dumps({'type': 'text', 'text': 'Committed WAL requirement'}), 'last'))
        writer.commit()
        before = self.fingerprints()
        result = native_review_snapshot(indexer, 'review')
        self.assertEqual(result['messages'][-1]['text'], 'Committed WAL requirement')
        self.assertEqual(before, self.fingerprints())


if __name__ == '__main__':
    unittest.main()
