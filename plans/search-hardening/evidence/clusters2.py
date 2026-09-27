#!/usr/bin/env python3
"""Focused follow-ups: A-p5 cross-message masking, B-p2redo cursor vs index revision."""
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, '/tmp/cchv-hardening/mutant')
from history_core.sources import Indexer, parse_codex_session_file
from history_core import reuse

FIX = Path('/tmp/cchv-hardening/home')
cache = Path('/tmp/cchv-hardening/cache/v2')
shutil.rmtree(cache, ignore_errors=True)
(cache / 'codex').mkdir(parents=True)
idx = Indexer(FIX / '.codex/sessions/2026/09/06', cache / 'codex', 'codex',
              parse_file_fn=parse_codex_session_file, parser_version=5, recall_db_path=None)
idx.scan_sessions()
idxs = [('linux', 'codex', idx)]

print('== A-p5: five early single-term hits vs late phrase ==')
r = reuse.search(idxs, query='gammaterm1 gammaterm2', limit=20)
d = next(i for i in r['items'] if i['id'] == 'delta-0001')
print('delta snippets:', [s['message_index'] for s in d['snippets']],
      '→ phrase@2106', 'INCLUDED' if any(s['message_index'] == 2106 for s in d['snippets']) else 'EXCLUDED by earlier any-term hits')

print('== B-p2redo: cursor vs INDEX revision ==')
r1 = reuse.search(idxs, query='填充', limit=1)
cur = r1['next_cursor']
print('cursor issued:', bool(cur))
p2 = reuse.search(idxs, query='填充', limit=1, cursor=cur)
print('page2 ok while index unchanged:', [i['id'] for i in p2['items']], 'partial=', p2['partial'])
# now append a source file AND rescan → INDEX revision changes
f = FIX / '.codex/sessions/2026/09/06/rollout-2026-09-06T10-59-59-newer.jsonl'
f.write_text(json.dumps({"timestamp":"2026-09-06T10:59:59Z","type":"session_meta","payload":{"id":"newer-0001","timestamp":"2026-09-06T10:59:59Z","cwd":"/fix/proj-new"}})+"\n"
           + json.dumps({"timestamp":"2026-09-06T11:00:00Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"这里也有填充内容 new"}]}})+"\n", encoding='utf-8')
idx.scan_sessions()
try:
    reuse.search(idxs, query='填充', limit=1, cursor=cur)
    print('B-p2redo stale cursor ACCEPTED after index change → I7 VIOLATION')
except ValueError as exc:
    print('B-p2redo stale cursor rejected after index change:', exc)
r2 = reuse.search(idxs, query='填充', limit=20)
print('recovery: fresh search items=', sorted(i['id'] for i in r2['items']))
f.unlink()
idx.conn.close()
