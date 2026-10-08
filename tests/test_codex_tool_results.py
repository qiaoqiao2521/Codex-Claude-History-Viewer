"""Codex tool evidence survives structured native result envelopes."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from history_core.providers import parser_version
from history_core.reader import HistoryReader
from history_core.sources import (_codex_format_tool_result, _codex_summarize_tool_result,
                                  parse_codex_session_file)


class CodexToolResultTests(unittest.TestCase):
    def test_native_object_matches_json_string(self):
        value = {"output": "READBACK_OK", "metadata": {"exit_code": 0, "duration_seconds": 0.25}}
        encoded = json.dumps(value)
        self.assertEqual(_codex_format_tool_result("shell_command", "c1", value),
                         _codex_format_tool_result("shell_command", "c1", encoded))
        self.assertEqual(_codex_summarize_tool_result("shell_command", value),
                         _codex_summarize_tool_result("shell_command", encoded))

    def test_list_text_blocks_keep_body_and_error(self):
        value = [{"type": "text", "text": "FIRST_RESULT"},
                 {"output": "FAILED_RESULT", "exit_code": 2}]
        text = _codex_format_tool_result("exec", "c1", value)
        self.assertIn("FIRST_RESULT", text)
        self.assertIn("FAILED_RESULT", text)
        self.assertIn("Exit code: 2", text)
        summary = _codex_summarize_tool_result("exec", value)
        self.assertTrue(summary["is_error"])
        self.assertEqual(summary["exit_code"], 2)

    def test_text_block_json_is_literal_not_result_metadata(self):
        raw = '{"output":"BODY_RESULT","exit_code":2,"isError":true}'
        value = {"content": [{"type": "text", "text": raw}]}
        self.assertIn(raw, _codex_format_tool_result("exec", raw_output=value))
        summary = _codex_summarize_tool_result("exec", value)
        self.assertEqual(summary["output_preview"], raw)
        self.assertIsNone(summary["exit_status"])
        self.assertIsNone(summary["exit_code"])

    def test_deep_json_list_has_bounded_fallback(self):
        raw = '[' * 500 + '{"type":"text","text":"DEPTH_OK"}' + ']' * 500
        self.assertIn("[unsupported tool output: nesting limit]", _codex_format_tool_result("exec", raw_output=raw))
        self.assertIsNone(_codex_summarize_tool_result("exec", raw)["exit_status"])

    def test_content_envelope_and_explicit_error_without_exit_code(self):
        value = {"content": [{"type": "text", "text": "ACCESS_DENIED"}], "isError": True}
        self.assertIn("ACCESS_DENIED", _codex_format_tool_result("read", raw_output=value))
        summary = _codex_summarize_tool_result("read", value)
        self.assertEqual(summary["exit_status"], "error")
        self.assertTrue(summary["is_error"])
        self.assertIsNone(summary["exit_code"])

    def test_error_overrides_zero_exit_code(self):
        value = {"output": "failure detail", "metadata": {"exit_code": 0}, "error": {"message": "TOOL_DENIED"}}
        text = _codex_format_tool_result("read", raw_output=value)
        self.assertIn("Status: error", text)
        self.assertIn("TOOL_DENIED", text)
        self.assertTrue(_codex_summarize_tool_result("read", value)["is_error"])

    def test_failure_in_batch_is_not_hidden_by_later_success(self):
        value = [{"output": "FAILED", "exit_code": 3}, {"output": "OK", "exit_code": 0}]
        summary = _codex_summarize_tool_result("exec", value)
        self.assertEqual(summary["exit_code"], 3)
        self.assertEqual(summary["exit_status"], "error")

    def test_plain_text_metadata_matches_expanded_and_collapsed_status(self):
        text = _codex_format_tool_result("shell_command", raw_output="Exit code: 1\nWall time: 0.1 seconds\nOutput:\nFAILED")
        self.assertIn("Status: error", text)
        self.assertIn("Wall time: 0.1 seconds", text)

    def test_media_payloads_are_not_expanded_or_previewed(self):
        content = [{"type": "text", "text": "VISIBLE_TEXT"},
                   {"type": "image", "data": "BASE64_SENTINEL", "mimeType": "image/png"},
                   {"type": "audio", "data": "BASE64_SENTINEL"},
                   {"type": "resource", "resource": {"blob": "BASE64_SENTINEL"}}]
        for value in (content, json.dumps(content)):
            with self.subTest(value_type=type(value).__name__):
                text = _codex_format_tool_result("mcp", raw_output=value)
                self.assertIn("VISIBLE_TEXT", text)
                self.assertIn("[image content omitted]", text)
                self.assertIn("[audio content omitted]", text)
                self.assertIn("[resource content omitted]", text)
                self.assertNotIn("BASE64_SENTINEL", text)
                self.assertNotIn("BASE64_SENTINEL", _codex_summarize_tool_result("mcp", value)["output_preview"])

    def test_empty_and_unknown_shapes_are_visible_without_invented_success(self):
        for value in (None, "", [], {"output": ""}):
            with self.subTest(value=value):
                self.assertIn("[empty tool output]", _codex_format_tool_result("exec", raw_output=value))
                self.assertIsNone(_codex_summarize_tool_result("exec", value)["exit_status"])
        for value in (42, {"unknown": "RAW_UNSUPPORTED"}, {"type": ["unknown"]}):
            with self.subTest(value=value):
                self.assertIn("[unsupported tool output:", _codex_format_tool_result("exec", raw_output=value))
                self.assertIsNone(_codex_summarize_tool_result("exec", value)["exit_status"])

    def test_ordinary_json_stdout_is_preserved_as_text(self):
        raw = '{"answer": 42}'
        self.assertIn(raw, _codex_format_tool_result("shell_command", raw_output=raw))

    def test_business_json_stdout_with_status_is_preserved(self):
        raw = '{"status":"healthy","result":"READBACK_OK"}'
        self.assertIn(raw, _codex_format_tool_result("shell_command", raw_output=raw))
        summary = _codex_summarize_tool_result("shell_command", raw)
        self.assertEqual(summary["output_preview"], raw)
        self.assertIsNone(summary["exit_status"])

    def test_envelope_json_body_stays_literal(self):
        raw = '{"status":"healthy","result":"READBACK_OK"}'
        value = {"output": raw, "metadata": {"exit_code": 0}}
        for envelope in (value, json.dumps(value)):
            with self.subTest(envelope_type=type(envelope).__name__):
                self.assertIn(raw, _codex_format_tool_result("shell_command", raw_output=envelope))
                summary = _codex_summarize_tool_result("shell_command", envelope)
                self.assertEqual(summary["output_preview"], raw)
                self.assertEqual(summary["exit_status"], "ok")

    def test_envelope_object_body_keeps_application_fields(self):
        value = {"output": {"answer": "READBACK_OK", "status": "healthy", "error": "historical"},
                 "metadata": {"exit_code": 0}}
        for envelope in (value, json.dumps(value)):
            with self.subTest(envelope_type=type(envelope).__name__):
                text = _codex_format_tool_result("shell_command", raw_output=envelope)
                self.assertIn('"answer": "READBACK_OK"', text)
                self.assertIn('"status": "healthy"', text)
                self.assertIn('"error": "historical"', text)
                self.assertNotIn("unsupported", text)
                self.assertEqual(_codex_summarize_tool_result("shell_command", envelope)["exit_status"], "ok")

    def test_object_body_serialization_omits_nested_media_bytes(self):
        value = {"output": {"answer": "READBACK_OK", "attachment": {"type": "image", "data": "BASE64_SENTINEL"}},
                 "metadata": {"exit_code": 0}}
        for envelope in (value, json.dumps(value)):
            with self.subTest(envelope_type=type(envelope).__name__):
                text = _codex_format_tool_result("mcp", raw_output=envelope)
                self.assertIn("READBACK_OK", text)
                self.assertIn("[image content omitted]", text)
                self.assertNotIn("BASE64_SENTINEL", text)
                self.assertNotIn("BASE64_SENTINEL", _codex_summarize_tool_result("mcp", envelope)["output_preview"])

    def test_plain_json_stdout_omits_nested_media_bytes(self):
        raw = json.dumps({"answer": "READBACK_OK", "attachment": {"type": "image", "data": "BASE64_SENTINEL"}})
        for value, expected_status in ((raw, None), ("Exit code: 0\nWall time: 0.1 seconds\nOutput:\n" + raw, "ok")):
            with self.subTest(wrapped=expected_status is not None):
                text = _codex_format_tool_result("mcp", raw_output=value)
                self.assertIn("READBACK_OK", text)
                self.assertIn("[image content omitted]", text)
                self.assertNotIn("BASE64_SENTINEL", text)
                summary = _codex_summarize_tool_result("mcp", value)
                self.assertNotIn("BASE64_SENTINEL", summary["output_preview"])
                self.assertEqual(summary["exit_status"], expected_status)

    def test_plain_data_uri_does_not_expand_media_bytes(self):
        raw = "data:image/png;base64,BASE64_SENTINEL"
        for value, expected_status in ((raw, None), ("Exit code: 0\nWall time: 0.1 seconds\nOutput:\n" + raw, "ok")):
            with self.subTest(wrapped=expected_status is not None):
                text = _codex_format_tool_result("mcp", raw_output=value)
                self.assertIn("[encoded media content omitted]", text)
                self.assertNotIn("BASE64_SENTINEL", text)
                summary = _codex_summarize_tool_result("mcp", value)
                self.assertNotIn("BASE64_SENTINEL", summary["output_preview"])
                self.assertEqual(summary["exit_status"], expected_status)


class CodexToolReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = self.root / "sessions"
        self.logs.mkdir()
        self.cache = self.root / "cache"
        self.path = self.logs / "structured.jsonl"
        records = [{"type": "session_meta", "timestamp": "2026-10-08T00:00:00Z",
                    "payload": {"id": "structured", "cwd": "/synthetic/tools"}}]
        payloads = [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Check tool evidence"}]},
            {"type": "function_call", "name": "shell_command", "call_id": "c1", "arguments": '{"command":"verify"}'},
            {"type": "function_call_output", "call_id": "c1", "output": {"output": "READBACK_OK", "metadata": {"exit_code": 0}}},
            {"type": "custom_tool_call", "name": "read", "call_id": "c2", "input": "read fixture"},
            {"type": "custom_tool_call_output", "call_id": "c2", "content": [{"type": "text", "text": "READER_ERROR_DETAIL"}], "isError": True},
            {"type": "function_call_output", "call_id": "c3", "output": '{"status":"healthy","result":"JSON_STDOUT_OK"}'},
            {"type": "function_call_output", "call_id": "c4", "output": {
                "output": '{"status":"healthy","result":"JSON_BODY_OK"}', "metadata": {"exit_code": 0}}},
            {"type": "function_call_output", "call_id": "c5", "output": {
                "output": {"answer": "OBJECT_BODY_OK"}, "metadata": {"exit_code": 0}}},
        ]
        records += [{"type": "response_item", "timestamp": f"2026-10-08T00:00:0{i + 1}Z", "payload": p}
                    for i, p in enumerate(payloads)]
        self.path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        self.original = self.path.read_bytes()

    def tearDown(self):
        self.assertEqual(self.path.read_bytes(), self.original, "reader changed the source recording")

    def test_native_parser_content_fallback_and_top_level_error(self):
        parsed = parse_codex_session_file(self.path)
        results = [row for row in parsed["messages"] if row["kind"] == "tool_result"]
        self.assertEqual(results[0]["raw_ref"], {"line_no": 4})
        self.assertIn("READBACK_OK", results[0]["text"])
        self.assertFalse(results[0]["tool_result_error"])
        self.assertIn("READER_ERROR_DETAIL", results[1]["text"])
        self.assertTrue(results[1]["tool_result_error"])
        self.assertEqual(results[1]["tool_call_id"], "c2")

    def test_public_reader_refresh_search_activity_and_old_cache_reparse(self):
        with patch("history_core.reader.parser_version", return_value=5):
            with HistoryReader("codex", self.logs, self.cache) as old:
                self.assertEqual(old.refresh()["status"], "refreshed")
        database = next(self.cache.glob("machine-codex-*/index.sqlite"))
        with sqlite3.connect(database) as db:
            # Reproduce the old cache's lost object bodies without changing
            # the native recording's bytes, size, timestamp, or identity.
            db.execute("UPDATE messages SET text='Tool result: shell_command', tool_summary_json=NULL WHERE kind='tool_result'")
            db.execute("UPDATE sessions SET search_blob='Check tool evidence', parser_version=5")
        with HistoryReader("codex", self.logs, self.cache) as reader:
            self.assertEqual(reader.refresh()["status"], "refreshed")
            self.assertEqual([row["id"] for row in reader.search(query="READBACK_OK")["items"]], ["structured"])
            for keyword in ("JSON_STDOUT_OK", "JSON_BODY_OK", "OBJECT_BODY_OK"):
                self.assertEqual([row["id"] for row in reader.search(query=keyword)["items"]], ["structured"])
            activity = reader.activity(date="2026-10-08", timezone="Asia/Shanghai", refresh=True,
                                       session_id="structured", evidence_limit=10)
            results = [e for e in activity["items"][0]["evidence"] if e["kind"] == "tool_result"]
            self.assertEqual(len(results), 5)
            self.assertIn("READBACK_OK", results[0]["text"])
            self.assertIn("READER_ERROR_DETAIL", results[1]["text"])
            self.assertIn("Status: error", results[1]["text"])
            self.assertIn('{"status":"healthy","result":"JSON_STDOUT_OK"}', results[2]["text"])
            self.assertIn('{"status":"healthy","result":"JSON_BODY_OK"}', results[3]["text"])
            self.assertIn('"answer": "OBJECT_BODY_OK"', results[4]["text"])
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("SELECT parser_version FROM sessions").fetchone()[0], parser_version("codex"))
        self.assertEqual(parser_version("codex"), 6)
        self.assertEqual(parser_version("claude"), 5)


if __name__ == "__main__":
    unittest.main()
