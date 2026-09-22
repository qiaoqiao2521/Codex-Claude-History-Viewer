"""Native CodeBuddy/cbc shapes, synthetic histories only."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from audit.codebuddy import normalize_codebuddy_record
from audit.extractor import _claude_events, build_audit_from_events
from history_core.codebuddy import CODEBUDDY_ALIASES, parse_codebuddy_session_file


def record(kind, **fields):
    return {"type": kind, "timestamp": 1790078400000, "sessionId": "cb-session", "cwd": "/synthetic/project", **fields}


class CodeBuddyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, records, name="cb-session.jsonl"):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in records))
        return path

    def test_native_messages_reasoning_tools_and_usage_only_wrapper(self):
        rows = [
            record("message", id="user", role="user", content=[{"type": "input_text", "text": "Find the failure"}]),
            record("reasoning", id="think", content=[{"type": "reasoning_text", "text": "Check the fixture"}]),
            record("function_call", id="call-record", callId="tool-1", name="Bash", arguments=json.dumps({"command": "pytest"}),
                   message={"usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "cache_read_input_tokens": 80}}),
            record("function_call_result", id="result", callId="tool-1", name="Bash", status="completed",
                   output={"type": "text", "text": "Exit code: 1\nfailed"}),
            record("message", id="reply", role="assistant", content=[{"type": "output_text", "text": "The test failed."}]),
            record("turn-metrics", tokenDelta=120, durationMs=200),
            record("ai-title", aiTitle="Native title"),
        ]
        path = self.write(rows)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        parsed = parse_codebuddy_session_file(path)
        self.assertEqual(parsed["id"], "cb-session")
        self.assertEqual(parsed["cwd"], "/synthetic/project")
        self.assertEqual(parsed["title"], "Native title")
        self.assertEqual(parsed["file_path"], str(path))
        self.assertEqual(parsed["message_count"], 2)
        self.assertEqual([msg["kind"] for msg in parsed["messages"]], ["message", "thinking", "tool_use", "tool_result", "message"])
        self.assertIn("pytest", parsed["search_blob"])
        self.assertEqual(parsed["usage"], {"input": 100, "output": 20, "cached": 80, "reasoning": 0, "total": 120})
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_cache_is_subset_not_added_twice_and_usage_dedup_is_message_scoped(self):
        def usage_row(native_id, provider_id, total):
            return record("function_call", id=native_id, callId=native_id, name="Read", arguments="{}",
                          providerData={"messageId": provider_id, "conversationRequestId": "one-request-many-responses"},
                          message={"usage": {"input_tokens": total - 10, "output_tokens": 10,
                                             "cache_read_input_tokens": 50, "total_tokens": total}})
        rows = [usage_row("row1", "response1", 100), usage_row("row1-update", "response1", 120),
                usage_row("row2", "response2", 100)]
        parsed = parse_codebuddy_session_file(self.write(rows))
        self.assertEqual(parsed["usage"], {"input": 200, "output": 20, "cached": 100, "reasoning": 0, "total": 220})

    def test_provider_usage_fallback_and_reasoning_are_not_extra_total(self):
        row = record("message", id="reply", role="assistant", content=[{"type": "output_text", "text": "Done"}],
                     providerData={"messageId": "native-provider-id", "usage": {"inputTokens": 90, "outputTokens": 10, "totalTokens": 100},
                                   "rawUsage": {"prompt_tokens_details": {"cached_tokens": 70},
                                                "completion_tokens_details": {"reasoning_tokens": 6}}})
        self.assertEqual(parse_codebuddy_session_file(self.write([row]))["usage"],
                         {"input": 90, "output": 10, "cached": 70, "reasoning": 6, "total": 100})

    def test_no_usage_is_unknown_and_metrics_do_not_invent_tokens(self):
        rows = [record("message", role="user", content=[{"type": "input_text", "text": "hello"}]),
                record("turn-metrics", tokenDelta=999, durationMs=100)]
        self.assertIsNone(parse_codebuddy_session_file(self.write(rows))["usage"])

    def test_native_tool_error_and_exit_code_reuse_existing_audit(self):
        rows = [
            record("function_call", id="edit", callId="edit1", name="Edit", arguments=json.dumps({"file_path": "a.py", "old_string": "a", "new_string": "b"})),
            record("function_call_result", id="edit-result", callId="edit1", name="Edit", status="completed",
                   output={"type": "text", "text": "Permission denied"}, providerData={"toolResult": {"error": "permission denied"}}),
            record("function_call", id="test", callId="test1", name="Bash", arguments=json.dumps({"command": "pytest"})),
            record("function_call_result", id="test-result", callId="test1", name="Bash", status="completed",
                   output={"type": "text", "text": "Exit code: 0\n2 passed"}),
        ]
        events = [event for line, raw in enumerate(rows, 1) for event in _claude_events(normalize_codebuddy_record(raw), line)]
        audit = build_audit_from_events(events, session_id="cb-session", source="codebuddy")
        self.assertEqual(audit.source, "codebuddy")
        self.assertEqual(audit.errors["count"], 1)
        self.assertEqual(audit.commands[0]["exit_code"], 0)
        self.assertEqual(audit.commands[0]["status"], "pass")
        self.assertEqual(audit.files_touched["local"][0]["path"], "a.py")
        self.assertEqual(audit.evidence[0]["raw_ref"]["line_no"], 1)
        completed = normalize_codebuddy_record(rows[-1])["message"]["content"][0]
        self.assertNotIn("is_error", completed, "completed alone must not imply success")

    def test_agent_sidecar_keeps_its_identity_instead_of_parent_session_id(self):
        rows = [record("message", role="user", content=[{"type": "input_text", "text": "child task"}]),
                record("session-meta", sessionId="agent-child", meta={})]
        self.assertEqual(parse_codebuddy_session_file(self.write(rows, "agent-child.jsonl"))["id"], "agent-child")

    def test_fallback_ids_are_scoped_by_relative_file_identity(self):
        row = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "no session ID"}]}
        first = self.write([row], "one.jsonl")
        second = self.write([row], "two.jsonl")
        a = parse_codebuddy_session_file(first, display_root=self.root)
        b = parse_codebuddy_session_file(second, display_root=self.root)
        self.assertTrue(a["id"].startswith("file-"))
        self.assertNotEqual(a["id"], b["id"])
        self.assertFalse(a["cwd"], "do not invent cwd from an encoded project folder")

    def test_malformed_tail_remains_visible_and_fully_invalid_file_is_rejected(self):
        path = self.write([record("message", role="user", content=[{"type": "input_text", "text": "hello"}])])
        with path.open("a") as stream:
            stream.write('{"partial":')
        parsed = parse_codebuddy_session_file(path)
        self.assertEqual(parsed["messages"][-1]["kind"], "raw_json:malformed_line")
        path.write_text('{"partial":')
        with self.assertRaisesRegex(ValueError, "invalid_session_file"):
            parse_codebuddy_session_file(path)
        self.assertIsNone(parse_codebuddy_session_file(self.root / "missing.jsonl"))

    def test_aliases_are_one_canonical_source_and_agent_files_are_excluded(self):
        from history_core.providers import canonical_source, include_file
        self.assertEqual({canonical_source(alias) for alias in CODEBUDDY_ALIASES}, {"codebuddy"})
        self.assertFalse(include_file("codebuddy", Path("agent-child.jsonl")))
        self.assertTrue(include_file("codebuddy", Path("session.jsonl")))


if __name__ == "__main__":
    unittest.main()
