#!/usr/bin/env python3
"""Strict synthetic-only oracle against an existing cache; queries cannot scan/write.

Use --setup once to build the cache, then run without it to exercise old caches.
--corrupt is a probe self-test: deliberate faulty responses must exit nonzero.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def source_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / 'home').rglob('*.jsonl'))}


def open_indexes(repo, root, cache):
    sys.path.insert(0, str(repo))
    from history_core.sources import Indexer, parse_codex_session_file, parse_claude_session_file
    result = []
    for source, relative, parser in [('codex', 'home/.codex/sessions', parse_codex_session_file),
                                     ('claude', 'home/.claude/projects', parse_claude_session_file)]:
        directory = cache / source
        directory.mkdir(parents=True, exist_ok=True)
        idx = Indexer(root / relative, directory, source, parse_file_fn=parser, parser_version=5, recall_db_path=None)
        result.append(('linux', source, idx))
    return result


def setup(repo, root, cache):
    if cache.exists():
        raise ValueError('setup requires a nonexistent cache directory')
    indexes = open_indexes(repo, root, cache)
    try:
        for _, source, idx in indexes:
            idx.scan_sessions()
            # Deliberately mark the retained cache as old. A query must not reparse
            # merely because the caller now uses parser_version=5.
            with idx.conn:
                idx.conn.execute('UPDATE sessions SET parser_version=1, search_blob=substr(search_blob,1,2000000)')
            idx.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            count = idx.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
            print(f'SETUP {source} sessions={count} retained_parser_version=1')
    finally:
        for _, _, idx in indexes:
            idx.conn.close()


def db_snapshot(indexes):
    return {source: {'content_sha256': hashlib.sha256(idx.conn.serialize()).hexdigest(),
                     'total_changes': idx.conn.total_changes,
                     'reader_state': [tuple(row) for row in idx.conn.execute('SELECT * FROM reader_state ORDER BY key')],
                     'parser_versions': [tuple(row) for row in idx.conn.execute('SELECT parser_version,COUNT(*) FROM sessions GROUP BY parser_version')]}
            for _, source, idx in indexes}


def check_equal(got, expected, label):
    if got != expected:
        actual = repr(got)
        want = repr(expected)
        raise AssertionError(f'{label}: got={actual[:900]} expected={want[:900]}')


def check_response(result, case, expected, more):
    for key in ('errors', 'partial', 'truncated', 'pagination_status', 'freshness'):
        check_equal(result.get(key), case[key], key)
    if type(result.get('partial')) is not bool or type(result.get('truncated')) is not bool:
        raise AssertionError('partial/truncated must be JSON booleans')
    check_equal(len(result['items']), len(expected), 'item count')
    check_equal(bool(result.get('next_cursor')), more, 'next_cursor availability')
    if result.get('next_cursor') is not None and not isinstance(result['next_cursor'], str):
        raise AssertionError('next_cursor must be string or null')
    if not re.fullmatch('[0-9a-f]{64}', result.get('revision', '')):
        raise AssertionError('revision must be a 64-digit hash')
    for got, want in zip(result['items'], expected):
        for key in ('system', 'source', 'store_id', 'id', 'snippet_status', 'snippets'):
            check_equal(got.get(key), want[key], f'{want["source"]}/{want["id"]}.{key}')
        if not re.fullmatch('[0-9a-f]{64}', got.get('source_revision', '')):
            raise AssertionError('source_revision must be a 64-digit hash')


def corrupt_response(result, corruption):
    if corruption == 'partial':
        result['partial'] = not result['partial']
    elif corruption == 'errors':
        result['errors'] = [{'system': 'linux', 'source': 'codex', 'error': 'invented'}]
    elif result['items']:
        item = result['items'][0]
        if corruption == 'source': item['source'] = 'claude' if item['source'] == 'codex' else 'codex'
        elif corruption == 'store': item['store_id'] = '0' * 64
        elif corruption == 'body' and item['snippets']: item['snippets'][0]['text'] = 'wrong body'
        elif corruption == 'status': item['snippet_status'] = 'invented_status'
        elif corruption == 'missing_item': result['items'].pop()
    return result


def run(repo, root, cache, corruption=None):
    from manifest_spec import manifest
    expected_manifest = manifest(root)
    persisted = json.loads((root / 'manifest.json').read_text())
    check_equal(persisted, expected_manifest, 'persisted manifest')
    check_equal(source_hashes(root), json.loads((root / 'source-hashes.json').read_text()), 'source fixture integrity before')
    for source in ('codex', 'claude'):
        if not (cache / source / 'index.sqlite').is_file():
            raise ValueError('cache does not exist; run --setup first')
    indexes = open_indexes(repo, root, cache)
    from history_core import reuse
    from history_core.sources import Indexer
    failures = []
    before = db_snapshot(indexes)
    source_before = source_hashes(root)
    blocked_writes = []
    def readonly(op, first, second, db, trigger):
        if op in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                  sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE,
                  sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX}:
            blocked_writes.append([op, first, second])
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    try:
        deep = expected_manifest['deep_message']
        idx = next(i for _, s, i in indexes if s == deep['source'])
        actual = idx.conn.execute('SELECT text FROM messages WHERE session_id=? ORDER BY ts_ms,id LIMIT 1 OFFSET ?', (deep['id'], deep['index'])).fetchone()
        check_equal(actual[0] if actual else None, deep['text'], 'G2 construction-defined phrase index')
        alpha = idx.conn.execute('SELECT search_blob,parser_version FROM sessions WHERE id=?', ('alpha-0001',)).fetchone()
        check_equal(alpha['parser_version'], 1, 'retained old parser version')
        if 'after2mneedle' in alpha['search_blob']:
            raise AssertionError('tail fixture accidentally fits within the old bounded blob')
        for _, _, candidate in indexes:
            check_equal([tuple(row) for row in candidate.conn.execute('SELECT DISTINCT parser_version FROM sessions')], [(1,)], 'all cached parser versions remain old')
        for _, _, idx in indexes:
            idx.conn.set_authorizer(readonly)
        for case in expected_manifest['cases']:
            try:
                with ExitStack() as stack:
                    scan_guard = stack.enter_context(patch.object(Indexer, 'scan_sessions', side_effect=AssertionError('query attempted scan')))
                    if corruption == 'underscore_unescaped':
                        stack.enter_context(patch.object(reuse, '_escape_sql_like', side_effect=lambda s: str(s).replace('\\', '\\\\').replace('%', '\\%')))
                    if case.get('fault') == 'codex_query':
                        original = reuse._candidates
                        def faulty(indexer, *args, **kwargs):
                            if indexer.source == 'codex':
                                raise sqlite3.OperationalError('synthetic source query failure')
                            return original(indexer, *args, **kwargs)
                        stack.enter_context(patch.object(reuse, '_candidates', side_effect=faulty))
                    elif case.get('fault') == 'snippet_query':
                        stack.enter_context(patch.object(reuse, '_indexed_snippets', side_effect=sqlite3.OperationalError('interrupted')))
                    cursor = None
                    observed = []
                    for start in range(0, max(1, len(case['items'])), 20):
                        expected = case['items'][start:start + 20]
                        result = reuse.search(indexes, query=case['query'], limit=20, cursor=cursor)
                        result = corrupt_response(result, corruption)
                        check_response(result, case, expected, start + 20 < len(case['items']))
                        observed += [(x['system'], x['source'], x['store_id'], x['id']) for x in result['items']]
                        cursor = result['next_cursor']
                    check_equal(len(observed), len(set(observed)), 'full identity duplicates across pages')
                    if cursor is not None:
                        raise AssertionError('unexpected extra page')
                    check_equal(scan_guard.call_count, 0, 'query scan attempts including swallowed failures')
                print('PASS', case['name'])
            except Exception as exc:
                failures.append(case['name'])
                print('FAIL', case['name'], type(exc).__name__, str(exc))
        check_equal(source_hashes(root), source_before, 'source fixture integrity after')
        check_equal(db_snapshot(indexes), before, 'existing cache content/revision/write counter')
        check_equal(blocked_writes, [], 'attempted query writes')
        print('PASS source_jsonl_unchanged cache_bytes_revision_parser_versions_unchanged no_query_scan_or_write')
    finally:
        for _, _, idx in indexes:
            idx.conn.set_authorizer(None)
            idx.conn.close()
    print(json.dumps({'cases': len(expected_manifest['cases']), 'passed': len(expected_manifest['cases']) - len(failures), 'failed': failures, 'corruption': corruption}))
    return 1 if failures else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--setup', action='store_true')
    parser.add_argument('--corrupt', choices=['source', 'store', 'body', 'status', 'partial', 'errors', 'missing_item', 'underscore_unescaped'])
    args = parser.parse_args()
    if args.setup:
        setup(args.repo.resolve(), args.root.resolve(), args.cache.resolve())
    else:
        try:
            raise SystemExit(run(args.repo.resolve(), args.root.resolve(), args.cache.resolve(), args.corrupt))
        except Exception as exc:
            print('FAIL harness', type(exc).__name__, str(exc))
            raise SystemExit(1)
