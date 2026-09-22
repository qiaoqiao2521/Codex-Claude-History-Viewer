#!/usr/bin/env python3
"""Frozen synthetic evidence questions and two-source 10k performance corpus."""
import argparse
import hashlib
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / 'tests/fixtures/reuse_queries.json'
SEED = 20260922
TARGET_BYTES = 16384
MIN_BYTES, MAX_BYTES = 14746, 18022


def load_questions(path=QUESTIONS):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def session_bytes(source, session_id, project, evidence=(), number=0, seed=SEED):
    """20 parsed messages, shared titles/timestamps, Chinese and byte-exact sizing."""
    if source not in ('codex', 'claude'):
        raise ValueError('unsupported_synthetic_source')
    rng = random.Random(seed + number)
    ts = '2026-09-%02dT09:00:00.000Z' % (1 + number % 20)
    messages = []
    targets = dict(evidence)
    for index in range(20):
        # The first title is deliberately shared: answer text is deeper in the session.
        text = targets.get(index, '继续修复索引。' if index == 0 else
                           '合成记录 %05d-%02d：检查读取边界与编码一致性。' % (number, index))
        if index == 6:
            text += '\n' + 'synthetic-long-line-0123456789 ' * 70
        text += ' 合成填充' * rng.randint(2, 6)
        role = 'user' if index % 2 == 0 else 'assistant'
        messages.append((role, text))

    def encode(items):
        rows = []
        if source == 'codex':
            rows.append({'type': 'session_meta', 'timestamp': ts,
                         'payload': {'id': session_id, 'cwd': project, 'timestamp': ts}})
        for index, (role, text) in enumerate(items):
            if source == 'codex':
                row = {'timestamp': ts, 'type': 'response_item', 'payload': {
                    'type': 'message', 'role': role, 'content': [
                        {'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}}
            else:
                row = {'timestamp': ts, 'sessionId': session_id, 'cwd': project, 'type': 'message',
                       'message': {'id': '%s-%02d' % (session_id, index), 'role': role, 'content': text}}
            rows.append(row)
        return ('\n'.join(json.dumps(row, ensure_ascii=False, separators=(',', ':')) for row in rows) + '\n').encode()

    data = encode(messages)
    if len(data) > TARGET_BYTES:
        raise ValueError('synthetic_payload_exceeds_frozen_size')
    # Padding is message text so the benchmark exercises a real 16KiB searchable transcript.
    role, text = messages[-1]
    messages[-1] = (role, text + 'x' * (TARGET_BYTES - len(data)))
    data = encode(messages)
    assert len(data) == TARGET_BYTES
    return data


def source_dir(root, source):
    return Path(root) / source / ('sessions' if source == 'codex' else 'projects')


def generate_dataset(root, *, performance=False, questions=QUESTIONS):
    """Refuse to reuse a nonempty directory: an old file would alter the frozen corpus."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise ValueError('synthetic_output_must_be_empty')
    root.mkdir(parents=True, exist_ok=True)
    spec = load_questions(questions)
    records = list(spec['sessions'])
    if performance:
        for source in ('codex', 'claude'):
            count = sum(s['source'] == source for s in records)
            for i in range(5000 - count):
                records.append({'source': source, 'id': 'perf-%s-%05d' % (source, i),
                                'project': i % len(spec['projects']), 'evidence': []})
    manifest_rows = []
    for number, record in enumerate(records):
        path = source_dir(root, record['source']) / (record['id'] + '.jsonl')
        path.parent.mkdir(parents=True, exist_ok=True)
        data = session_bytes(record['source'], record['id'], spec['projects'][record['project']],
                             record['evidence'], number=number, seed=spec['seed'])
        path.write_bytes(data)
        manifest_rows.append({'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(data).hexdigest(),
                              'size': len(data), 'source': record['source'], 'messages': 20})
    manifest_rows.sort(key=lambda item: item['path'])
    digest = hashlib.sha256('\n'.join('%s:%s' % (row['path'], row['sha256']) for row in manifest_rows).encode()).hexdigest()
    manifest = {'schema_version': 'history.reuse-corpus.v1', 'seed': spec['seed'],
                'purpose': 'performance_10k' if performance else 'fixed_questions',
                'questions_sha256': sha256(questions), 'generator_sha256': sha256(__file__),
                'dataset_sha256': digest, 'session_count': len(records),
                'counts': {source: sum(r['source'] == source for r in records) for source in ('codex', 'claude')},
                'messages_per_session': 20, 'bytes_per_session': TARGET_BYTES, 'files': manifest_rows}
    (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


def verify_dataset(root, *, require_performance=False):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['questions_sha256'] != sha256(QUESTIONS):
        raise ValueError('frozen_questions_changed')
    actual = sorted(str(p.relative_to(root)) for source in ('codex', 'claude')
                    for p in source_dir(root, source).rglob('*.jsonl'))
    if actual != [r['path'] for r in manifest['files']]:
        raise ValueError('corpus_file_set_changed')
    for row in manifest['files']:
        path = root / row['path']
        if path.is_symlink() or not MIN_BYTES <= path.stat().st_size <= MAX_BYTES or sha256(path) != row['sha256']:
            raise ValueError('corpus_file_changed: ' + row['path'])
    digest = hashlib.sha256('\n'.join('%s:%s' % (r['path'], r['sha256']) for r in manifest['files']).encode()).hexdigest()
    if digest != manifest['dataset_sha256']:
        raise ValueError('corpus_manifest_changed')
    if require_performance and (manifest['counts'] != {'codex': 5000, 'claude': 5000} or len(actual) != 10000):
        raise ValueError('performance_requires_frozen_10k_corpus')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--performance', action='store_true')
    args = parser.parse_args()
    manifest = generate_dataset(args.out, performance=args.performance)
    print(json.dumps({k: v for k, v in manifest.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
