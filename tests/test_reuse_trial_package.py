"""The trial overlay must be deterministic, synthetic, and honestly identified."""
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_reuse_trial as trial


class TrialPackageTests(unittest.TestCase):
    def source_files(self):
        return {name: (trial.ROOT / name).read_bytes() for name in trial.REQUIRED}

    def test_frozen_package_overlay_hashes_and_tool_results_are_consistent(self):
        commit = "a" * 40
        source = self.source_files()
        original = dict(source)
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "trial.zip"
            with patch.object(trial, "_source_files", side_effect=lambda revision: (commit, dict(source))), redirect_stdout(io.StringIO()):
                first = trial.build(output, commit)
                second = trial.build(Path(temp) / "repeat.zip", commit)
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(source, original)
            manifest = json.loads(output.with_suffix(".manifest.json").read_text())
            self.assertEqual(manifest["u1_status"], "pending")
            self.assertEqual(manifest["material_preflight"], "not_run")
            self.assertEqual(manifest["source_commit"], commit)
            self.assertEqual(manifest["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertIn(manifest["sha256"], output.with_suffix(".sha256").read_text())
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertEqual(len([name for name in names if name.endswith(".jsonl")]), 12)
                self.assertNotIn("demo/manifest.json", names)
                self.assertFalse(any("observer.md" in name or name.startswith(("work/", "data/")) for name in names))
                info = json.loads(archive.read("BUILD_INFO.json"))
                self.assertEqual(info["source_commit"], commit)
                for name, digest in info["files_sha256"].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest, name)
                corpus = json.loads(archive.read("demo/u1-manifest.json"))
                self.assertEqual(corpus["counts"], {"codex": 6, "claude": 6})
                for name, digest in corpus["files_sha256"].items():
                    self.assertEqual(hashlib.sha256(archive.read("demo/" + name)).hexdigest(), digest)
                rows = [json.loads(line) for line in archive.read("demo/claude/projects/trial-file-fixed.jsonl").splitlines()]
                results = [item for row in rows for item in row["message"]["content"]
                           if isinstance(row["message"]["content"], list) and item.get("type") == "tool_result"]
                self.assertEqual(len(results), 2)
                self.assertTrue(all(item["is_error"] is False for item in results))
                self.assertIn(commit, archive.read("TRIAL_TASKS.md").decode())

    def test_no_overwrite_private_data_or_unfrozen_packager(self):
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            output = Path(temp) / "trial.zip"
            output.write_bytes(b"previous-package")
            with self.assertRaisesRegex(ValueError, "already_exists"):
                trial.build(output)
            self.assertEqual(output.read_bytes(), b"previous-package")
            output.unlink()
            source = self.source_files()
            source["history_core/private.jsonl"] = b"private log"
            with patch.object(trial, "_source_files", return_value=("b" * 40, source)):
                with self.assertRaisesRegex(ValueError, "forbidden_source_data"):
                    trial.build(output)
            self.assertFalse(output.exists())
            source = self.source_files()
            source["scripts/build_reuse_trial.py"] += b"\n# not the candidate\n"
            with patch.object(trial, "_source_files", return_value=("b" * 40, source)):
                with self.assertRaisesRegex(ValueError, "not_at_candidate_revision"):
                    trial.build(output)
            demo = Path(temp) / "demo"
            corpus = trial.prepare_demo(demo)
            self.assertEqual(corpus["session_count"], 12)
            with self.assertRaisesRegex(ValueError, "demo_output_must_be_empty"):
                trial.prepare_demo(demo)


if __name__ == "__main__":
    unittest.main()
