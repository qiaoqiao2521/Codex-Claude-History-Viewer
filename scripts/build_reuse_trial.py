#!/usr/bin/env python3
"""Build a commit-bound Linux U1 trial with only the 12 synthetic histories."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ALLOWLIST = ("app.py", "VERSION", "README.md", "LICENSE", "audit", "history_core",
                    "static", "scripts", "tests/fixtures/reuse_queries.json",
                    "plans/history-reuse-product/trial/tasks.md")
REQUIRED = ("app.py", "VERSION", "scripts/reuse_fixture.py", "scripts/build_reuse_trial.py",
            "tests/fixtures/reuse_queries.json", "plans/history-reuse-product/trial/tasks.md")
EPOCH = (2020, 1, 1, 0, 0, 0)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _source_files(revision):
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", str(revision) + "^{commit}"],
        cwd=ROOT, text=True).strip()
    raw = subprocess.check_output(
        ["git", "archive", "--format=zip", commit, "--", *SOURCE_ALLOWLIST], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    return commit, files


def _tool_sessions():
    project = "/synthetic/beta/repo"
    timestamp = "2026-09-20T10:00:00.000Z"
    def codex(payload):
        return {"timestamp": timestamp, "type": "response_item", "payload": payload}
    rows = [
        {"timestamp": timestamp, "type": "session_meta", "payload": {
            "id": "trial-file-failed", "cwd": project, "timestamp": timestamp}},
        codex({"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "修正 src/a.py 并核对测试。"}]}),
        codex({"type": "function_call", "name": "edit", "call_id": "trial-edit-failed",
               "arguments": json.dumps({"file_path": project + "/src/a.py", "old_string": "old", "new_string": "new"})}),
        codex({"type": "function_call_output", "call_id": "trial-edit-failed",
               "output": "Exit code: 1\nPermission denied; no file written."}),
        codex({"type": "function_call", "name": "shell", "call_id": "trial-test-failed",
               "arguments": json.dumps({"command": "python -m pytest tests/test_a.py", "workdir": project})}),
        codex({"type": "function_call_output", "call_id": "trial-test-failed",
               "output": "Exit code: 1\n1 failed; expected new behavior."}),
    ]
    encode = lambda records: ("\n".join(json.dumps(row, ensure_ascii=False) for row in records) + "\n").encode()
    failed = encode(rows)
    timestamp = "2026-09-21T10:00:00.000Z"
    def claude(role, content):
        return {"sessionId": "trial-file-fixed", "timestamp": timestamp, "cwd": project,
                "type": "message", "message": {"role": role, "content": content}}
    rows = [
        claude("user", "再次修改 src/a.py，检查文件行为；不处理 worker 退出问题。"),
        claude("assistant", [{"type": "tool_use", "id": "trial-edit-ok", "name": "Edit",
                              "input": {"file_path": project + "/src/a.py", "old_string": "old", "new_string": "new"}}]),
        claude("user", [{"type": "tool_result", "tool_use_id": "trial-edit-ok", "is_error": False,
                         "content": "The file has been edited."}]),
        claude("assistant", [{"type": "tool_use", "id": "trial-test-ok", "name": "Bash",
                              "input": {"command": "python -m pytest tests/test_a.py"}}]),
        claude("user", [{"type": "tool_result", "tool_use_id": "trial-test-ok", "is_error": False,
                         "content": "Exit code: 0\n2 passed."}]),
    ]
    return {"codex/sessions/trial-file-failed.jsonl": failed,
            "claude/projects/trial-file-fixed.jsonl": encode(rows)}


def prepare_demo(target_root, *, source_files=None):
    """Write a new 12-session demo for material preflight without a commit.

    Packaging passes frozen source bytes; ordinary callers use the current
    generator/questions. The E0 corpus itself is never modified or reused.
    """
    target_root = Path(target_root)
    if target_root.exists() and (not target_root.is_dir() or any(target_root.iterdir())):
        raise ValueError("trial_demo_output_must_be_empty")
    questions_path = "tests/fixtures/reuse_queries.json"
    files = source_files if source_files is not None else {
        name: (ROOT / name).read_bytes() for name in ("scripts/reuse_fixture.py", questions_path)}
    with tempfile.TemporaryDirectory(prefix="hv-u1-build-") as temp:
        temp_root = Path(temp)
        # Execute the frozen generator, not an uncommitted working-tree import.
        for name in ("scripts/reuse_fixture.py", questions_path):
            path = temp_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(files[name])
        corpus = temp_root / "corpus"
        subprocess.run([sys.executable, str(temp_root / "scripts/reuse_fixture.py"), "--out", str(corpus)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        base_manifest = json.loads((corpus / "manifest.json").read_text())
        if base_manifest.get("counts") != {"codex": 5, "claude": 5} or base_manifest.get("session_count") != 10:
            raise ValueError("trial_requires_frozen_10_session_corpus")
        synthetic = {str(path.relative_to(corpus)): path.read_bytes() for path in sorted(corpus.rglob("*.jsonl"))}
    synthetic.update(_tool_sessions())
    if len(synthetic) != 12:
        raise ValueError("trial_requires_12_unique_sessions")
    corpus_manifest = {
        "schema_version": "history.reuse-u1-corpus.v1", "scope": "U1 synthetic corpus; E0 10 sessions plus 2 tool sessions",
        "counts": {"codex": 6, "claude": 6}, "session_count": 12,
        "questions_sha256": _sha(files[questions_path]), "e0_dataset_sha256": base_manifest["dataset_sha256"],
        "files_sha256": {name: _sha(raw) for name, raw in sorted(synthetic.items())}}
    target_root.mkdir(parents=True, exist_ok=True)
    for name, raw in synthetic.items():
        path = target_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    (target_root / "u1-manifest.json").write_bytes(_json(corpus_manifest))
    return corpus_manifest


def build(output, revision="HEAD"):
    output = Path(output)
    if output.suffix.lower() != ".zip":
        raise ValueError("trial_output_must_be_zip")
    checksum = output.with_suffix(".sha256")
    manifest_path = output.with_suffix(".manifest.json")
    if any(path.exists() for path in (output, checksum, manifest_path)):
        raise ValueError("trial_output_already_exists: choose a new path")
    commit, files = _source_files(revision)
    missing = [name for name in REQUIRED if name not in files]
    if missing:
        raise ValueError("candidate_missing_required_files: " + ", ".join(missing))
    if files["scripts/build_reuse_trial.py"] != Path(__file__).read_bytes():
        raise ValueError("trial_packager_not_at_candidate_revision: run the script from that candidate")
    # Original demo files are deliberately absent from the allowlist. Prevent a
    # tracked cache/log under a runtime directory from becoming a trial input.
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or any(
                part in ("__pycache__", "node_modules", "work", "data", ".git") for part in path.parts):
            raise ValueError("trial_forbidden_source_path: " + name)
        if name.endswith((".jsonl", ".sqlite", ".sqlite-wal", ".sqlite-shm", ".db", ".pyc")):
            raise ValueError("trial_forbidden_source_data: " + name)
    version = files["VERSION"].decode().strip()
    with tempfile.TemporaryDirectory(prefix="hv-u1-overlay-") as temp:
        demo = Path(temp) / "demo"
        corpus_manifest = prepare_demo(demo, source_files=files)
        for path in sorted(demo.rglob("*")):
            if path.is_file():
                files["demo/" + str(path.relative_to(demo))] = path.read_bytes()
    task_path = "plans/history-reuse-product/trial/tasks.md"
    tasks = files.pop(task_path).decode()
    tasks = tasks.replace("候选源码 commit：**待组织者填入**；候选包 SHA-256：**待组织者填入**。",
                          "候选源码 commit：`" + commit + "`；应用 VERSION：`" + version +
                          "`；候选包 SHA-256：见同名 `.sha256` 与 `.manifest.json`。")
    files["TRIAL_TASKS.md"] = tasks.encode()
    trial = {"schema_version": "history.reuse-trial.v1", "package_type": "synthetic_trial_candidate",
             "source_commit": commit, "version": version, "platform": "Linux / Python 3.11+",
             "u1_status": "pending", "material_preflight": "not_run",
             "participant_tasks": "TRIAL_TASKS.md", "source_archive_allowlist": list(SOURCE_ALLOWLIST),
             "packager_sha256": _sha(files["scripts/build_reuse_trial.py"]),
             "corpus_manifest": "demo/u1-manifest.json", "corpus_manifest_sha256": _sha(files["demo/u1-manifest.json"]),
             "counts": corpus_manifest["counts"], "session_count": 12,
             "overlay": ["demo/ (all synthetic)", "TRIAL_TASKS.md", "TRIAL_MANIFEST.json", "BUILD_INFO.json"],
             "note": "This customised trial is not an unchanged release. Packaging does not satisfy independent U1 acceptance."}
    files["TRIAL_MANIFEST.json"] = _json(trial)
    files["BUILD_INFO.json"] = _json({"source_commit": commit, "version": version, "support": "Linux / Python 3.11+",
                                      "package_type": "synthetic_trial_candidate",
                                      "files_sha256": {name: _sha(raw) for name, raw in sorted(files.items())}})
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw, compresslevel=9)
    digest = _sha(output.read_bytes())
    checksum.write_text(digest + "  " + output.name + "\n")
    manifest = dict(trial, artifact=output.name, sha256=digest,
                    archive_files_sha256={name: _sha(raw) for name, raw in sorted(files.items())})
    manifest_path.write_bytes(_json(manifest))
    result = {"artifact": str(output), "sha256_file": str(checksum), "manifest": str(manifest_path),
              "sha256": digest, "source_commit": commit, "version": version, "session_count": 12,
              "u1_status": "pending", "material_preflight": "not_run"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.output, args.revision)
