"""MiniMax Code v2 public transcript parser. Only two fixed sibling files read."""
import json
import re
from pathlib import Path

from .evidence import redact_text

_REMINDER = re.compile(r'<system-reminder\b[^>]*>.*?(?:</system-reminder>|\Z)', re.S | re.I)


def parse_mcode_session_file(path):
    path = Path(path)
    manifest = path.parent / 'manifest.json'
    if path.name != 'messages.jsonl' or path.is_symlink() or manifest.is_symlink():
        raise ValueError('invalid_mcode_storage')
    # Do not resolve any paths advertised by the manifest or transcript.
    header = json.loads(manifest.read_text(encoding='utf-8'))
    sid = header.get('sessionId')
    if header.get('schemaVersion') != 2 and header.get('schemaVersion') != 1:
        raise ValueError('unsupported_mcode_manifest_version')
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError('mcode_manifest_identity_required')
    messages, seen = [], {}
    warnings = dict(malformed_lines=0, duplicate_messages=0, unknown_blocks=0, missing_timestamps=0)
    title = None
    with path.open(encoding='utf-8') as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get('message'), dict):
                    raise ValueError()
            except ValueError:
                warnings['malformed_lines'] += 1
                continue
            mid = row.get('message_id')
            if not isinstance(mid, str) or not mid:
                warnings['malformed_lines'] += 1
                continue
            if mid in seen:
                if seen[mid] != row:
                    raise ValueError('conflicting_mcode_message_identity')
                warnings['duplicate_messages'] += 1
                continue
            seen[mid] = row
            msg = row['message']; role = msg.get('role')
            ts = msg.get('timestamp')
            ts = int(ts) if type(ts) in (int, float) and ts > 0 else None
            if ts is None:
                warnings['missing_timestamps'] += 1
            ref = dict(line_no=line_no, message_id=mid)
            turn = row.get('turn_id')
            content = msg.get('content', [])
            if not isinstance(content, list):
                warnings['unknown_blocks'] += 1
                continue
            if role not in ('user', 'assistant', 'toolResult'):
                # System/configuration messages are not public retrospective evidence.
                continue
            for block_index, block in enumerate(content):
                if not isinstance(block, dict):
                    warnings['unknown_blocks'] += 1
                    continue
                kind = block.get('type')
                call = msg.get('toolCallId')
                out_role, out_kind = ('tool', 'tool_result') if role == 'toolResult' else (role, 'message')
                if kind == 'text':
                    text = block.get('text')
                    text = _REMINDER.sub('', text).strip() if isinstance(text, str) else ''
                elif kind == 'toolCall' and role == 'assistant':
                    out_role, out_kind = 'tool', 'tool_use'
                    call = block.get('id')
                    text = 'Tool call: %s\n%s' % (block.get('name', ''), json.dumps(block.get('arguments', {}), ensure_ascii=False))
                elif kind in ('thinking', 'redactedThinking'):
                    continue
                else:
                    warnings['unknown_blocks'] += 1
                    continue
                if not text:
                    continue
                text = redact_text(text)
                messages.append(dict(ts_ms=ts, role=out_role, kind=out_kind, text=text,
                    raw_ref=dict(ref, block_index=block_index), turn_id=turn, tool_call_id=call, tool_result_error=msg.get('isError') if role == 'toolResult' else None))
                if title is None and out_role == 'user':
                    title = text.splitlines()[0][:80]
    times = [m['ts_ms'] for m in messages if m['ts_ms'] is not None]
    return dict(id=sid, file_path=str(path), start_ts_ms=min(times, default=0), end_ts_ms=max(times, default=0),
                cwd=None, title=title or 'MiniMax Code session', message_count=len(messages), messages=messages,
                search_blob='\n'.join(m['text'] for m in messages)[:2_000_000],
                activity_metadata=dict(warnings=warnings, parent_session_id=header.get('parentSessionId'),
                                       identity_origin='manifest.sessionId', project_status='not_recorded'))
