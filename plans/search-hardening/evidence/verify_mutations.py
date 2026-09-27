#!/usr/bin/env python3
"""Repeat recorded mutations in a fresh private copy; never edit product files.
Usage: python3 verify_mutations.py REPO NEW_OUTPUT_DIRECTORY
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
copy = out / 'copy'
copy.mkdir()
for folder in ('history_core', 'audit', 'tests'):
    shutil.copytree(repo / folder, copy / folder,
                    ignore=shutil.ignore_patterns('__pycache__', '*.sqlite*'))
shutil.copyfile(repo / 'app.py', copy / 'app.py')
paths = ['history_core/reuse.py', 'history_core/sources.py', 'tests/test_large_session_search.py',
         'tests/test_large_search_snippets.py', 'tests/test_reuse_contract.py']
hashes = {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in paths}
(out / 'source-hashes.json').write_text(json.dumps(hashes, indent=2))
checks = ['test_large_session_search.LargeSessionSearchTests.test_raw_fallback_is_searchable_but_harness_context_stays_excluded',
          'test_large_search_snippets.LargeSearchSnippetTests.test_phrase_is_preferred_and_response_has_at_most_three_bounded_excerpts',
          'test_reuse_contract.ReuseContractTests.test_query_failure_cannot_issue_or_consume_mixed_source_cursor']
results = []

def run(label, modules):
    command = [sys.executable, '-m', 'unittest', '-v', *modules]
    process = subprocess.run(command, cwd=copy / 'tests', env={**__import__('os').environ, 'PYTHONPATH': str(copy)},
                             capture_output=True, text=True, timeout=180)
    (out / (label + '.log')).write_text(process.stdout + process.stderr)
    results.append({'label': label, 'command': command, 'exit_code': process.returncode})
    print(label, process.returncode, flush=True)
    return process.returncode

assert run('control-before', checks) == 0
mutations = [
    ('M1', 'history_core/sources.py', 'search_message.session_id={alias}.id', "search_message.session_id=''", checks),
    ('M2', 'history_core/reuse.py', 'text = "COALESCE(m.text,\'\')"', 'text = "substr(COALESCE(m.text,\'\'),1,8192)"', [checks[1]]),
    ('M3', 'history_core/reuse.py', "            errors.append({'system':system,'source':src,'error':error_code(exc)})\n    items.sort", '            pass\n    items.sort', [checks[2]]),
]
for name, relative, before, after, modules in mutations:
    path = copy / relative
    original = path.read_text()
    region = original[original.index('def search('):original.index('\ndef ', original.index('def search(') + 1)] if name == 'M3' else original
    assert region.count(before) == 1, (name, 'ambiguous anchor')
    try:
        changed = original.replace(region, region.replace(before, after), 1)
        path.write_text(changed)
        import difflib
        (out / (name + '.patch')).write_text(''.join(difflib.unified_diff(original.splitlines(True), changed.splitlines(True), fromfile=relative, tofile=relative)))
        assert run(name, modules) != 0, (name, 'unexpected green')
    finally:
        path.write_text(original)
    assert run(name + '-restored', checks) == 0
assert hashes == {path: hashlib.sha256((repo / path).read_bytes()).hexdigest() for path in paths}
(out / 'results.json').write_text(json.dumps(results, indent=2))
print('Product scope unchanged; inspect raw failure assertions before classifying detected.')
