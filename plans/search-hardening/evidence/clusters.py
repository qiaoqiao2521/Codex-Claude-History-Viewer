#!/usr/bin/env python3
"""Bounded fault-cluster probes A/B/C against the isolated copy
(code identical to the uncommitted working tree). Read-only on fixtures."""
import shutil, sys, threading, time, base64, json, hashlib
from pathlib import Path

repo = Path('/tmp/cchv-hardening/mutant')
sys.path.insert(0, str(repo))
from history_core.sources import Indexer, parse_codex_session_file, parse_claude_session_file
from history_core import reuse

FIX = Path('/tmp/cchv-hardening/home')

def build(cache_name):
    cache = Path('/tmp/cchv-hardening/cache') / cache_name
    shutil.rmtree(cache, ignore_errors=True)
    idxs = []
    for sub, src, parser in (('codex', 'codex', parse_codex_session_file), ('claude', 'claude', parse_claude_session_file)):
        d = FIX / ('.codex/sessions/2026/09/06' if src == 'codex' else '.claude/projects/proj-claude')
        (cache / sub).mkdir(parents=True, exist_ok=True)
        idx = Indexer(d, cache / sub, src, parse_file_fn=parser, parser_version=5, recall_db_path=None)
        idx.scan_sessions()
        idxs.append(('linux', src, idx))
    return idxs

idxs = build('clusters')
codex = idxs[0][2]

print('== A: recall & excerpts ==')
# A-p1 cross-message ordering: earliest any-term hit vs late phrase
r = reuse.search(idxs, query='gammaterm1 gammaterm2', limit=20)
g = next(i for i in r['items'] if i['id'] == 'gamma-0001')
idxs_g = [s['message_index'] for s in g['snippets']]
print('A-p1 gamma snippet indexes:', idxs_g, '(phrase lives at 2102; top-3 window =',
      'earliest-any-term' if idxs_g and max(idxs_g) < 2102 else 'includes-phrase', ')')

# A-p2 non-ASCII case folding
r = reuse.search(idxs, query='CAFÉ', limit=20)
ids = [i['id'] for i in r['items']]
sn = [s['message_index'] for i in r['items'] if i['id'] == 'alpha-0001' for s in i['snippets']]
print('A-p2 q=CAFÉ →', ids, 'snippets', sn, '→', 'ASCII-only folding (É misses)' if not sn else 'hit')

# A-p3 multibyte excerpt content
r = reuse.search(idxs, query='双千兆', limit=20)
a = next(i for i in r['items'] if i['id'] == 'alpha-0001')
print('A-p3 excerpt:', repr(a['snippets'][0]['text'][:40]), 'truncated=', a['snippets'][0]['truncated'])

# A-p4 legacy entrance parity (I9): Indexer.list_sessions_page vs reuse candidates
legacy = codex.list_sessions_page(q='双千兆', limit=50)
legacy_ids = sorted(row['id'] for row in legacy['items'])
ru = reuse.search([('linux','codex',codex)], query='双千兆', limit=20)
reuse_ids = sorted(i['id'] for i in ru['items'])
print('A-p4 legacy', legacy_ids, '== reuse', reuse_ids, '→', legacy_ids == reuse_ids)

print('== B: identity, revision, concurrency ==')
# B-p1 same-id cross-source provenance
r = reuse.search(idxs, query='claudedistinct', limit=20)
prov = [(i['source'], i['id'], i['store_id']) for i in r['items']]
print('B-p1 claudedistinct items:', prov, '→ codex ghost absent:', all(p[0]=='claude' for p in prov))

# B-p2 revision-bound cursor: page then append a file
r1 = reuse.search(idxs, query='填充', limit=1)
cur = r1['next_cursor']
print('B-p2 cursor issued:', bool(cur))
f = FIX / '.codex/sessions/2026/09/06/rollout-2026-09-06T10-59-59-newer.jsonl'
f.write_text(json.dumps({"timestamp":"2026-09-06T10:59:59Z","type":"session_meta","payload":{"id":"newer-0001","timestamp":"2026-09-06T10:59:59Z","cwd":"/fix/proj-new"}})+"\n", encoding='utf-8')
try:
    reuse.search(idxs, query='填充', limit=1, cursor=cur)
    print('B-p2 stale cursor ACCEPTED → VIOLATION of I7')
except ValueError as exc:
    print('B-p2 stale cursor rejected:', exc)

# recovery: fresh search sees the new session
r2 = reuse.search(idxs, query='填充', limit=20)
print('B-p2 recovery: after restart-from-0, total hits =', len(r2['items']), 'includes newer-0001:',
      any(i['id']=='newer-0001' for i in r2['items']))
f.unlink()

print('== C: failure & resource boundaries ==')
# C-p1 lock hold: measure search() wall time while the indexer lock is held elsewhere
def hold():
    codex.lock.acquire()
    time.sleep(3)
    codex.lock.release()
t = threading.Thread(target=hold); t.start()
time.sleep(0.2)
t0 = time.monotonic()
try:
    r = reuse.search(idxs, query='双千兆', limit=20)
    dt = time.monotonic()-t0
    print(f'C-p1 search under 3s lock hold: returned in {dt:.2f}s items={len(r["items"])} errors={r["errors"]} partial={r["partial"]}')
except Exception as exc:
    dt = time.monotonic()-t0
    print(f'C-p1 search under lock: raised {type(exc).__name__} after {dt:.2f}s: {exc}')
t.join()

# C-p2 query budget exhausted mid-candidates (progress handler never allows)
orig = reuse.query_budget
from contextlib import contextmanager
@contextmanager
def starved(idx):
    class FakeConn:
        def __getattr__(self, name):
            raise sqlite3_err
    import sqlite3
    def raiser(*a, **k): raise sqlite3.OperationalError('interrupted')
    class Locked:
        def __enter__(self): return None
        def __exit__(self, *a): return False
    # emulate: connection raises immediately on execute
    class C:
        def execute(self, *a, **k): raise sqlite3.OperationalError('interrupted')
        def create_function(self, *a, **k): pass
    yield C()
reuse.query_budget = starved
try:
    r = reuse.search(idxs, query='双千兆', limit=20)
    print('C-p2 budget starved: items=', len(r['items']), 'errors=', r['errors'], 'partial=', r['partial'],
          '→ explicit' if r['errors'] else '→ SILENT empty (I6 violation)')
finally:
    reuse.query_budget = orig
r = reuse.search(idxs, query='双千兆', limit=20)
print('C-p2 recovery: normal search again items=', len(r['items']), 'errors=', r['errors'])

for _s, _src, ic in idxs: ic.conn.close()
