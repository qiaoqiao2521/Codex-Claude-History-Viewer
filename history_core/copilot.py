"""Read-only GitHub Copilot CLI event-log parser.

The canonical input is session-state/<id>/events.jsonl, including Snap common
homes. This module does not discover roots, open Copilot databases, load auth
configuration, invoke the CLI, or rewrite recordings. Only explicit display
content and executed tool events are materialized. Assistant toolRequests are
intent metadata, not additional executed calls.

Event IDs are immutable identities: first occurrence wins, preserving its raw
line locator. Missing IDs retain each line. Generic success is an event outcome,
never an inferred process exit code. Token counters remain unknown until their
cumulative/interval/cache semantics have a verified contract.
"""
from __future__ import annotations

import json
from pathlib import Path

from .extra_parsers import MAX_SEARCH_CHARS, _exit_codes, _json, _text, _ts


DISPLAY_EVENTS = {'user.message': 'user', 'assistant.message': 'assistant', 'system.message': 'system'}


def _records(raw):
    records, seen, malformed, duplicates = [], set(), [], 0
    for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            malformed.append(number)
            continue
        if not isinstance(event, dict):
            malformed.append(number)
            continue
        eid = event.get('id')
        if isinstance(eid, str) and eid:
            if eid in seen:
                duplicates += 1
                continue
            seen.add(eid)
        ref = {'line_no': number}
        if isinstance(eid, str) and eid:
            ref['record_id'] = eid
        parent = event.get('parentId')
        if isinstance(parent, str):
            ref['parent_id'] = parent
        records.append((event, ref))
    return records, malformed, duplicates


def _result_text(result):
    """Read explicit output fields without dumping telemetry or credential maps."""
    if isinstance(result, (str, list)):
        return _text(result)
    if not isinstance(result, dict):
        return ''
    parts = []
    for key in ('content', 'detailedContent', 'text', 'output', 'stdout', 'stderr'):
        value = _text(result.get(key))
        if value and value not in parts:
            parts.append(value)
    error = result.get('error')
    if isinstance(error, str) and error not in parts:
        parts.append(error)
    elif isinstance(error, dict) and isinstance(error.get('message'), str) and error['message'] not in parts:
        parts.append(error['message'])
    return '\n'.join(parts)


def parse_copilot_session_bytes(raw: bytes, path='<memory>'):
    """Return the same session/messages shape as the other file parsers.

    Tool messages additionally carry normalized audit fields (tool_name,
    tool_args or tool_result_*), tool_call_id, and the original raw_ref.
    Neither the containing directory nor gitRoot is authority for session cwd.
    """
    records, malformed, duplicates = _records(raw)
    starts = [(event, ref) for event, ref in records
              if event.get('type') == 'session.start' and isinstance(event.get('data'), dict)]
    if not starts:
        raise ValueError('invalid_copilot_session_file: session.start required')
    header = starts[0][0]
    data = header['data']
    sid = data.get('sessionId')
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError('invalid_copilot_session_file: explicit sessionId required')
    if any(event['data'].get('sessionId') not in (None, sid) for event, _ in starts):
        raise ValueError('mixed_copilot_session_file')
    context = data.get('context') if isinstance(data.get('context'), dict) else {}
    cwd = context.get('cwd') or data.get('cwd')
    cwd = cwd if isinstance(cwd, str) and Path(cwd).is_absolute() else None
    start = _ts(data.get('startTime')) or _ts(header.get('timestamp'))
    end, title, count, search_len = start, None, 0, 0
    messages, search, calls = [], [], {}

    def add(ts, role, kind, body, ref, **extra):
        nonlocal count, title, search_len
        if not isinstance(body, str) or not body.strip():
            return
        display = body.strip()
        messages.append(dict(ts_ms=ts or 0, role=role, kind=kind, text=display, raw_ref=dict(ref), **extra))
        if role in ('user', 'assistant') and kind == 'message':
            count += 1
            if role == 'user' and not title:
                title = display.splitlines()[0][:80]
        if search_len < MAX_SEARCH_CHARS:
            fragment = display[:MAX_SEARCH_CHARS - search_len]
            search.append(fragment)
            search_len += len(fragment)

    for event, ref in records:
        kind = event.get('type')
        payload = event.get('data')
        if not isinstance(kind, str) or not isinstance(payload, dict):
            continue
        ts = _ts(event.get('timestamp')) or start or 0
        if ts:
            start = min(start, ts) if start else ts
            end = max(end, ts) if end else ts
        if kind in DISPLAY_EVENTS:
            role = DISPLAY_EVENTS[kind]
            # transformedContent, reasoningOpaque, encryptedContent, toolRequests,
            # model telemetry and attachment bytes are deliberately not fallback text.
            add(ts, role, 'message' if role != 'system' else 'context', _text(payload.get('content')), ref)
        elif kind == 'tool.execution_start':
            name = payload.get('toolName')
            name = name if isinstance(name, str) and name else 'tool'
            call_id = payload.get('toolCallId')
            call_id = call_id if isinstance(call_id, str) else None
            args = payload.get('arguments')
            if call_id:
                calls[call_id] = name
            add(ts, 'tool', 'tool_use', 'Tool use: %s\nInput:\n%s' % (name, _json(args)), ref,
                tool_name=name, tool_args=args, tool_call_id=call_id)
        elif kind == 'tool.execution_complete':
            call_id = payload.get('toolCallId')
            call_id = call_id if isinstance(call_id, str) else None
            name = payload.get('toolName') or calls.get(call_id)
            name = name if isinstance(name, str) and name else 'tool'
            result = payload.get('result')
            output = _result_text(result)
            error = payload.get('error')
            if not output and isinstance(error, (str, dict)):
                output = error if isinstance(error, str) else _text(error.get('message'))
            # Only actual native exitCode/exit_code fields count. Text saying
            # "Exit code: 0", generic code/status, and success=True do not.
            codes = list(dict.fromkeys(_exit_codes(result) + [payload[key] for key in ('exitCode', 'exit_code') if type(payload.get(key)) is int]))
            success = payload.get('success')
            result_error = isinstance(result, dict) and (result.get('isError') is True or result.get('is_error') is True or bool(result.get('error')))
            failed = success is False or result_error or bool(error) or any(code != 0 for code in codes)
            is_error = True if failed else False if success is True or codes and all(code == 0 for code in codes) else None
            status = 'error' if failed else 'completed' if is_error is False else 'unknown'
            add(ts, 'tool', 'tool_result', 'Tool result: %s\nStatus: %s\n%s' % (name, status, output), ref,
                tool_name=name, tool_call_id=call_id, tool_result_text=output,
                tool_result_status=status, tool_result_error=is_error, tool_result_exit_codes=codes)
        elif kind == 'session.error':
            error = payload.get('message')
            if not isinstance(error, str):
                error = _result_text(payload.get('error'))
            add(ts, 'other', 'context', '[Copilot session error]\n' + error if error else '', ref)
        # Lifecycle, auth, hook and trace events are not transcript messages.
    if malformed:
        add(end or start, 'other', 'context', '[copilot recording: skipped %d malformed JSONL rows]' % len(malformed), {'line_no': malformed[0]})
    return {'id': sid, 'file_path': str(path), 'start_ts_ms': int(start or end or 0),
            'end_ts_ms': int(end or start or 0), 'cwd': cwd, 'title': title or 'Session ' + sid[:8],
            'message_count': count, 'messages': messages, 'search_blob': '\n'.join(search),
            'usage': None, 'usage_status': 'unknown_counter_semantics',
            'malformed_line_count': len(malformed), 'duplicate_event_count': duplicates}


def parse_copilot_session_file(path):
    """Parse only the selected event log. Missing sources retain normal semantics."""
    try:
        return parse_copilot_session_bytes(Path(path).read_bytes(), path=path)
    except FileNotFoundError:
        return None
