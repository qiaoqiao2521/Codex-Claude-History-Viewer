"""Bounded queries of recorded trace markers, never message bodies or effects."""
import json

from .evidence import redact_text
from .reuse import query_budget

MAX_LIMIT = 100
MAX_OFFSET = 100000
MAX_METADATA_CHARS = 65536
FIELD_CHARS = 128
PATH_CHARS = 512
CWD_CHARS = 2048
_MARKER_FIELDS = ('kind', 'event', 'name', 'path', 'version', 'content_hash',
                  'evidence_origin', 'hook_event')
_RAW_REF_FIELDS = ('line_no', 'record_id', 'parent_message_id', 'json_pointer')


def _bounded_text(value, limit, field, truncated):
    if not isinstance(value, str):
        return None
    # Mask complete selected fields before clipping across secret boundaries.
    safe = redact_text(value)
    if len(safe) > limit:
        truncated.append(field)
    return safe[:limit]


def _display_metadata(raw):
    """The SQL caller supplies only whitelisted fields, not raw metadata."""
    value = json.loads(raw)
    truncated = []
    result = {}
    for field in _MARKER_FIELDS:
        result[field] = _bounded_text(value.get(field),
            PATH_CHARS if field == 'path' else FIELD_CHARS, field, truncated)
        if value.get(field + '_truncated') in (True, 1) and field not in truncated:
            truncated.append(field)
    for field, limit in (('call_id', FIELD_CHARS), ('cwd', CWD_CHARS),
                         ('turn_id', FIELD_CHARS), ('context_basis', FIELD_CHARS)):
        result[field] = _bounded_text(value.get(field), limit, field, truncated)
    raw_ref = {}
    for field in _RAW_REF_FIELDS:
        ref = value.get('raw_ref_' + field)
        if field == 'line_no':
            if type(ref) is int and ref > 0:
                raw_ref[field] = ref
        elif isinstance(ref, str):
            raw_ref[field] = _bounded_text(ref, PATH_CHARS,
                                           'raw_ref.' + field, truncated)
    result.update(raw_ref=raw_ref, metadata_truncated=bool(truncated),
                  truncated_fields=truncated)
    return json.dumps(result, ensure_ascii=False)


def read_markers(indexer, *, name=None, kind=None, session_id=None, project=None, limit=20, offset=0):
    if getattr(indexer, 'source', None) not in ('codex', 'claude'):
        raise ValueError('markers_source_unsupported')
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError('invalid_marker_limit')
    if type(offset) is not int or not 0 <= offset <= MAX_OFFSET:
        raise ValueError('invalid_marker_offset')
    if name is not None and (not isinstance(name, str) or not name or len(name) > FIELD_CHARS):
        raise ValueError('invalid_marker_name')
    if kind is not None and kind not in ('skill', 'output_style'):
        raise ValueError('invalid_marker_kind')
    if session_id is not None and (
        not isinstance(session_id, str) or not session_id or len(session_id) > 1024
    ):
        raise ValueError('invalid_marker_session')
    if project is not None and (not isinstance(project, str) or not project or len(project) > CWD_CHARS):
        raise ValueError('invalid_marker_project')

    # Row ordinals use every indexed message before marker/name/kind filtering.
    session_filter = 'WHERE m.session_id=?' if session_id is not None else ''
    params = [MAX_METADATA_CHARS]
    if session_id is not None:
        params.append(session_id)
    filters = ["json_extract(marker,'$.kind') IN ('skill','output_style')",
               "json_type(marker,'$.event')='text'",
               "length(json_extract(marker,'$.event'))>0",
               "json_type(marker,'$.name')='text'",
               "length(json_extract(marker,'$.name'))>0"]
    for field, selected in (('name', name), ('kind', kind)):
        if selected is not None:
            filters.append("json_extract(marker,'$.%s')=?" % field)
            params.append(selected)
    if project is not None:
        filters.append("COALESCE(json_extract(meta,'$.trace_context.cwd'),session_cwd)=?")
        params.append(project)
    fields = []
    for field in _MARKER_FIELDS:
        fields.extend(("'%s'" % field, "json_extract(marker,'$.%s')" % field))
        fields.extend(("'%s_truncated'" % field,
                       "json_extract(marker,'$.%s_truncated')" % field))
    for field in _RAW_REF_FIELDS:
        fields.extend(("'raw_ref_%s'" % field,
                       "json_extract(meta,'$.raw_ref.%s')" % field))
    fields.extend(("'call_id'", "json_extract(meta,'$.tool_call_id')",
                   "'cwd'", "COALESCE(json_extract(meta,'$.trace_context.cwd'),session_cwd)",
                   "'turn_id'", "COALESCE(json_extract(meta,'$.trace_context.turn_id'),json_extract(meta,'$.turn_id'))",
                   "'context_basis'", "json_extract(meta,'$.trace_context.basis')"))
    params.extend((limit + 1, offset))
    with query_budget(indexer) as conn:
        conn.create_function('hv_marker_metadata', 1, _display_metadata, deterministic=True)
        rows = conn.execute(f'''
            WITH ordered AS (
                SELECT m.session_id,m.ts_ms,m.activity_ts_ms,
                       CASE WHEN length(m.activity_meta_json)<=? AND json_valid(m.activity_meta_json)
                            THEN m.activity_meta_json ELSE '{{}}' END AS meta,
                       ROW_NUMBER() OVER (PARTITION BY m.session_id ORDER BY m.ts_ms,m.id)-1 AS message_index
                FROM messages m {session_filter}
            ), candidates AS (
                SELECT o.*,s.cwd AS session_cwd,j.key AS marker_index,
                       CASE WHEN j.type='object' THEN j.value ELSE '{{}}' END AS marker
                FROM ordered o JOIN sessions s ON s.id=o.session_id
                JOIN json_each(CASE WHEN json_type(o.meta,'$.trace_markers')='array'
                                    THEN json_extract(o.meta,'$.trace_markers') ELSE '[]' END) j
            )
            SELECT session_id,message_index,marker_index,ts_ms,activity_ts_ms,
                   hv_marker_metadata(json_object({','.join(fields)})) AS display_json
            FROM candidates WHERE {' AND '.join(filters)}
            ORDER BY ts_ms DESC,session_id ASC,message_index DESC,marker_index ASC
            LIMIT ? OFFSET ?
        ''', params).fetchall()
    has_more = len(rows) > limit
    items = []
    for row in rows[:limit]:
        item = {'source': indexer.source, 'session_id': row['session_id'],
                'message_index': row['message_index'], 'marker_index': row['marker_index'],
                'ts_ms': row['ts_ms'], 'activity_ts_ms': row['activity_ts_ms']}
        item.update(json.loads(row['display_json']))
        items.append(item)
    return {'schema_version': 'history.markers.v1', 'items': items,
            'limit': limit, 'offset': offset, 'count': len(items),
            'count_basis': 'returned_recorded_markers', 'has_more': has_more,
            'next_offset': offset + len(items) if has_more else None,
            'coverage': 'recorded_markers_only', 'partial': True,
            'uncaptured_triggers_possible': True, 'effect_assessment': 'not_performed',
            'metadata_budget_chars': MAX_METADATA_CHARS, 'oversized_metadata_policy': 'omitted',
            'redacted': True,
            'redaction_notice': 'Common secret spans are masked; this is not complete anonymisation.'}
