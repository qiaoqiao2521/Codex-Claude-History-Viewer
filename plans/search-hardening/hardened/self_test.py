#!/usr/bin/env python3
"""Run the strict oracle and require each deliberate probe corruption to fail."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SCRIPTS = ('self_test.py', 'build_fixture.py', 'manifest_spec.py', 'probe.py')


def file_bindings(paths):
    """Bind the exact bytes and absolute paths actually used by this run."""
    return {p.name: {'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--run-root', required=True, type=Path, help='new scratch root; never inside the repository')
    parser.add_argument('--logs', required=True, type=Path, help='new small evidence directory')
    parser.add_argument('--frozen-run', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    run = args.run_root.resolve()
    repo = args.repo.resolve()
    logs = args.logs.resolve()
    if run == repo or repo in run.parents:
        parser.error('--run-root must be outside the repository')
    if not args.frozen_run:
        run.mkdir(parents=True, exist_ok=False)
        logs.mkdir(parents=True, exist_ok=False)
        frozen = run / 'verifier'
        frozen.mkdir()
        origin_before = file_bindings([HERE / name for name in SCRIPTS])
        for name in SCRIPTS:
            payload = (HERE / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != origin_before[name]['sha256']:
                raise RuntimeError('verification script changed while freezing: ' + name)
            target = frozen / name
            target.write_bytes(payload)
            target.chmod(0o444)
        binding = {'origin_before': origin_before,
                   'frozen_before': file_bindings([frozen / name for name in SCRIPTS])}
        (run / 'verifier-binding.json').write_text(json.dumps(binding, indent=2) + '\n')
        command = [sys.executable, str(frozen / 'self_test.py'), '--repo', str(repo),
                   '--run-root', str(run), '--logs', str(logs), '--frozen-run']
        # Execute the driver itself from the frozen copy, not just its children.
        raise SystemExit(subprocess.run(command, cwd=repo).returncode)
    if HERE != run / 'verifier':
        raise RuntimeError('--frozen-run must execute the frozen driver')
    binding = json.loads((run / 'verifier-binding.json').read_text())
    frozen_before = file_bindings([HERE / name for name in SCRIPTS])
    if frozen_before != binding['frozen_before']:
        raise RuntimeError('frozen scripts differ before execution')
    origin_paths = [Path(binding['origin_before'][name]['path']) for name in SCRIPTS]
    records = []
    runtime = [repo / 'app.py'] + sorted((repo / 'history_core').rglob('*.py')) + sorted((repo / 'audit').rglob('*.py')) + sorted((repo / 'static').glob('*'))
    runtime = [p for p in runtime if p.is_file()]
    hashes = lambda: {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest() for p in runtime}
    before = hashes()
    def execute(name, command, expected_exit=0, diagnostic=None):
        result = subprocess.run(command, cwd=repo, text=True, capture_output=True, timeout=90)
        output = result.stdout + result.stderr
        log = logs / (name + '.txt')
        log.write_text(output, encoding='utf-8')
        ok = result.returncode == expected_exit and (diagnostic is None or diagnostic in output)
        record = {'name': name, 'command': command, 'exit_code': result.returncode, 'expected_exit': expected_exit,
                  'required_diagnostic': diagnostic, 'passed': ok, 'log': log.name,
                  'sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
        records.append(record)
        print(('PASS' if ok else 'FAIL') + ' ' + name, 'exit=' + str(result.returncode))
        if not ok:
            raise RuntimeError(name + ' did not meet its independent expectation')
    root = run / 'fixture'
    cache = run / 'cache'
    fixture_paths = [root / 'manifest.json', root / 'source-hashes.json']
    fixture_before = None
    base = [sys.executable, str(HERE / 'probe.py'), '--repo', str(repo), '--root', str(root), '--cache', str(cache)]
    try:
        execute('build', [sys.executable, str(HERE / 'build_fixture.py'), '--root', str(root)])
        fixture_before = file_bindings(fixture_paths)
        # Retain the two small generated documents, not the large fixture/DB.
        for path in fixture_paths:
            (logs / path.name).write_bytes(path.read_bytes())
        execute('setup', base + ['--setup'])
        execute('control-before', base, diagnostic='"passed": 19, "failed": []')
        failures = {
            'source': '.source: got=', 'store': '.store_id: got=', 'body': '.snippets: got=',
            'status': '.snippet_status: got=', 'partial': 'partial: got=', 'errors': 'errors: got=',
            'missing_item': 'item count: got=', 'underscore_unescaped': 'FAIL literal_underscore AssertionError item count: got=',
        }
        for corruption, diagnostic in failures.items():
            execute('negative-' + corruption, base + ['--corrupt', corruption], expected_exit=1, diagnostic=diagnostic)
        execute('control-after', base, diagnostic='"passed": 19, "failed": []')
    finally:
        after = hashes()
        origin_after = file_bindings(origin_paths)
        frozen_after = file_bindings([HERE / name for name in SCRIPTS])
        fixture_after = file_bindings(fixture_paths) if all(p.is_file() for p in fixture_paths) else None
        stable = {'runtime_source_unchanged': before == after,
                  'verification_origin_unchanged': binding['origin_before'] == origin_after,
                  'verification_frozen_unchanged': frozen_before == frozen_after,
                  'fixture_documents_unchanged': fixture_before is not None and fixture_before == fixture_after}
        summary = {'observed_at': datetime.now(timezone.utc).isoformat(), 'repo': str(repo), 'run_root': str(run),
                   **stable, 'runtime_sha256_before': before, 'runtime_sha256_after': after,
                   'verification_origin_before': binding['origin_before'], 'verification_origin_after': origin_after,
                   'verification_frozen_before': frozen_before, 'verification_frozen_after': frozen_after,
                   'fixture_documents_before': fixture_before, 'fixture_documents_after': fixture_after,
                   'archived_fixture_documents': file_bindings([logs / p.name for p in fixture_paths]) if fixture_before else None,
                   'driver_path': str(Path(__file__).resolve()), 'runs': records}
        (logs / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not all(stable.values()):
        raise RuntimeError('product, verifier or fixture evidence changed during execution; inspect hashes')

if __name__ == '__main__':
    main()
