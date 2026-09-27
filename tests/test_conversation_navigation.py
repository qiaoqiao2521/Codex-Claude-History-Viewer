"""Synthetic, independent reader-offset and bounded navigation contracts."""
import hashlib
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from history_core import conversation_navigation as navigation, reuse
from history_core.evidence import source_store_id
from history_core.sources import Indexer


class ConversationNavigationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.indexers = []
        self.idx = self.make_indexer("codex")

    def make_indexer(self, source, name=None):
        root = self.root / (name or source)
        root.mkdir()
        cache = self.root / ((name or source) + "-cache")
        cache.mkdir()
        indexer = Indexer(root, cache, source)
        self.addCleanup(indexer.conn.close)
        self.indexers.append(("linux", source, indexer))
        return indexer

    def seed(self, messages, sid="session", indexer=None):
        indexer = indexer or self.idx
        path = indexer.sessions_dir / (sid + ".jsonl")
        path.write_text("synthetic source; navigation must use the existing index\n")
        with indexer.conn:
            indexer.conn.execute(
                "INSERT INTO sessions(id,file_path,start_ts_ms,end_ts_ms,title,cwd,message_count) "
                "VALUES(?,?,1,2,'Synthetic','/synthetic',?)", (sid, str(path), len(messages)))
            indexer.conn.executemany(
                "INSERT INTO messages(session_id,ts_ms,role,kind,text) VALUES(?,?,?,?,?)",
                [(sid, ts, role, kind, text) for ts, role, kind, text in messages])
        return path

    def read(self, sid="session", indexer=None, **kwargs):
        indexer = indexer or self.idx
        before = indexer.conn.total_changes
        revision = reuse.index_revision(indexer)
        result = navigation.key_messages(
            self.indexers, system="linux", source=indexer.source, session_id=sid,
            source_revision=revision, **kwargs)
        self.assertEqual(indexer.conn.total_changes, before)
        self.assertEqual(reuse.index_revision(indexer), revision)
        self.assertEqual(result["source_revision"], revision)
        return result

    def test_complete_identity_disambiguates_same_ids_sources_and_stores(self):
        claude = self.make_indexer("claude")
        second = self.make_indexer("codex", "codex-second")
        for number, indexer in enumerate((self.idx, claude, second)):
            self.seed([(1, "user", "message", f"request from store {number}")], indexer=indexer)
        with self.assertRaisesRegex(ValueError, "selection_source_ambiguous"):
            self.read()
        for number, indexer in enumerate((self.idx, claude, second)):
            store = source_store_id("linux", indexer.source, indexer)
            result = self.read(indexer=indexer, store_id=store)
            self.assertEqual(result["store_id"], store)
            self.assertEqual(result["source"], indexer.source)
            self.assertEqual(result["items"][0]["text"], f"request from store {number}")
        with self.assertRaisesRegex(ValueError, "selection_source_unavailable"):
            self.read(store_id="not-a-selected-store")

    def test_revision_required_stale_rejected_and_missing_session_distinct(self):
        self.seed([(1, "user", "message", "find a problem")])
        args = dict(system="linux", source="codex", session_id="session")
        with self.assertRaisesRegex(ValueError, "source_revision_required"):
            navigation.key_messages(self.indexers, **args)
        with self.assertRaisesRegex(ValueError, "index_revision_changed"):
            navigation.key_messages(self.indexers, **args, source_revision="0" * 64)
        with self.assertRaisesRegex(ValueError, "session_not_found"):
            self.read("missing")

    def test_revision_changes_during_query_rejects_entire_response(self):
        self.seed([(1, "user", "message", "request")])
        revision = reuse.index_revision(self.idx)
        with patch.object(navigation, "index_revision", side_effect=[revision, "changed"]):
            with self.assertRaisesRegex(ValueError, "index_revision_changed"):
                navigation.key_messages(self.indexers, system="linux", source="codex",
                                        session_id="session", source_revision=revision)

    def test_context_thinking_and_tools_keep_absolute_reader_offsets(self):
        self.seed([(30, "assistant", "message", "最终选择 Linux"),
                   (None, "user", "context", "untrusted harness request"),
                   (10, "assistant", "reasoning_summary", "pytest failure thoughts"),
                   (20, "user", "message", "帮我找回上下文"),
                   (20, "assistant", "tool_use", "pytest error: pretend tool arguments"),
                   (25, "tool", "tool_result", "Error: Permission denied"),
                   (40, "assistant", "message", "pytest has not run; waiting for access")])
        result = self.read()
        self.assertEqual([item["message_index"] for item in result["items"]], [2, 4, 5, 6])
        self.assertEqual(result["total_messages"], 7)
        self.assertEqual(result["indexed_messages"], 7)
        self.assertFalse(result["partial"])
        for item in result["items"]:
            original = self.idx.get_session_message("session", item["message_index"])
            self.assertEqual(item["text"], original["text"])
            self.assertEqual(item["role"], original["role"])
        self.assertEqual(result["items"][1]["kinds"], ["failure"])
        self.assertEqual(result["items"][-1]["kinds"], ["verification", "last_response"])

    def test_failure_record_survives_success_reply_and_multilabel_is_one_node(self):
        self.seed([(0, "user", "message", "修复测试"),
                   (1, "tool", "tool_result", "Error: old failure; tests failed"),
                   (2, "assistant", "message", "决定采用方案二，pytest tests passed")])
        result = self.read()
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["items"][1]["kinds"], ["failure", "verification"])
        self.assertEqual(result["items"][2]["kinds"], ["decision", "verification", "last_response"])
        self.assertEqual(result["interpretation"], "wording_hints_only")
        self.assertNotIn("completed", str(result))

    def test_full_text_after_two_megabytes_and_after_message_2000_is_located(self):
        body = "🧪" * 2_100_000 + " 决定采用 Linux，pytest 在这里 " + "尾" * 400
        messages = [(0, "user", "message", "最初请求")]
        messages += [(number + 1, "assistant", "message", "ordinary filler") for number in range(2005)]
        messages += [(2006, "assistant", "message", body), (2007, "assistant", "message", "last ordinary reply")]
        self.seed(messages)
        result = self.read()
        self.assertEqual([item["message_index"] for item in result["items"]], [0, 2006, 2007])
        middle = result["items"][1]
        self.assertIn("决定采用 Linux", middle["text"])
        self.assertIn("pytest", middle["text"])
        self.assertLessEqual(len(middle["text"]), navigation.MAX_EXCERPT_CHARS)
        self.assertTrue(middle["truncated"])
        self.assertFalse(result["partial"], "excerpt clipping is not incomplete index search")
        self.assertEqual(result["indexed_messages"], 2008)

    def test_marker_cap_is_explicit_and_first_last_anchors_never_disappear(self):
        messages = [(0, "user", "message", "original request")]
        messages += [(number + 1, "tool", "tool_result", "Error: numbered failure " + str(number))
                     for number in range(navigation.MAX_MARKERS + 8)]
        messages.append((1000, "assistant", "message", "waiting for your choice"))
        self.seed(messages)
        result = self.read()
        self.assertTrue(result["partial"])
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["items"]), navigation.MAX_MARKERS + 2)
        self.assertEqual(result["items"][0]["message_index"], 0)
        self.assertEqual(result["items"][-1]["message_index"], len(messages) - 1)
        self.assertEqual(result["items"][-1]["kinds"], ["last_response"])
        self.assertEqual(result["total_messages"], len(messages))
        self.assertEqual(len({item["message_index"] for item in result["items"]}), len(result["items"]))

    def test_negated_errors_do_not_claim_failure_and_test_mentions_are_not_results(self):
        self.seed([(0, "user", "message", "investigate"),
                   (1, "assistant", "message", "未发现错误，没有失败，本轮没有报错。No errors detected; no failures."),
                   (2, "assistant", "message", "尚未运行 pytest，这不是测试通过的证据。"),
                   (3, "assistant", "message", "最后回复仍需人工验收")])
        result = self.read()
        self.assertEqual([item["message_index"] for item in result["items"]], [0, 2, 3])
        self.assertEqual(result["items"][1]["kinds"], ["verification"])
        self.assertFalse(any("failure" in item["kinds"] for item in result["items"]))
        self.assertEqual(result["interpretation"], "wording_hints_only")
        self.assertNotIn("verified", result)

    def test_first_user_after_marker_cap_and_last_reply_are_both_retained(self):
        messages = [(number, "tool", "tool_result", "Error: earlier failure")
                    for number in range(navigation.MAX_MARKERS + 5)]
        messages += [(1000, "user", "message", "first actual request after imported tool history"),
                     (1001, "assistant", "message", "last reply")]
        self.seed(messages)
        result = self.read()
        self.assertEqual(len(result["items"]), navigation.MAX_MARKERS + 2)
        self.assertEqual(result["items"][-2]["message_index"], navigation.MAX_MARKERS + 5)
        self.assertEqual(result["items"][-2]["kinds"], ["request"])
        self.assertEqual(result["items"][-1]["kinds"], ["last_response"])
        self.assertTrue(result["partial"])

    def test_native_without_shared_index_is_explicitly_unsupported(self):
        native = SimpleNamespace(source="hermes", db_path=self.root / "hermes.sqlite")
        with patch.object(navigation, "index_revision", return_value="revision"):
            result = navigation.key_messages([("linux", "hermes", native)], system="linux",
                                             source="hermes", session_id="native-session",
                                             source_revision="revision")
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["reason"], "source_message_index_unsupported")
        self.assertEqual(result["items"], [])
        self.assertIsNone(result["total_messages"])
        self.assertIsNone(result["indexed_messages"])

    def test_incomplete_decoding_is_disclosed(self):
        self.seed([(0, "user", "message", "request")])
        self.idx._coverage = {"session": {"content_status": "encrypted"}}
        result = self.read()
        self.assertTrue(result["partial"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["content_status"], "encrypted")

    def test_existing_cache_query_is_read_only_no_reparse_or_audit(self):
        path = self.seed([(0, "user", "message", "request"),
                          (1, "assistant", "message", "决定使用本地缓存")])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.idx.conn.execute("PRAGMA query_only=ON")
        with patch.object(self.idx, "maybe_update_index", side_effect=AssertionError("implicit refresh")), \
             patch("history_core.provenance.selected_snapshot", side_effect=AssertionError("source extraction")):
            result = self.read()
        self.assertEqual(result["status"], "available")
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_sql_budget_failure_propagates_and_connection_recovers(self):
        self.seed([(number, "assistant", "message", "ordinary filler") for number in range(2005)]
                  + [(2005, "assistant", "message", "pytest mentioned here")])
        calls = 0

        def clock():
            nonlocal calls
            calls += 1
            return calls * 3

        with patch("history_core.reuse.time.monotonic", side_effect=clock):
            with self.assertRaisesRegex(sqlite3.OperationalError, "interrupted"):
                self.read()
        self.assertGreater(calls, 1)
        result = self.read()
        self.assertEqual(result["items"][0]["message_index"], 2005)

    def test_empty_session_is_available_and_distinct_from_unsupported(self):
        self.seed([])
        result = self.read()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["total_messages"], 0)
        self.assertEqual(result["items"], [])
        self.assertFalse(result["partial"])


if __name__ == "__main__":
    unittest.main()
