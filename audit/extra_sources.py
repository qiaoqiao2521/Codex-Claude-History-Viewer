"""Audit the same materialized Gemini/pi records used by the history index."""
from pathlib import Path

from .schema import AuditEvent


def extract_extra_audit(path, source, *, session_id_hint=None, content=None):
    from history_core.extra_parsers import parse_extra_session_bytes
    from .extractor import build_audit_from_events
    if content is None:
        try:
            content = Path(path).read_bytes()
        except FileNotFoundError:
            return None
    if source == 'copilot':
        from history_core.copilot import parse_copilot_session_bytes
        parsed = parse_copilot_session_bytes(content, path)
    else:
        parsed = parse_extra_session_bytes(content, 'pi' if source == 'prime' else source, path)
    events = []
    tool_names = {'run_shell_command': 'shell_command', 'write_file': 'write', 'replace': 'edit'}
    for message in parsed['messages']:
        kind = message['kind']
        kind = 'reasoning' if kind == 'reasoning_summary' else kind
        ref = message.get('raw_ref') or {}
        name = message.get('tool_name')
        events.append(AuditEvent(
            ts_ms=message.get('ts_ms') or 0, role=message['role'], kind=kind,
            text=message['text'] if kind in ('message', 'reasoning') else '',
            tool_name=tool_names.get(name, name), tool_args=message.get('tool_args'),
            tool_result_text=message.get('tool_result_text', message['text'] if kind == 'tool_result' else ''),
            tool_result_error=message.get('tool_result_error'),
            tool_result_exit_codes=message.get('tool_result_exit_codes') or [],
            line_no=ref.get('line_no'), raw_ref=dict(ref),
        ))
    payload = build_audit_from_events(events, session_id=session_id_hint or parsed['id'], source=source,
                                      started_at=parsed['start_ts_ms'], ended_at=parsed['end_ts_ms'],
                                      parse_errors=parsed.get('malformed_line_count', 0))
    # A pi file is a tree of retained branches, not proof one active task ended.
    if source in ('pi', 'prime'):
        payload.outcome_signal = 'unknown'
        payload.has_assistant_after_last_user = False
    return payload
