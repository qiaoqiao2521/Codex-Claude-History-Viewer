#!/usr/bin/env python3
"""Fixture probe: run reuse.search against the synthetic fixture and compare
with the hand-authored manifest. Usage: probe.py <repo_root> <cache_dir> [probe_case ...]
Prints PASS/FAIL per case + source-file integrity. Exit 0 iff all pass."""
import hashlib, json, shutil, sys
from pathlib import Path

repo = Path(sys.argv[1]); cache = Path(sys.argv[2]); only = sys.argv[3:] or None
sys.path.insert(0, str(repo))
from history_core.sources import Indexer, parse_codex_session_file, parse_claude_session_file
from history_core import reuse

FIX = Path('/tmp/cchv-hardening/home')
manifest = json.loads(Path('/tmp/cchv-hardening/manifest.json').read_text())

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
sources_before = {str(p): sha(p) for p in sorted(FIX.rglob('*.jsonl'))}

def build():
    idxs = []
    for sub in ('codex', 'claude'):
        (cache / sub).mkdir(parents=True, exist_ok=True)
    codex_cache = cache / 'codex'; claude_cache = cache / 'claude'
    ic = Indexer(FIX / '.codex/sessions/2026/09/06', codex_cache, 'codex',
                 parse_file_fn=parse_codex_session_file, parser_version=5, recall_db_path=None)
    ic.scan_sessions()
    idxs.append(('linux', 'codex', ic))
    icl = Indexer(FIX / '.claude/projects/proj-claude', claude_cache, 'claude',
                  parse_file_fn=parse_claude_session_file, parser_version=5, recall_db_path=None)
    icl.scan_sessions()
    idxs.append(('linux', 'claude', icl))
    return idxs

failures = []
for case in manifest['cases']:
    q = case['q']
    if only and q not in only: continue
    cache_dir = cache / ('probe-' + hashlib.sha1(q.encode()).hexdigest()[:10])
    shutil.rmtree(cache_dir, ignore_errors=True)
    idxs = build()
    try:
        result = reuse.search(idxs, query=q, limit=20)
    except Exception as exc:
        print('FAIL', repr(q), f'EX raised: {type(exc).__name__}: {exc}')
        failures.append((q, f'EX raised: {type(exc).__name__}: {exc}'))
        continue
    ids = [item['id'] for item in result['items']]
    want = case['sessions']
    ok = set(ids) == set(want)
    detail = f'ids={ids} want={want}'
    if 'snippet_indexes' in case:
        snaps = {}
        for item in result['items']:
            if item['id'] in want:
                snaps[item['id']] = [s['message_index'] for s in item.get('snippets') or []]
        want_idx = case['snippet_indexes']
        got = snaps.get(want[0]) if want else None
        ok = ok and got == want_idx
        detail += f' snippets={snips if False else snaps} want_idx={want_idx}'
    if 'forbidden_indexes' in case:
        for item in result['items']:
            if item['id'] in want:
                got_idx = [s['message_index'] for s in item.get('snippets') or []]
                bad = [i for i in got_idx if i in case['forbidden_indexes']]
                if bad: ok = False; detail += f' FORBIDDEN_hit={bad}'
    if case.get('zero_hit_clean'):
        ok = ok and not result['errors'] and not result['partial']
        detail += f" errors={result['errors']} partial={result['partial']}"
    if case.get('snippets_empty'):
        item = next((i for i in result['items'] if i['id'] in want), None)
        if item is not None:
            ok = ok and not item.get('snippets')
            detail += f" status={item.get('snippet_status')}"
    print(('PASS' if ok else 'FAIL'), repr(q), detail)
    if not ok: failures.append((q, detail))
    for _s,_src,ic in idxs: ic.conn.close()

sources_after = {str(p): sha(p) for p in sorted(FIX.rglob('*.jsonl'))}
integrity = sources_before == sources_after
print('SOURCE_INTEGRITY', 'OK' if integrity else 'MODIFIED')
if not integrity: failures.append(('integrity', 'source files changed'))
sys.exit(1 if failures else 0)
