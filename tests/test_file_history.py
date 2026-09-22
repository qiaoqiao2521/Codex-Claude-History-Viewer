import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from history_core.file_history import file_changes
from history_core.provenance import selected_audit, selected_snapshot
from history_core.sources import Indexer, parse_claude_session_file


PATCH_A = "*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n*** End Patch\n"


def codex_call(call_id="patch-1", patch_text=PATCH_A, function=False):
    payload = {"type": "function_call" if function else "custom_tool_call", "name": "apply_patch", "call_id": call_id}
    payload["arguments" if function else "input"] = json.dumps({"patch": patch_text}) if function else patch_text
    return {"type": "response_item", "payload": payload}


def codex_result(call_id="patch-1", output="Success. Updated the following files:\nM a.py"):
    return {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id, "output": output}}


def claude_call(name="Edit", call_id="edit-1", args=None):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": call_id, "name": name,
         "input": args if args is not None else {"file_path": "a.py", "old_string": "old", "new_string": "new"}}]}}


def claude_result(call_id="edit-1", error=False, content="File has been updated successfully"):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": call_id, "is_error": error, "content": content}]}}


class FileHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, records, source="codex"):
        root, cache = self.root / source, self.root / (source + "-cache")
        root.mkdir()
        cache.mkdir()
        if source == "codex":
            rows = [{"type": "session_meta", "payload": {"id": "session", "cwd": "/project"}}] + records
        else:
            rows = [{"type": "user", "message": {"role": "user", "content": "Make the requested change"}}] + records
            for row in rows:
                row.update(sessionId="session", cwd="/project")
        for number, row in enumerate(rows):
            row["timestamp"] = "2026-09-22T12:00:%02dZ" % number
        path = root / "session.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        kwargs = {"parse_file_fn": parse_claude_session_file} if source == "claude" else {}
        indexer = Indexer(root, cache, source, **kwargs)
        self.addCleanup(indexer.conn.close)
        indexer.maybe_update_index(max_age_seconds=0)
        _, provenance = selected_audit(indexer, "session")
        return indexer, path, provenance

    def changes(self, indexer, provenance, path="a.py", project="/project"):
        return file_changes(indexer, "session", project, path, provenance)

    def test_codex_explicit_success_and_failure_remain_distinct_attempted_diffs(self):
        indexer, path, provenance = self.fixture([
            codex_call("ok"), codex_result("ok"), codex_call("bad"),
            codex_result("bad", "apply_patch verification failed: expected lines missing")])
        before = path.read_bytes()
        rows = self.changes(indexer, provenance)
        self.assertEqual([row["status"] for row in rows], ["success", "failed"])
        self.assertEqual([row["diff"] for row in rows], [PATCH_A, PATCH_A])
        self.assertEqual(rows[1]["current_file_status"], "unknown")
        self.assertEqual(rows[0]["raw_ref"]["line_no"], 2)
        self.assertEqual(rows[0]["result_line_no"], 3)
        self.assertTrue(rows[0]["evidence_id"])
        self.assertNotIn("message_index", rows[0])
        self.assertEqual(path.read_bytes(), before)

    def test_json_function_input_and_structured_exit_status(self):
        indexer, _, provenance = self.fixture([
            codex_call(function=True), codex_result(output={"output": "tool response", "metadata": {"exit_code": 1}})])
        rows = self.changes(indexer, provenance)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["diff"], PATCH_A)

    def test_structured_error_flag_overrides_zero_exit_code(self):
        indexer, _, provenance = self.fixture([
            codex_call(), codex_result(output={"is_error": True, "exit_code": 0, "output": "wrapper returned"})])
        self.assertEqual(self.changes(indexer, provenance)[0]["status"], "failed")

    def test_absent_or_ambiguous_results_never_imply_success(self):
        indexer, _, provenance = self.fixture([
            codex_call("missing"), codex_call("ambiguous"), codex_result("ambiguous", "Done, check it.")])
        self.assertEqual([row["status"] for row in self.changes(indexer, provenance)], ["attempted", "unknown"])

    def test_results_join_only_by_unique_id_after_call(self):
        indexer, _, provenance = self.fixture([
            codex_result("before"), codex_call("before"), codex_call("duplicate"),
            codex_call("duplicate"), codex_result("duplicate"), codex_result("unrelated")])
        self.assertEqual([row["status"] for row in self.changes(indexer, provenance)], ["attempted", "unknown", "unknown"])

    def test_exact_file_sections_and_project_isolation(self):
        patch_text = "*** Begin Patch\n*** Update File: a.py\n@@\n-old\n+new\n*** Update File: a_backup.py\n@@\n-decoy\n+decoy-new\n*** End Patch\n"
        indexer, _, provenance = self.fixture([codex_call(patch_text=patch_text), codex_result()])
        rows = self.changes(indexer, provenance, path="/project/a.py")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("a_backup.py", rows[0]["diff"])
        self.assertEqual(self.changes(indexer, provenance, path="/different/a.py"), [])
        with self.assertRaisesRegex(ValueError, "file_history_project_mismatch"):
            self.changes(indexer, provenance, project="/different")

    def test_rename_is_linked_only_when_explicit_in_patch(self):
        patch_text = "*** Begin Patch\n*** Update File: old.py\n*** Move to: new.py\n@@\n-old\n+new\n*** End Patch\n"
        indexer, _, provenance = self.fixture([codex_call(patch_text=patch_text), codex_result()])
        old = self.changes(indexer, provenance, path="old.py")
        new = self.changes(indexer, provenance, path="new.py")
        self.assertEqual([{k: v for k, v in row.items() if k != "observed_at"} for row in old],
                         [{k: v for k, v in row.items() if k != "observed_at"} for row in new])
        self.assertEqual(old[0]["renamed_to"], "new.py")
        self.assertEqual(self.changes(indexer, provenance, path="unrecorded-alias.py"), [])

    def test_claude_edit_diff_is_only_the_explicit_old_new_fragment(self):
        indexer, _, provenance = self.fixture([claude_call(), claude_result()], source="claude")
        with patch.object(Path, "read_text", side_effect=AssertionError("must not read current project file")):
            row = self.changes(indexer, provenance)[0]
        self.assertEqual(row["status"], "success")
        self.assertIn("-old", row["diff"])
        self.assertIn("+new", row["diff"])
        self.assertEqual(row["diff_scope"], "explicit_replacement_fragment")
        self.assertEqual(row["raw_ref"]["content_index"], 0)

    def test_claude_write_without_before_content_has_no_manufactured_diff(self):
        indexer, _, provenance = self.fixture([
            claude_call(name="Write", args={"file_path": "a.py", "content": "new file text"}),
            claude_result(error=True, content="Error: Permission denied")], source="claude")
        row = self.changes(indexer, provenance)[0]
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["diff"])
        self.assertEqual(row["diff_scope"], "unavailable_no_before_content")

    def test_source_change_after_display_rejected_before_and_after_index_refresh(self):
        indexer, path, provenance = self.fixture([codex_call(), codex_result()])
        path.write_bytes(path.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(ValueError, "file_history_stale"):
            self.changes(indexer, provenance)
        indexer.maybe_update_index(max_age_seconds=0)
        with self.assertRaisesRegex(ValueError, "file_history_stale"):
            self.changes(indexer, provenance)

    def test_unstable_read_is_rejected_even_if_digest_matches(self):
        indexer, _, provenance = self.fixture([codex_call(), codex_result()])
        audit, fresh, raw = selected_snapshot(indexer, "session")
        fresh["status"] = "unknown"
        fresh["reason"] = "source_changed_during_read"
        with patch("history_core.file_history.selected_snapshot", return_value=(audit, fresh, raw)):
            with self.assertRaisesRegex(ValueError, "file_history_stale"):
                self.changes(indexer, provenance)

    def test_source_and_diff_budget_fail_explicitly(self):
        indexer, _, provenance = self.fixture([codex_call(), codex_result()])
        with patch("history_core.provenance.MAX_SOURCE_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "file_history_source_limit_exceeded"):
                self.changes(indexer, provenance)
        with patch("history_core.file_history.MAX_DIFF_CHARS", 16):
            with self.assertRaisesRegex(ValueError, "file_history_diff_limit_exceeded"):
                self.changes(indexer, provenance)

    def test_total_diff_or_record_budget_never_silently_drops_changes(self):
        indexer, _, provenance = self.fixture([codex_call("a"), codex_call("b")])
        with patch("history_core.file_history.MAX_CHANGE_RECORDS", 1):
            with self.assertRaisesRegex(ValueError, "file_history_result_limit_exceeded"):
                self.changes(indexer, provenance)
        with patch("history_core.file_history.MAX_TOTAL_DIFF_CHARS", len(PATCH_A)):
            with self.assertRaisesRegex(ValueError, "file_history_result_limit_exceeded"):
                self.changes(indexer, provenance)

    def test_unknown_revision_or_wrong_identity_cannot_bind_file_records(self):
        indexer, _, provenance = self.fixture([codex_call(), codex_result()])
        with self.assertRaisesRegex(ValueError, "file_history_revision_required"):
            self.changes(indexer, dict(provenance, content_revision="unknown"))
        with self.assertRaisesRegex(ValueError, "file_history_identity_mismatch"):
            self.changes(indexer, dict(provenance, session_id="different"))

    def test_native_source_is_explicitly_unsupported_before_unbounded_read(self):
        native = SimpleNamespace(source="opencode", get_session_metadata=Mock())
        with self.assertRaisesRegex(ValueError, "file_history_source_unsupported"):
            self.changes(native, {})
        native.get_session_metadata.assert_not_called()


if __name__ == "__main__":
    unittest.main()
