#!/usr/bin/env python3
"""Synthetic-only source builder. Refuses to reuse an existing output root."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

BASE = datetime(2026, 9, 6, 10, tzinfo=timezone.utc)

def timestamp(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z')

def codex_message(n, role, text):
    return {'timestamp': timestamp(n), 'type': 'response_item', 'payload': {
        'type': 'message', 'role': role, 'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}}

def write_codex(directory, sid, start, cwd, messages):
    records = [{'timestamp': timestamp(start), 'type': 'session_meta', 'payload': {
        'id': sid, 'timestamp': timestamp(start), 'cwd': cwd}}]
    records += [codex_message(start + i + 1, role, text) for i, (role, text) in enumerate(messages)]
    (directory / (sid + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')

def build(root):
    root.mkdir(parents=True, exist_ok=False)
    codex = root / 'home/.codex/sessions'
    claude = root / 'home/.claude/projects/synthetic-project'
    codex.mkdir(parents=True)
    claude.mkdir(parents=True)
    write_codex(codex, 'alpha-0001', 0, '/synthetic/alpha', [
        ('user', 'sharedneedle codex source introduction'),
        ('assistant', 'x' * 2_100_000 + 'after2mneedle 后置系统'),
        ('user', '<permissions instructions>ctxonlyneedle private setup</permissions instructions>'),
        ('assistant', 'y' * 11500 + 'tailneedle' + 'y' * 300),
        ('assistant', '在双千兆网卡上验证 OpenWrt 前先核对驱动'),
        ('assistant', 'Café café Ωω 🎯 end'),
    ])
    rows = []
    for i, (role, text) in enumerate([('user', 'sharedneedle claude source introduction'), ('assistant', 'claudedistinct only Claude reply')]):
        rows.append({'timestamp': timestamp(4000 + i), 'sessionId': 'alpha-0001', 'cwd': '/synthetic/claude',
                     'type': role, 'message': {'role': role, 'content': text}})
    (claude / 'alpha-0001.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    write_codex(codex, 'literal-0001', 100, '/synthetic/literal', [('user', 'Literal controls'), ('assistant', 'under_score percent%done slash\\path')])
    write_codex(codex, 'decoy-underscore', 110, '/synthetic/decoy', [('user', 'underXscore')])
    write_codex(codex, 'decoy-percent', 120, '/synthetic/decoy', [('user', 'percentZZdone')])
    write_codex(codex, 'decoy-backslash', 130, '/synthetic/decoy', [('user', 'slashXpath slashpath')])
    write_codex(codex, 'metadata-0001', 140, '/synthetic/cwdmetaneedle', [('user', 'Ordinary metadata example'), ('assistant', 'Ordinary reply')])
    write_codex(codex, 'cross-0001', 150, '/synthetic/cross', [('user', 'crosstermone first'), ('assistant', 'crosstermtwo second')])
    write_codex(codex, 'cross-negative', 160, '/synthetic/cross', [('user', 'crosstermone only')])
    delta = [('user', 'delta goal')]
    delta += [('assistant', f'Weak {i} gammaterm1') for i in range(5)]
    delta += [('assistant', f'Ordinary filler {i}') for i in range(2100)]
    delta += [('user', 'gammaterm1 gammaterm2 完整短语在深处')]
    assert len(delta) == 2107 and delta[2106][1] == 'gammaterm1 gammaterm2 完整短语在深处'
    write_codex(codex, 'delta-0001', 2500, '/synthetic/delta', delta)
    for i in range(25):
        write_codex(codex, f'page-{i:02}', 10000 + i, '/synthetic/pagination', [('user', f'paginationneedle case {i:02}')])
    # Audit the generator's own timestamps without importing any product parser.
    rows = 0
    for path in (root / 'home').rglob('*.jsonl'):
        for line in path.read_text(encoding='utf-8').splitlines():
            datetime.fromisoformat(json.loads(line)['timestamp'].replace('Z', '+00:00'))
            rows += 1
    from manifest_spec import manifest
    (root / 'manifest.json').write_text(json.dumps(manifest(root), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root / 'home').rglob('*.jsonl'))}
    (root / 'source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps({'root': str(root), 'files': len(hashes), 'valid_timestamps': rows, 'pagination_query': 'paginationneedle', 'pagination_hits': 25}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    build(args.root.resolve())
