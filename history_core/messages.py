"""Bounded public message reads from the selected derived index."""
import json

from .evidence import _redact, redact_indexed_window
from .providers import uses_message_index
from .reuse import query_budget
from .sources import _indexed_public_message_sql

BODY_PAGE_CHARS = 2000
METADATA_CHARS = 8192
CALL_ID_CHARS = 128


def _object(raw):
    try:
        value = json.loads(raw or '{}')
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _display_metadata(raw):
    call_id = _object(raw).get('tool_call_id')
    call_id = _redact(call_id) if isinstance(call_id, str) and call_id else None
    return json.dumps({'tool_call_id': call_id[:CALL_ID_CHARS] if call_id else None,
                       'call_id_truncated': bool(call_id and len(call_id) > CALL_ID_CHARS)})


def read_message(indexer, session_id, message_index, text_offset=0):
    if not uses_message_index(indexer):
        raise ValueError('message_evidence_source_unsupported')
    if not isinstance(session_id, str) or not session_id:
        raise ValueError('session_id_required')
    if type(message_index) is not int or message_index < 0:
        raise ValueError('invalid_message_index')
    if type(text_offset) is not int or text_offset < 0:
        raise ValueError('invalid_text_offset')
    with query_budget(indexer) as conn:
        if conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone() is None:
            raise ValueError('session_not_found')
        # SQLite LENGTH/SUBSTR stop at NUL; Python counts indexed characters.
        # Full selected-message matching also prevents window-boundary leaks.
        conn.create_function('hv_message_chars', 1, lambda text: len(text or ''), deterministic=True)
        conn.create_function('hv_message_window', 3, redact_indexed_window, deterministic=True)
        conn.create_function('hv_message_metadata', 1, _display_metadata, deterministic=True)
        row = conn.execute(f'''
            WITH ordered AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY ts_ms,id)-1 AS message_index
                FROM messages WHERE session_id=?
            )
            SELECT m.role,m.kind,m.ts_ms,hv_message_chars(m.text) AS char_count,
                   hv_message_window(m.text,?,?) AS text,
                   SUBSTR(m.tool_summary_json,1,?) AS tool_summary_json,
                   hv_message_chars(m.tool_summary_json)>? AS tool_summary_truncated,
                   hv_message_metadata(m.activity_meta_json) AS activity_meta_json,
                   ({_indexed_public_message_sql('m')}) AS public_evidence
            FROM ordered o JOIN messages m ON m.id=o.id
            WHERE o.message_index=?
        ''', (session_id, text_offset, BODY_PAGE_CHARS, METADATA_CHARS,
              METADATA_CHARS, message_index)).fetchone()
    if row is None:
        raise ValueError('message_not_found')
    if not row['public_evidence']:
        raise ValueError('message_not_public')
    if text_offset > row['char_count']:
        raise ValueError('text_offset_out_of_range')
    end = text_offset + len(row['text'])
    meta = _object(row['activity_meta_json'])
    result = {'schema_version': 'history.message.v1', 'session_id': session_id,
              'message_index': message_index, 'role': row['role'], 'kind': row['kind'],
              'ts_ms': row['ts_ms'], 'text': row['text'],
              'char_count': row['char_count'], 'text_offset': text_offset,
              'text_offset_basis': 'indexed_text', 'body_page_chars': BODY_PAGE_CHARS,
              'next_text_offset': end if end < row['char_count'] else None,
              'has_more_before': text_offset > 0, 'has_more_after': end < row['char_count'],
              'truncated': text_offset > 0 or end < row['char_count'],
              'call_id': meta.get('tool_call_id'), 'call_id_truncated': meta.get('call_id_truncated', False),
              'tool_summary_truncated': bool(row['tool_summary_truncated']), 'redacted': True,
              'redaction_notice': 'Common secret spans use equal-length masking; this is not complete anonymisation.'}
    summary = _object(row['tool_summary_json'])
    if summary:
        result['tool_summary'] = _redact(summary)
    coverage = getattr(indexer, '_coverage', {}).get(session_id, {})
    result['partial'] = bool(coverage and coverage.get('content_status') != 'decoded_text')
    if coverage:
        result.update(content_status=coverage.get('content_status'),
                      unsupported_steps_count=len(coverage.get('unsupported_steps') or []))
    return result
