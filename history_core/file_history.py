"""Explicit, revision-bound file tool records; never a current-filesystem diff."""
import difflib
import json
import posixpath
import re

from .provenance import selected_snapshot

MAX_CHANGE_RECORDS = 50
MAX_DIFF_CHARS = 8000
MAX_TOTAL_DIFF_CHARS = 16000
_PATCH_HEADER = re.compile(r"^\*\*\* (Update|Add|Delete) File: (.+)$")


def _path(value, project):
    value = str(value or "")
    return posixpath.normpath(value if value.startswith("/") else posixpath.join(project, value))


def _arguments(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _tool_records(raw, source):
    """Read only explicit tool envelopes, reusing the snapshot's JSONL lines."""
    calls, results = [], []
    for line_no, line in enumerate(raw.splitlines(), 1):
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(record, dict):
            continue
        if source == "codex":
            payload = record.get("payload")
            if record.get("type") != "response_item" or not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            if kind in ("function_call", "custom_tool_call"):
                calls.append({"id": payload.get("call_id"), "name": str(payload.get("name") or ""),
                              "arguments": _arguments(payload.get("arguments") if kind == "function_call" else payload.get("input")),
                              "line_no": line_no, "content_index": None})
            elif kind in ("function_call_output", "custom_tool_call_output"):
                results.append({"id": payload.get("call_id"), "value": payload.get("output"),
                                "is_error": payload.get("is_error"), "line_no": line_no})
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            message = record if source == "openclaw" else {}
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for content_index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                calls.append({"id": block.get("id"), "name": str(block.get("name") or ""),
                              "arguments": block.get("input"), "line_no": line_no,
                              "content_index": content_index})
            elif block.get("type") == "tool_result":
                results.append({"id": block.get("tool_use_id"), "value": block.get("content"),
                                "is_error": block.get("is_error"), "line_no": line_no})
    return calls, results


def _result_status(result, source):
    if result.get("is_error") is True:
        return "failed"
    value = result.get("value")
    parsed = _arguments(value)
    if isinstance(parsed, dict):
        if parsed.get("is_error") is True:
            return "failed"
        metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        code = parsed.get("exit_code", metadata.get("exit_code"))
        if type(code) is int:
            return "success" if code == 0 else "failed"
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    # These are explicit tool result markers, never assistant prose or tool args.
    exit_match = re.search(r"(?im)^\s*(?:process exited with code|exit code:)\s*(-?\d+)\s*$", text)
    if exit_match:
        return "success" if int(exit_match.group(1)) == 0 else "failed"
    if re.search(r"(?im)^\s*(?:error\s*:|failed\b|apply_patch verification failed\b)", text):
        return "failed"
    if source in ("claude", "openclaw") and result.get("is_error") is False:
        return "success"
    if re.search(r"(?im)^\s*Success\.\s*Updated the following files:", text):
        return "success"
    if source in ("claude", "openclaw") and re.search(
            r"(?i)(?:file created successfully at|file .* has been (?:updated|written) successfully)", text):
        return "success"
    return "unknown"


def _patch_sections(value):
    if isinstance(value, dict):
        value = value.get("patch", value.get("input", value.get("patch_text")))
    if not isinstance(value, str) or not value.startswith("*** Begin Patch\n"):
        return []
    if not value.rstrip().endswith("*** End Patch"):
        return []
    sections, current = [], None
    for line in value.splitlines()[1:]:
        match = _PATCH_HEADER.fullmatch(line)
        if match:
            if current:
                sections.append(current)
            current = {"operation": match.group(1).lower(), "path": match.group(2), "lines": [line]}
        elif line == "*** End Patch":
            if current:
                sections.append(current)
            current = None
        elif current:
            current["lines"].append(line)
            if line.startswith("*** Move to: "):
                current["renamed_to"] = line[len("*** Move to: "):]
    return sections


def _changes(call, project, target):
    name = call["name"].rsplit(".", 1)[-1].lower()
    args = call["arguments"]
    changes = []
    if name == "apply_patch":
        for section in _patch_sections(args):
            original = section["path"]
            renamed_to = section.get("renamed_to")
            if not any(_path(value, project) == target for value in (original, renamed_to) if value):
                continue
            diff = "*** Begin Patch\n" + "\n".join(section["lines"]) + "\n*** End Patch\n"
            changes.append({"path": original, "operation": section["operation"], "diff": diff,
                            "diff_scope": "explicit_patch", "renamed_to": renamed_to})
    elif name in ("edit", "write") and isinstance(args, dict):
        path = args.get("file_path", args.get("path"))
        if not isinstance(path, str) or not path or _path(path, project) != target:
            return []
        diff = None
        if name == "edit" and isinstance(args.get("old_string"), str) and isinstance(args.get("new_string"), str):
            old, new = args["old_string"], args["new_string"]
            if len(old) + len(new) > MAX_DIFF_CHARS:
                raise ValueError("file_history_diff_limit_exceeded")
            diff = "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                                  fromfile=path + " (recorded old fragment)",
                                                  tofile=path + " (recorded new fragment)", lineterm=""))
        changes.append({"path": path, "operation": name, "diff": diff,
                        "diff_scope": "explicit_replacement_fragment" if diff is not None else "unavailable_no_before_content",
                        "replace_all": bool(args.get("replace_all")) if name == "edit" else None})
    return changes


def file_changes(indexer, session_id, project, file_path, provenance):
    """Selected path's explicit calls/results from the caller's exact revision.

    ``status`` is attempted (no paired result), unknown (ambiguous result),
    success or failed (explicit paired result). A diff is the attempted input,
    not proof the change was applied. Source/diff limits fail explicitly.
    """
    source = getattr(indexer, "source", "")
    if source not in ("codex", "claude", "openclaw") or getattr(indexer, "sessions_dir", None) is None:
        raise ValueError("file_history_source_unsupported")
    if not isinstance(project, str) or not isinstance(file_path, str) or not file_path:
        raise ValueError("file_history_path_required")
    metadata = indexer.get_session_metadata(session_id)
    if metadata is None:
        raise ValueError("file_history_session_unavailable")
    if (metadata.get("cwd") or "") != project:
        raise ValueError("file_history_project_mismatch")
    if not isinstance(provenance, dict):
        raise ValueError("file_history_revision_required")
    expected = provenance.get("content_revision")
    if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
        if provenance.get("truncated"):
            raise ValueError("file_history_source_limit_exceeded")
        raise ValueError("file_history_revision_required")
    if provenance.get("source") != source or str(provenance.get("session_id")) != str(session_id):
        raise ValueError("file_history_identity_mismatch")
    try:
        audit, fresh, raw = selected_snapshot(indexer, session_id)
    except (ValueError, OSError) as error:
        if "changed" in str(error):
            raise ValueError("file_history_stale") from error
        raise ValueError("file_history_source_unavailable") from error
    if audit is None or raw is None:
        raise ValueError("file_history_source_unavailable")
    if fresh.get("truncated"):
        raise ValueError("file_history_source_limit_exceeded")
    if fresh.get("status") != "captured" or fresh.get("content_revision") != expected:
        raise ValueError("file_history_stale")
    target = _path(file_path, project)
    calls, results = _tool_records(raw, source)
    output, total_diff = [], 0
    ids = {}
    for call in calls:
        if isinstance(call["id"], str) and call["id"]:
            ids[call["id"]] = ids.get(call["id"], 0) + 1
    for call in calls:
        changes = _changes(call, project, target)
        if not changes:
            continue
        call_id = call["id"] if isinstance(call["id"], str) else None
        matches = [result for result in results if call_id and result["id"] == call_id
                   and result["line_no"] > call["line_no"]]
        paired = matches[0] if ids.get(call_id) == 1 and len(matches) == 1 else None
        status = _result_status(paired, source) if paired else ("unknown" if matches else "attempted")
        candidates = [item for item in audit.get("evidence", []) if item.get("type") == "tool_call"
                      and (item.get("raw_ref") or {}).get("line_no") == call["line_no"]
                      and item.get("tool_name") == call["name"]]
        for change in changes:
            diff = change.get("diff")
            if diff is not None and len(diff) > MAX_DIFF_CHARS:
                raise ValueError("file_history_diff_limit_exceeded")
            total_diff += len(diff or "")
            if len(output) >= MAX_CHANGE_RECORDS or total_diff > MAX_TOTAL_DIFF_CHARS:
                raise ValueError("file_history_result_limit_exceeded")
            change.update(scope="local", status=status, call_id=call_id, tool_name=call["name"],
                          line_no=call["line_no"], content_index=call["content_index"],
                          raw_ref={"line_no": call["line_no"], "content_index": call["content_index"]},
                          result_line_no=paired["line_no"] if paired else None,
                          content_revision=expected, observed_at=fresh.get("observed_at"),
                          current_file_status="unknown")
            if len(candidates) == 1:
                change["evidence_id"] = candidates[0]["id"]
            # Audit event indices differ from browser message indices. Keep the
            # exact raw line/block locator until the shared index stores a map.
            output.append(change)
    return output
