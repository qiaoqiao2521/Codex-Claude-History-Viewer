import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from history_core.evidence import selection_bundle, source_store_id
from history_core.provenance import selected_audit
from history_core.sources import Indexer, parse_claude_session_file


class EvidenceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.indexers = []

    def fixture(self, source="codex", texts=("selected", "unselected secret-free context"), name=None):
        root = self.root / (name or source)
        root.mkdir()
        cache = root.parent / (root.name + "-cache")
        cache.mkdir()
        records = []
        if source == "codex":
            records.append({"type": "session_meta", "payload": {"id": "same-session", "cwd": "/project"}})
        for index, text in enumerate(texts):
            timestamp = "2026-09-22T12:00:%02dZ" % index
            if source == "codex":
                record = {"timestamp": timestamp, "type": "response_item", "payload": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}
            else:
                record = {"timestamp": timestamp, "sessionId": "same-session", "cwd": "/project",
                          "type": "user", "message": {"role": "user", "content": text}}
            records.append(record)
        path = root / "session.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in records))
        kwargs = {"parse_file_fn": parse_claude_session_file} if source == "claude" else {}
        indexer = Indexer(root, cache, source, **kwargs)
        self.addCleanup(indexer.conn.close)
        indexer.maybe_update_index(max_age_seconds=0)
        self.indexers.append(("linux", source, indexer))
        return indexer, path

    def selection(self, indexer, message_index=0, **overrides):
        _, provenance = selected_audit(indexer, "same-session")
        selection = {"system": "linux", "source": indexer.source,
                     "store_id": source_store_id("linux", indexer.source, indexer),
                     "session_id": "same-session", "message_index": message_index,
                     "content_revision": provenance["content_revision"]}
        selection.update(overrides)
        return selection

    def test_two_sources_same_session_only_export_selected_messages(self):
        first, first_path = self.fixture(texts=("Codex chosen", "Codex unselected"))
        second, second_path = self.fixture("claude", ("Claude unselected", "Claude chosen"))
        before = [path.read_bytes() for path in (first_path, second_path)]
        bundle = selection_bundle(self.indexers, [self.selection(first), self.selection(second, 1)])
        self.assertEqual([item["text"] for item in bundle["items"]], ["Codex chosen", "Claude chosen"])
        self.assertNotEqual(bundle["items"][0]["store_id"], bundle["items"][1]["store_id"])
        self.assertNotIn("unselected", json.dumps(bundle))
        self.assertTrue(bundle["context_only"])
        self.assertEqual(bundle["authorization"], "context_only")
        for item in bundle["items"]:
            self.assertEqual(item["binding"], "content_revision")
            self.assertTrue(item["observed_at"])
            self.assertIn(item["content_revision"], bundle["markdown"])
        self.assertEqual(before, [path.read_bytes() for path in (first_path, second_path)])

    def test_requires_display_revision_before_read(self):
        indexer, _ = self.fixture()
        selection = self.selection(indexer, content_revision="unknown")
        with patch("history_core.evidence.selected_audit", side_effect=AssertionError("must not read")):
            with self.assertRaisesRegex(ValueError, "selection_revision_required"):
                selection_bundle(self.indexers, [selection])

    def test_refuses_changed_source_even_before_refresh(self):
        indexer, path = self.fixture()
        selection = self.selection(indexer)
        path.write_bytes(path.read_bytes() + b"{}\n")
        with self.assertRaisesRegex(ValueError, "selection_stale"):
            selection_bundle(self.indexers, [selection])
        indexer.maybe_update_index(max_age_seconds=0)
        with self.assertRaisesRegex(ValueError, "selection_stale"):
            selection_bundle(self.indexers, [selection])

    def test_rejects_count_and_text_budgets_without_silent_truncation(self):
        indexer, _ = self.fixture(texts=("x" * 4001, "y" * 4000))
        with self.assertRaisesRegex(ValueError, "selection_count_limit"):
            selection_bundle(self.indexers, [self.selection(indexer)] * 6)
        with self.assertRaisesRegex(ValueError, "selection_body_limit_exceeded"):
            selection_bundle(self.indexers, [self.selection(indexer), self.selection(indexer, 1)])
        huge, _ = self.fixture(texts=("z" * 8001,), name="huge")
        with patch.object(huge, "get_session", side_effect=AssertionError("must not read full session")), \
                patch.object(huge, "get_session_message", side_effect=AssertionError("unbounded cache read")):
            with self.assertRaisesRegex(ValueError, "selection_body_limit_exceeded"):
                selection_bundle(self.indexers, [self.selection(huge)])

    def test_redacts_json_markdown_and_preserves_source(self):
        secret = ("token=secret-value password: 'hidden password' Authorization: Bearer secret-bearer "
                  "api_key=sk-1234567890abcdefgh\n-----BEGIN RSA PRIVATE KEY-----\nprivate-value\n"
                  "-----END RSA PRIVATE KEY-----")
        indexer, path = self.fixture(texts=(secret,))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        bundle = selection_bundle(self.indexers, [self.selection(indexer)])
        for value in ("secret-value", "hidden password", "secret-bearer", "sk-1234567890abcdefgh", "private-value"):
            self.assertNotIn(value, json.dumps(bundle))
        self.assertTrue(bundle["redacted"])
        self.assertTrue(bundle["items"][0]["redacted"])
        self.assertIn("[REDACTED]", bundle["markdown"])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_redaction_expansion_must_still_fit_exported_body_budget(self):
        text = "x" * 7992 + " token=a"
        self.assertEqual(len(text), 8000)
        indexer, _ = self.fixture(texts=(text,))
        with self.assertRaisesRegex(ValueError, "selection_body_limit_exceeded"):
            selection_bundle(self.indexers, [self.selection(indexer)])

    def test_html_shell_and_markdown_are_fenced_data(self):
        dangerous = "```\n<script>alert(1)</script>\n$(touch /tmp/never-execute)\n```"
        indexer, _ = self.fixture(texts=(dangerous,))
        bundle = selection_bundle(self.indexers, [self.selection(indexer)])
        self.assertEqual(bundle["items"][0]["text"], dangerous)
        self.assertIn("````text", bundle["markdown"])
        self.assertIn(dangerous, bundle["markdown"])

    def test_evidence_selection_is_exact_and_explicitly_summary(self):
        indexer, _ = self.fixture(texts=("selected user request", "do not include this request"))
        audit, _ = selected_audit(indexer, "same-session")
        chosen = audit["evidence"][0]
        bundle = selection_bundle(self.indexers, [self.selection(indexer, evidence_id=chosen["id"])])
        item = bundle["items"][0]
        self.assertEqual(item["representation"], "deterministic_evidence_summary")
        self.assertEqual(item["text"], chosen["summary"])
        self.assertEqual(item["locator"]["raw_ref"], chosen["raw_ref"])
        self.assertNotIn("do not include", json.dumps(bundle))

    def test_bounded_prefix_needs_context_revision_and_rejects_cache_message(self):
        indexer, path = self.fixture(texts=("selected", "z" * 1500))
        # A cutoff after the selected first message proves the export binds the
        # actual captured prefix rather than pretending to hash the whole file.
        cap = len(b"\n".join(path.read_bytes().split(b"\n")[:2])) + 1
        with patch("history_core.provenance.MAX_SOURCE_BYTES", cap):
            audit, provenance = selected_audit(indexer, "same-session")
            self.assertEqual(provenance["content_revision"], "unknown")
            selection = self.selection(indexer, evidence_id=audit["evidence"][0]["id"],
                                       context_revision=provenance["context_revision"])
            bundle = selection_bundle(self.indexers, [selection])
            self.assertEqual(bundle["items"][0]["binding"], "context_revision")
            self.assertTrue(bundle["items"][0]["truncated_source"])
            selection.pop("evidence_id")
            with self.assertRaisesRegex(ValueError, "selection_message_outside_verified_scope"):
                selection_bundle(self.indexers, [selection])

    def test_native_source_explicitly_unsupported_without_loading_database(self):
        native = SimpleNamespace(source="opencode", db_path=self.root / "source.db",
                                 get_session=Mock(side_effect=AssertionError("unbounded read")))
        selection = {"system": "linux", "source": "opencode", "session_id": "same-session",
                     "message_index": 0, "content_revision": "sha256:" + "0" * 64}
        with self.assertRaisesRegex(ValueError, "selection_revision_unsupported"):
            selection_bundle([("linux", "opencode", native)], [selection])
        native.get_session.assert_not_called()

    def test_missing_source_or_selection_does_not_return_successful_partial_bundle(self):
        indexer, path = self.fixture()
        selection = self.selection(indexer)
        with self.assertRaisesRegex(ValueError, "selection_source_unavailable"):
            selection_bundle(self.indexers, [dict(selection, store_id="incorrect-store")])
        with self.assertRaisesRegex(ValueError, "selection_evidence_unavailable"):
            selection_bundle(self.indexers, [dict(selection, evidence_id="missing")])
        path.unlink()
        with self.assertRaisesRegex(ValueError, "selection_source_unavailable"):
            selection_bundle(self.indexers, [selection])

    def test_same_source_store_requires_identity_when_ambiguous(self):
        first, _ = self.fixture()
        second, _ = self.fixture(name="other-codex", texts=("other-store",))
        selection = self.selection(first)
        selection.pop("store_id")
        with self.assertRaisesRegex(ValueError, "selection_source_ambiguous"):
            selection_bundle(self.indexers, [selection])
        self.assertEqual(selection_bundle(self.indexers, [self.selection(second)])["items"][0]["text"], "other-store")

    def test_index_refresh_race_and_legacy_unsigned_cache_are_rejected(self):
        indexer, _ = self.fixture()
        selection = self.selection(indexer)
        with patch("history_core.evidence._message_signature", return_value="changed"):
            with self.assertRaisesRegex(ValueError, "selection_stale"):
                selection_bundle(self.indexers, [selection])
        indexer.conn.execute("UPDATE sessions SET file_signature=NULL")
        with self.assertRaisesRegex(ValueError, "selection_message_binding_unsupported"):
            selection_bundle(self.indexers, [selection])


if __name__ == "__main__":
    unittest.main()
