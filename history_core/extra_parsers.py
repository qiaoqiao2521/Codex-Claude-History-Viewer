"""Read-only Gemini CLI (legacy JSON/current JSONL) and pi session parsers.

No provider imports, filesystem discovery or transcript rewrites. Gemini's
append records are materialized with last-record-wins message updates and
inclusive $rewindTo. pi retains every unique historical entry in file order;
parent IDs remain visible, so branches are not silently presented as one path.

Audit integration: iter_gemini_records(raw) / iter_pi_records(raw) yield
{message: native_message, raw_ref: {line_no|json_pointer, record_id, parent_id},
 entry_type: ...}. Gemini emits only the effective current recording; pi emits
all unique persisted message/summary entries, not replayed ancestor paths.
parse_extra_session_bytes(raw, source, path) shares the exact same materializer.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import Path

MAX_SEARCH_CHARS = 2_000_000


def _ts(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return int(value) if value > 10_000_000_000 else int(value * 1000)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1000)
        except (ValueError, OverflowError):
            return None
    return None


def _number(value):
    return max(0, int(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 0


def _text(value):
    """Only textual content; never expose embedded image/audio data or signatures."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(filter(None, (_text(part) for part in value)))
    if isinstance(value, dict):
        text = value.get('text')
        if isinstance(text, str):
            return text
    return ''


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def _exit_codes(value):
    """Only explicit native exit fields; text or generic HTTP codes are not proof."""
    codes = []
    if isinstance(value, dict):
        for key in ('exitCode', 'exit_code'):
            if type(value.get(key)) is int:
                codes.append(value[key])
        for key in ('response', 'functionResponse', 'result', 'metadata'):
            codes.extend(_exit_codes(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            codes.extend(_exit_codes(item))
    return list(dict.fromkeys(codes))


def _line_records(raw):
    valid, malformed = [], []
    for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if isinstance(record, dict):
                valid.append((record, {'line_no': number}))
        except ValueError:
            malformed.append(number)
    return valid, malformed


def _gemini_records(raw):
    try:
        whole = json.loads(raw)
    except (ValueError, UnicodeError):
        whole = None
    if isinstance(whole, dict) and isinstance(whole.get('messages'), list):
        records = [(whole, {'json_pointer': ''})]
        malformed = []
    else:
        records, malformed = _line_records(raw)
    metadata, messages = {}, {}
    def put(message, ref):
        if not isinstance(message, dict) or not isinstance(message.get('id'), str):
            return
        messages[message['id']] = {'message': message, 'raw_ref': dict(ref, record_id=message['id']), 'entry_type': 'message'}
    for record, ref in records:
        if isinstance(record.get('$rewindTo'), str):
            ids = list(messages)
            start = ids.index(record['$rewindTo']) if record['$rewindTo'] in messages else 0
            for mid in ids[start:]:
                del messages[mid]
        elif isinstance(record.get('id'), str):
            put(record, ref)
        elif isinstance(record.get('$set'), dict):
            updates = record['$set']
            if isinstance(updates.get('messages'), list):
                messages.clear()
                for number, message in enumerate(updates['messages']):
                    put(message, dict(ref, json_pointer='/$set/messages/%d' % number))
            metadata.update({key: value for key, value in updates.items() if key != 'messages'})
        elif isinstance(record.get('sessionId'), str) and isinstance(record.get('projectHash'), str):
            metadata.update({key: value for key, value in record.items() if key != 'messages'})
            for number, message in enumerate(record.get('messages') or []):
                put(message, dict(ref, json_pointer='/messages/%d' % number))
    if not metadata.get('sessionId') or not metadata.get('projectHash'):
        raise ValueError('invalid_gemini_session_file')
    return metadata, list(messages.values()), malformed


def iter_gemini_records(raw):
    """Yield effective native messages; refs identify the last updating record."""
    yield from _gemini_records(raw)[1]


def _pi_records(raw):
    rows, malformed = _line_records(raw)
    header = next((record for record, _ in rows if record.get('type') == 'session'), None)
    if not header or not isinstance(header.get('id'), str):
        raise ValueError('invalid_pi_session_file')
    version = header.get('version', 1)
    if type(version) is not int or version not in (1, 2, 3):
        raise ValueError('unsupported_pi_session_version')
    entries = {}
    for record, ref in rows:
        kind = record.get('type')
        if kind == 'session':
            continue
        if kind == 'session_info' and isinstance(record.get('name'), str):
            header = dict(header, name=record['name'])
        eid = record.get('id')
        identity = eid if isinstance(eid, str) else ('line', ref['line_no'])
        # v1 has no IDs; v2/v3 updates of the same entry do not multiply usage.
        native = record.get('message') if kind == 'message' else None
        if kind in ('branch_summary', 'compaction'):
            native = {'role': 'system', 'content': record.get('summary', ''), 'timestamp': record.get('timestamp')}
        elif kind == 'custom_message':
            native = {'role': 'custom', 'content': record.get('content', ''), 'timestamp': record.get('timestamp')}
        entries[identity] = {'message': native, 'raw_ref': dict(ref, record_id=eid, parent_id=record.get('parentId')),
                             'entry_type': kind, 'entry_timestamp': record.get('timestamp')}
    return header, [entry for entry in entries.values() if isinstance(entry['message'], dict)], malformed


def iter_pi_records(raw):
    """Yield each persisted tree node once, including clearly labelled summaries."""
    yield from _pi_records(raw)[1]


def _usage(source, message):
    usage = message.get('tokens' if source == 'gemini' else 'usage')
    if not isinstance(usage, dict):
        return None
    incoming, outgoing = _number(usage.get('input')), _number(usage.get('output'))
    cached = _number(usage.get('cached')) if source == 'gemini' else _number(usage.get('cacheRead')) + _number(usage.get('cacheWrite'))
    reasoning = _number(usage.get('thoughts')) if source == 'gemini' else 0
    total_key = 'total' if source == 'gemini' else 'totalTokens'
    # Gemini cached tokens are already inside promptTokenCount, unlike pi's
    # separate input/cache fields. Prefer the provider's explicit total always.
    total = _number(usage[total_key]) if total_key in usage else incoming + outgoing + reasoning + (0 if source == 'gemini' else cached)
    return {'input': incoming, 'output': outgoing, 'cached': cached, 'reasoning': reasoning, 'total': total}


def parse_extra_session_bytes(raw, source, path='<memory>'):
    if source == 'gemini':
        metadata, records, malformed = _gemini_records(raw)
        sid = metadata['sessionId']
        start, end = _ts(metadata.get('startTime')), _ts(metadata.get('lastUpdated'))
        cwd = metadata.get('cwd')
        directories = metadata.get('directories')
        if not cwd and isinstance(directories, list) and len(directories) == 1:
            cwd = directories[0]
        title = metadata.get('summary')
    elif source == 'pi':
        metadata, records, malformed = _pi_records(raw)
        sid = metadata['id']
        start, end = _ts(metadata.get('timestamp')), None
        cwd, title = metadata.get('cwd'), metadata.get('name')
    else:
        raise ValueError('unsupported_extra_source')
    cwd = cwd if isinstance(cwd, str) and Path(cwd).is_absolute() else None
    title = title.strip()[:80] if isinstance(title, str) and title.strip() else None
    messages, search, search_len, count, total = [], [], 0, 0, None
    def add(ts, role, kind, text, ref, **extra):
        nonlocal search_len
        if not isinstance(text, str) or not text.strip():
            return
        display = text.strip()
        if source == 'pi' and ref.get('record_id'):
            display = '[pi entry %s; parent %s]\n%s' % (ref['record_id'], ref.get('parent_id') or 'root', display)
        messages.append(dict(ts_ms=ts or 0, role=role, kind=kind, text=display, raw_ref=dict(ref), **extra))
        if search_len < MAX_SEARCH_CHARS:
            part = display[:MAX_SEARCH_CHARS-search_len]
            search.append(part); search_len += len(part)
    for entry in records:
        message, ref = entry['message'], entry['raw_ref']
        ts = _ts(message.get('timestamp')) or _ts(entry.get('entry_timestamp')) or start or 0
        if ts:
            start = min(start, ts) if start else ts
            end = max(end, ts) if end else ts
        role = message.get('type') if source == 'gemini' else message.get('role')
        role = 'assistant' if role == 'gemini' else role
        summary = entry['entry_type'] in ('compaction', 'branch_summary')
        if role in ('user', 'assistant') and not summary:
            count += 1
        content = _text(message.get('content'))
        if role == 'user' and not title and content.strip():
            title = content.strip().splitlines()[0][:80]
        if role == 'assistant':
            used = _usage(source, message)
            if used is not None:
                total = total or {key: 0 for key in used}
                for key, value in used.items():
                    total[key] += value
        if summary:
            add(ts, 'system', 'context', '[%s summary; historical context]\n%s' % (entry['entry_type'], content), ref)
            continue
        if role == 'bashExecution':
            command = str(message.get('command') or '')
            add(ts, 'tool', 'tool_use', 'Tool use: bash\nInput:\n' + command, ref, tool_name='bash', tool_args={'command': command})
            output = str(message.get('output') or '')
            status = 'cancelled' if message.get('cancelled') else 'error' if message.get('exitCode') not in (None, 0) else 'completed' if message.get('exitCode') == 0 else 'unknown'
            add(ts, 'tool', 'tool_result', 'Tool result: bash\nStatus: %s\n%s' % (status, output), ref,
                tool_name='bash', tool_result_text=output, tool_result_status=status,
                tool_result_error=(status in ('error', 'cancelled')) if status != 'unknown' else None,
                tool_result_exit_codes=[message['exitCode']] if type(message.get('exitCode')) is int else [])
            continue
        if role == 'toolResult':
            name = str(message.get('toolName') or 'tool')
            status = 'error' if message.get('isError') is True else 'completed' if message.get('isError') is False else 'unknown'
            add(ts, 'tool', 'tool_result', 'Tool result: %s\nStatus: %s\n%s' % (name, status, content), ref,
                tool_name=name, tool_call_id=message.get('toolCallId'), tool_result_text=content,
                tool_result_status=status, tool_result_error=message.get('isError'),
                tool_result_exit_codes=_exit_codes(message.get('details')))
            continue
        if content:
            add(ts, role if role in ('user','assistant','system') else 'other', 'message' if role in ('user','assistant') else 'context', content, ref)
        thoughts = message.get('thoughts') if source == 'gemini' else message.get('content')
        if isinstance(thoughts, list):
            for thought in thoughts:
                if not isinstance(thought, dict):
                    continue
                if source == 'gemini':
                    text = str(thought.get('subject') or '') + '\n' + str(thought.get('description') or '')
                else:
                    if thought.get('type') != 'thinking':
                        continue
                    text = str(thought.get('thinking') or '')
                add(ts, 'assistant', 'reasoning_summary', text, ref)
        calls = message.get('toolCalls') if source == 'gemini' else [part for part in message.get('content', []) if isinstance(part, dict) and part.get('type') == 'toolCall'] if isinstance(message.get('content'), list) else []
        seen_calls = set()
        for call in calls if isinstance(calls, list) else []:
            if not isinstance(call, dict):
                continue
            cid = call.get('id')
            if cid and cid in seen_calls:
                continue
            if cid: seen_calls.add(cid)
            name = str(call.get('name') or 'tool')
            args = call.get('args') if source == 'gemini' else call.get('arguments')
            add(ts, 'tool', 'tool_use', 'Tool use: %s\nInput:\n%s' % (name, _json(args)), ref, tool_name=name, tool_args=args, tool_call_id=cid)
            if source == 'gemini' and ('result' in call or call.get('status') in ('error','cancelled','success')):
                result = call.get('result')
                output = _text(result) or (_json(result) if result is not None else '')
                status = str(call.get('status') or 'unknown')
                add(ts, 'tool', 'tool_result', 'Tool result: %s\nStatus: %s\n%s' % (name,status,output), ref,
                    tool_name=name, tool_call_id=cid, tool_result_text=output, tool_result_status=status,
                    tool_result_error=True if status in ('error','cancelled') else False if status in ('success','completed') else None,
                    tool_result_exit_codes=_exit_codes(result))
        if isinstance(message.get('errorMessage'), str):
            add(ts, 'assistant', 'message', '[error]\n' + message['errorMessage'], ref)
    if malformed:
        add(end or start, 'other', 'context', '[%s recording: skipped %d malformed JSONL rows]' % (source, len(malformed)), {'line_no': malformed[0]})
    inherited_usage = source == 'pi' and bool(metadata.get('parentSession'))
    return {'id':sid, 'file_path':str(path), 'start_ts_ms':int(start or end or 0), 'end_ts_ms':int(end or start or 0),
            'cwd':cwd, 'title':title or ('Session ' + sid[:8]), 'message_count':count, 'messages':messages,
            'search_blob':'\n'.join(search), 'usage':None if inherited_usage else total,
            'usage_status':'unknown_inherited_session' if inherited_usage else 'reported' if total is not None else 'unknown',
            'parent_session':metadata.get('parentSession') if source=='pi' else None,
            'branch_policy':'effective_recording' if source=='gemini' else 'all_unique_persisted_entries',
            'malformed_line_count':len(malformed)}


def parse_gemini_session_file(path):
    try:
        return parse_extra_session_bytes(Path(path).read_bytes(), 'gemini', path)
    except FileNotFoundError:
        return None


def parse_pi_session_file(path):
    try:
        return parse_extra_session_bytes(Path(path).read_bytes(), 'pi', path)
    except FileNotFoundError:
        return None
