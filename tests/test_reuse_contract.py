"""Cross-source product contracts, using only synthetic local JSONL histories."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from history_core import reuse
from history_core.sources import Indexer, parse_claude_session_file


class ReuseContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.indexers = []
        self.sources = {}
        self.tick = 0

    def add_session(self, source, session_id, project="/repo/one", text="repair sqlite lock", file_path=None, fail=False):
        source_root = self.root / source
        source_root.mkdir(exist_ok=True)
        self.tick += 1
        stamp = 1789992000000 + self.tick * 10000
        if source == "codex":
            rows = [{"type": "session_meta", "timestamp": stamp,
                     "payload": {"id": session_id, "cwd": project}},
                    {"type": "response_item", "timestamp": stamp + 1, "payload": {
                        "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}]
            if file_path:
                rows.extend([
                    {"type": "response_item", "timestamp": stamp + 2, "payload": {
                        "type": "function_call", "name": "write", "call_id": "call-write",
                        "arguments": json.dumps({"file_path": file_path, "content": "print('hello')"})}},
                    {"type": "response_item", "timestamp": stamp + 3, "payload": {
                        "type": "function_call_output", "call_id": "call-write",
                        "output": "Error: Permission denied" if fail else "file written"}}])
        else:
            rows = [{"type": "user", "timestamp": stamp, "sessionId": session_id, "cwd": project,
                     "message": {"role": "user", "content": text}}]
            if file_path:
                rows.extend([
                    {"type": "assistant", "timestamp": stamp + 1, "sessionId": session_id, "cwd": project,
                     "message": {"role": "assistant", "content": [
                         {"type": "tool_use", "id": "call-write", "name": "Write",
                          "input": {"file_path": file_path, "content": "print('hello')"}}]}},
                    {"type": "user", "timestamp": stamp + 2, "sessionId": session_id, "cwd": project,
                     "message": {"role": "user", "content": [
                         {"type": "tool_result", "tool_use_id": "call-write", "is_error": fail,
                          "content": "Error: Permission denied" if fail else "file written"}]}}])
        path = source_root / (session_id + ".jsonl")
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        return path

    def start(self):
        for source_root in sorted(self.root.iterdir()):
            if source_root.name not in ("codex", "claude"):
                continue
            source = source_root.name
            cache = self.root / (source + "-cache")
            cache.mkdir()
            kwargs = {"parse_file_fn": parse_claude_session_file} if source == "claude" else {}
            indexer = Indexer(source_root, cache, source, **kwargs)
            self.addCleanup(indexer.conn.close)
            indexer.maybe_update_index(max_age_seconds=0)
            self.sources[source] = indexer
            self.indexers.append(("linux", source, indexer))

    def all_pages(self, function, **kwargs):
        cursor, items, cursors = None, [], set()
        for _ in range(100):
            page = function(self.indexers, cursor=cursor, **kwargs)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if not cursor:
                return items
            self.assertNotIn(cursor, cursors, "pagination cursor loop")
            cursors.add(cursor)
        self.fail("pagination never completed")

    def source_digests(self):
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for source in ("codex", "claude") for path in (self.root / source).glob("*.jsonl")}

    def test_same_id_from_two_sources_remains_two_precisely_located_hits(self):
        self.add_session("codex", "duplicate")
        self.add_session("claude", "duplicate")
        self.start()
        page = reuse.search(self.indexers, query="sqlite lock")
        self.assertEqual(len(page["items"]), 2)
        identities = {(row["source"], row["store_id"], row["id"]) for row in page["items"]}
        self.assertEqual(len(identities), 2)
        for row in page["items"]:
            self.assertTrue(row["match_reason"])
            self.assertEqual(row["snippets"][0]["message_index"], 0)
            actual = self.sources[row["source"]].get_session_message(row["id"], 0)
            self.assertIn("sqlite lock", actual["text"])
        self.assertFalse(page["partial"])

    def test_project_identity_is_full_path_and_unbound_remains_accessible(self):
        self.add_session("codex", "a", "/home/a/repo")
        self.add_session("claude", "b", "/home/b/repo")
        self.add_session("claude", "c", "/home/a/repo")
        self.add_session("codex", "unbound", "")
        self.start()
        page = reuse.projects(self.indexers)
        groups = {row["project"]: row for row in page["items"]}
        self.assertEqual(set(groups), {"/home/a/repo", "/home/b/repo", ""})
        self.assertEqual(groups["/home/a/repo"]["session_count"], 2)
        self.assertEqual(len(groups["/home/a/repo"]["sources"]), 2)
        self.assertEqual(groups["/home/a/repo"]["label"], groups["/home/b/repo"]["label"])
        self.assertEqual([row["id"] for row in reuse.timeline(self.indexers, project="")["items"]], ["unbound"])

    def test_projects_over_twenty_paginate_without_omission(self):
        for index in range(27):
            self.add_session("codex" if index % 2 else "claude", "s%02d" % index, "/repo/p%02d" % index)
        self.start()
        first = reuse.projects(self.indexers, limit=20)
        self.assertEqual(len(first["items"]), 20)
        self.assertIsNotNone(first["next_cursor"])
        all_items = self.all_pages(reuse.projects, limit=20)
        self.assertEqual(len(all_items), 27)
        self.assertEqual(len({row["project"] for row in all_items}), 27)

    def test_project_timeline_over_twenty_cross_source_sessions_is_complete(self):
        for index in range(27):
            self.add_session("codex" if index % 2 else "claude", "s%02d" % index)
        self.start()
        all_items = self.all_pages(reuse.timeline, project="/repo/one", limit=20)
        self.assertEqual(len(all_items), 27)
        self.assertEqual(len({(row["source"], row["store_id"], row["id"]) for row in all_items}), 27)
        for row in all_items:
            self.assertEqual(row["current_verification"], "unknown")
            self.assertEqual(row["evidence_status"], "available")
            self.assertTrue(row["evidence"])

    def test_file_timeline_is_exact_project_isolated_and_filters_before_paging(self):
        expected = set()
        for index in range(26):
            source = "codex" if index % 2 else "claude"
            sid = "match%02d" % index
            expected.add((source, sid))
            self.add_session(source, sid, file_path="a.py" if index % 2 else "/repo/one/a.py")
        # Newer non-matches would fill the initial page if filtering occurred
        # only after a generic page was selected.
        for index in range(24):
            self.add_session("codex", "decoy%02d" % index, file_path="a_backup.py")
            self.add_session("claude", "other%02d" % index, project="/repo/two", file_path="a.py")
        self.start()
        items = self.all_pages(reuse.timeline, project="/repo/one", file_path="a.py", limit=20)
        self.assertEqual({(row["source"], row["id"]) for row in items}, expected)
        self.assertEqual(len(items), 26)
        self.assertTrue(all(row["project"] == "/repo/one" for row in items))
        self.assertTrue(all(row["diff_status"] == "unavailable" for row in items))

    def test_cursor_rejects_index_revision_change_and_query_change(self):
        for index in range(3):
            self.add_session("codex", "s%d" % index)
        self.start()
        cursor = reuse.search(self.indexers, query="sqlite", limit=1)["next_cursor"]
        with self.assertRaisesRegex(ValueError, "cursor_query_changed"):
            reuse.search(self.indexers, query="repair", limit=1, cursor=cursor)
        self.add_session("codex", "new")
        self.sources["codex"].maybe_update_index(max_age_seconds=0)
        with self.assertRaisesRegex(ValueError, "index_revision_changed"):
            reuse.search(self.indexers, query="sqlite", limit=1, cursor=cursor)

    def test_cursor_binds_all_participating_sources_not_only_hit_source(self):
        self.add_session("codex", "hit1")
        self.add_session("codex", "hit2")
        self.add_session("claude", "nohit", text="other question")
        self.start()
        cursor = reuse.search(self.indexers, query="sqlite", limit=1)["next_cursor"]
        self.add_session("claude", "still-nohit", text="another unrelated question")
        self.sources["claude"].maybe_update_index(max_age_seconds=0)
        with self.assertRaisesRegex(ValueError, "index_revision_changed"):
            reuse.search(self.indexers, query="sqlite", limit=1, cursor=cursor)

    def test_empty_result_is_distinct_from_partial_source_failure(self):
        self.add_session("codex", "working")
        self.start()
        page = reuse.search(self.indexers, query="absent-query")
        self.assertEqual(page["items"], [])
        self.assertFalse(page["partial"])
        self.assertEqual(page["errors"], [])
        missing = SimpleNamespace(source="claude", sessions_dir=self.root / "missing-source")
        mixed = self.indexers + [("linux", "claude", missing)]
        page = reuse.search(mixed, query="sqlite")
        self.assertEqual(len(page["items"]), 1)
        self.assertTrue(page["partial"])
        self.assertEqual(page["errors"], [{"system": "linux", "source": "claude", "error": "source_not_found"}])
        scoped = reuse.search(mixed, query="sqlite", source="codex")
        self.assertFalse(scoped["partial"])

    def test_missing_source_stays_partial_for_projects_and_timeline(self):
        self.add_session("codex", "working")
        self.start()
        missing = SimpleNamespace(source="claude", sessions_dir=self.root / "missing-source")
        mixed = self.indexers + [("linux", "claude", missing)]
        for method, kwargs in ((reuse.projects, {}), (reuse.timeline, {"project": "/repo/one"})):
            with self.subTest(method=method.__name__):
                page = method(mixed, **kwargs)
                self.assertTrue(page["partial"])
                self.assertTrue(page["items"])
                self.assertEqual(page["errors"][0]["error"], "source_not_found")

    def test_search_project_file_reads_leave_original_sources_unchanged(self):
        self.add_session("codex", "failed", file_path="a.py", fail=True)
        self.add_session("claude", "later", file_path="b.py")
        self.start()
        before = self.source_digests()
        with patch("audit.handoff._git_state", side_effect=AssertionError("no current repo probing")):
            reuse.search(self.indexers, query="sqlite")
            reuse.projects(self.indexers)
            timeline = reuse.timeline(self.indexers, project="/repo/one")
            reuse.timeline(self.indexers, project="/repo/one", file_path="a.py")
        self.assertEqual(self.source_digests(), before)
        old_failure = next(row for row in timeline["items"] if row["id"] == "failed")
        self.assertIn("Permission denied", json.dumps(old_failure["evidence"]),
                      "unrelated later work must not erase earlier failure evidence")
        self.assertEqual(old_failure["current_verification"], "unknown")

    def test_long_failed_session_preserves_explicit_failure_beyond_evidence_summary_cap(self):
        path = self.add_session("codex", "many-tools")
        with path.open("a") as stream:
            for number in range(12):
                rows = [
                    {"type": "response_item", "timestamp": 1789992020000 + number * 10, "payload": {
                        "type": "function_call", "name": "write", "call_id": "write%d" % number,
                        "arguments": json.dumps({"file_path": "file%d.py" % number, "content": "hello"})}},
                    {"type": "response_item", "timestamp": 1789992020001 + number * 10, "payload": {
                        "type": "function_call_output", "call_id": "write%d" % number,
                        "output": "Error: Permission denied" if number == 11 else "file written"}}]
                stream.write("".join(json.dumps(row) + "\n" for row in rows))
        self.add_session("claude", "unrelated-later-success", file_path="unrelated.py")
        self.start()
        row = next(item for item in reuse.timeline(self.indexers, project="/repo/one")["items"]
                   if item["id"] == "many-tools")
        has_error_evidence = "Permission denied" in json.dumps(row["evidence"])
        observed_errors = (row.get("failures") or {}).get("observed_error_count", 0)
        self.assertTrue(has_error_evidence or observed_errors > 0,
                        "tool failure after evidence cap must remain visible as a concrete error or observed failure count")

    def test_message_excerpt_limit_is_exposed_when_match_is_beyond_read_budget(self):
        self.add_session("codex", "long", text="prefix " + "x" * (reuse.MAX_MESSAGE_CHARS + 100) + " late-needle")
        self.start()
        page = reuse.search(self.indexers, query="late-needle")
        self.assertEqual(len(page["items"]), 1)
        self.assertTrue(page["truncated"], "bounded text reads must not silently masquerade as complete search")
        self.assertTrue(page["partial"])

    def test_query_failure_cannot_issue_or_consume_mixed_source_cursor(self):
        for source in ('codex', 'claude'):
            for number in range(3): self.add_session(source, source + str(number))
        self.start()
        first = reuse.search(self.indexers, query='sqlite', limit=1)
        self.assertIsNotNone(first['next_cursor'])
        original = reuse._candidates
        def fail_one(idx, *args, **kwargs):
            if idx.source == 'claude': raise sqlite3.OperationalError('interrupted')
            return original(idx, *args, **kwargs)
        with patch('history_core.reuse._candidates', side_effect=fail_one):
            partial = reuse.search(self.indexers, query='sqlite', limit=1)
            self.assertTrue(partial['partial'])
            self.assertIsNone(partial['next_cursor'])
            self.assertEqual(partial['pagination_status'], 'restart_after_source_error')
            with self.assertRaisesRegex(ValueError, 'index_revision_changed'):
                reuse.search(self.indexers, query='sqlite', limit=1, cursor=first['next_cursor'])

    def test_candidate_cap_is_explicit_not_an_exhaustive_claim(self):
        for index in range(4):
            self.add_session("codex", "s%d" % index)
        self.start()
        with patch("history_core.reuse.MAX_CANDIDATES", 3):
            page = reuse.search(self.indexers, query="sqlite")
        self.assertEqual(len(page["items"]), 3)
        self.assertTrue(page["truncated"])
        self.assertTrue(page["partial"])


if __name__ == "__main__":
    unittest.main()
