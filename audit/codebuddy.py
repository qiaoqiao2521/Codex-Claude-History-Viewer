"""CodeBuddy's native JSONL tool/message envelopes as Claude audit events.

Only the record shape is adapted. No source file, provider or tool is executed.
CodeBuddy token accounting is intentionally handled separately by its indexer.
"""
import json


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("text") if isinstance(value.get("text"), str) else ""
    if isinstance(value, list):
        return "\n".join(text for item in value if (text := _text(item)))
    return ""


def normalize_codebuddy_record(record):
    """Return one compatible envelope, keeping its original JSONL line identity.

    A completed native tool record is not automatically a successful command.
    Explicit native error flags become ``is_error``; textual exit-code parsing
    remains the responsibility of the existing audit normaliser.
    """
    if not isinstance(record, dict):
        return None
    common = {key: record[key] for key in ("timestamp", "sessionId", "cwd") if key in record}
    kind = record.get("type")
    provider = record.get("providerData")
    provider = provider if isinstance(provider, dict) else {}
    mid = provider.get("messageId") or record.get("id")
    message = {"id": mid} if isinstance(mid, str) and mid else {}
    if kind == "message":
        message.update(role=record.get("role") or "other",
                       content=[{"type": "text", "text": _text(record.get("content"))}])
    elif kind == "reasoning":
        message.update(role="assistant", content=[{"type": "thinking", "thinking":
                       _text(record.get("content")) or _text(record.get("rawContent"))}])
    elif kind == "function_call":
        arguments = record.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (TypeError, ValueError):
                pass
        message.update(role="assistant", content=[{"type": "tool_use", "id": record.get("callId"),
                       "name": record.get("name") or "tool", "input": arguments}])
    elif kind == "function_call_result":
        result = {"type": "tool_result", "tool_use_id": record.get("callId"),
                  "content": _text(record.get("output"))}
        tool_result = provider.get("toolResult")
        tool_result = tool_result if isinstance(tool_result, dict) else {}
        if record.get("status") in ("failed", "error", "cancelled") or provider.get("error") or tool_result.get("error"):
            result["is_error"] = True
        message.update(role="user", content=[result])
    elif kind in ("summary", "ai-title"):
        return dict(common, type="summary", summary=record.get("aiTitle") if kind == "ai-title" else record.get("summary"))
    else:
        # Known telemetry/session metadata carries identity/timing but no user
        # message; ignore it rather than flooding the transcript with raw JSON.
        return dict(common, type="file-history-snapshot")
    return dict(common, type="message", message=message)
