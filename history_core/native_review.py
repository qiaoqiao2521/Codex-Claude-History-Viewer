"""Bounded, revision-bound public-message snapshots for native review exports.

Native SQLite sources are never opened for writing. A private DB/WAL copy is
used where SQLite would otherwise update the source WAL's shared-memory marks.
The resulting revision covers the selected session and the observed store
revision; it is not a promise that history proves current project correctness.
"""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from audit.extractor import _claude_events, build_audit_from_events
from .agy import _ReadBudget, _database_paths, _read_only, _signature, read_agy_session
from .zcode import ZCodeIndexer


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_ROWS = 10000
# SQLite pages contain unrelated rows too; physical copying has a separate,
# explicit ceiling and the copy is removed at the end of this call.
MAX_DATABASE_BYTES = 64 * 1024 * 1024
_PUBLIC_KINDS = frozenset(('message', 'tool_use', 'tool_result'))
_PUBLIC_ROLES = frozenset(('user', 'assistant', 'tool'))


def _public_messages(messages):
    result = []
    for index, message in enumerate(messages):
        if message.get('role') not in _PUBLIC_ROLES or message.get('kind') not in _PUBLIC_KINDS:
            continue
        item = {key: message.get(key) for key in ('role', 'kind', 'text', 'ts_ms')}
        item['message_index'] = index
        if 'step_index' in message:
            item['native_ref'] = {'table': 'steps', 'step_index': message['step_index']}
        result.append(item)
    return result


def _agy_snapshot(indexer, session_id):
    before = indexer.source_revision()
    if before != indexer._revision:
        raise ValueError('source_changed_since_index: refresh required')
    with indexer.lock:
        row = indexer.conn.execute('SELECT file_path FROM sessions WHERE id=?', (session_id,)).fetchone()
    if row is None:
        raise ValueError('selection_session_unavailable')
    path = Path(row['file_path'])
    expected = indexer.root / 'conversations' / (session_id + '.db')
    if path != expected:
        # Legacy protobuf is metadata-only, never an original user requirement.
        raise ValueError('selection_native_content_unsupported')
    data = read_agy_session(path, max_bytes=MAX_SOURCE_BYTES)
    if data['content_status'] != 'decoded_text':
        raise ValueError('selection_native_content_unsupported')
    if len(data['messages']) > MAX_SOURCE_ROWS:
        raise ValueError('native_review_source_limit_exceeded')
    events = []
    for record in data['records']:
        events.extend(_claude_events(record, record['step_index'] + 1))
    audit = build_audit_from_events(events, session_id=session_id, source=indexer.source,
                                   started_at=data['start_ts_ms'], ended_at=data['end_ts_ms']).to_dict()
    for evidence in audit.get('evidence', []):
        ref = evidence.get('raw_ref') or {}
        if 'line_no' in ref:
            evidence['raw_ref'] = {'table': 'steps', 'step_index': ref['line_no'] - 1}
    # The derived Indexer orders by timestamp then insertion ID, not step ID.
    ordered = [message for _, message in sorted(enumerate(data['messages']),
               key=lambda pair: (pair[1]['ts_ms'], pair[0]))]
    messages = _public_messages(ordered)
    if indexer.source_revision() != before or indexer._revision != before:
        raise ValueError('source_changed_during_read')
    return messages, audit, before, {'path': str(path), 'format': 'sqlite',
                                    'table': 'steps', 'addressing': 'display_message_index'}


def _zcode_snapshot(indexer, session_id):
    before = _signature(_database_paths(indexer.db_path))
    with closing(_read_only(indexer.db_path, budget=_ReadBudget(MAX_DATABASE_BYTES))) as snapshot:
        private = ZCodeIndexer(Path(snapshot._snapshot.name) / 'snapshot.db')
        try:
            if private.conn.execute('SELECT 1 FROM main.session WHERE id=?', (session_id,)).fetchone() is None:
                raise ValueError('selection_session_unavailable')
            # Preflight the selected joined payload before materializing any
            # messages. Even this query uses the private copy, not source shm.
            size, rows = private.conn.execute(
                'SELECT COALESCE(SUM(length(CAST(p.data AS BLOB)) + length(CAST(m.data AS BLOB))),0), COUNT(*) '
                'FROM main.part p JOIN main.message m ON m.id=p.message_id WHERE p.session_id=?',
                (session_id,)).fetchone()
            if size > MAX_SOURCE_BYTES or rows > MAX_SOURCE_ROWS:
                raise ValueError('native_review_source_limit_exceeded')
            messages = _public_messages(private._load_flat_messages(session_id))
            # This new indexer has no cached historical audit to reuse.
            audit = private.build_session_audit(session_id)
            if audit is None:
                raise ValueError('selection_session_unavailable')
        finally:
            private.conn.close()
    if _signature(_database_paths(indexer.db_path)) != before:
        raise ValueError('source_changed_during_read')
    return messages, audit, before, {'path': str(indexer.db_path), 'format': 'sqlite',
                                    'tables': ['session', 'message', 'part'],
                                    'addressing': 'display_message_index'}


def native_review_snapshot(indexer, session_id):
    """Return one complete bounded native session, retaining visible indices."""
    if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
        raise ValueError('selection_session_invalid')
    source = getattr(indexer, 'source', '')
    if source in ('agy', 'antigravity'):
        messages, audit, revision, locator = _agy_snapshot(indexer, session_id)
    elif source == 'zcode':
        messages, audit, revision, locator = _zcode_snapshot(indexer, session_id)
    else:
        raise ValueError('selection_revision_unsupported')
    canonical = json.dumps({'schema': 'history.native-review.v1', 'source': source,
                            'session_id': session_id, 'store_revision': revision,
                            'messages': messages, 'audit': audit},
                           ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    digest = 'sha256:' + hashlib.sha256(canonical.encode()).hexdigest()
    return {'messages': messages, 'audit': audit, 'provenance': {
        'status': 'captured', 'reason': None, 'source': source,
        'session_id': session_id, 'locator': {**locator, 'session_id': session_id},
        'content_revision': digest, 'context_revision': digest,
        'revision_scope': 'native_store_and_selected_public_messages_and_audit',
        'source_revision': revision, 'truncated': False,
        'byte_limit': MAX_SOURCE_BYTES, 'row_limit': MAX_SOURCE_ROWS,
        'physical_byte_limit': MAX_DATABASE_BYTES if source == 'zcode' else MAX_SOURCE_BYTES,
        'observed_at': datetime.now(timezone.utc).isoformat(),
    }}
