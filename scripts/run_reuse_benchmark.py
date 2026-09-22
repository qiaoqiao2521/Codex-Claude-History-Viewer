#!/usr/bin/env python3
"""Freeze old single-source baseline and measure evidence search over local HTTP.

Examples:
  python3 scripts/run_reuse_benchmark.py baseline --dataset work/reuse-evaluation/questions --out work/reuse-evaluation/baseline.json
  python3 scripts/run_reuse_benchmark.py measure --dataset work/reuse-evaluation/performance --out work/reuse-evaluation/http.json
  python3 scripts/run_reuse_benchmark.py measure --dataset work/reuse-evaluation/questions --url http://127.0.0.1:8787 --quality-only --out work/reuse-evaluation/quality.json
"""
import argparse
from contextlib import contextmanager
from functools import partial
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.reuse_fixture import QUESTIONS, load_questions, sha256, source_dir, verify_dataset


def nearest_rank(values, percentile=.95):
    if not values or not 0 < percentile <= 1:
        raise ValueError('nonempty_samples_and_valid_percentile_required')
    return sorted(values)[math.ceil(len(values) * percentile) - 1]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def environment():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    files = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    code = {}
    for name in sorted(set(files)):
        path = ROOT / name
        if path.is_file() and not path.is_symlink() and (name == 'app.py' or name.startswith(('history_core/', 'audit/', 'scripts/'))):
            code[name] = sha256(path)
    cpu = 'unknown'
    try:
        cpu = next(line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name'))
    except (OSError, StopIteration):
        pass
    return {'platform': platform.platform(), 'python': platform.python_version(), 'cpu': cpu,
            'logical_cpu_count': os.cpu_count(), 'head': head, 'source_files_sha256': code,
            'source_tree_sha256': hashlib.sha256(json.dumps(code, sort_keys=True).encode()).hexdigest(),
            'data': 'synthetic_only', 'provider_models': 'none', 'browser_paint_ms': 'not_measured'}


def baseline(dataset, output):
    """Use immutable git archive HEAD, never the concurrently edited working tree."""
    manifest = verify_dataset(dataset)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(['git', 'archive', head], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='old-baseline-', dir=output.parent) as temp:
        isolated = Path(temp)
        snapshot = isolated / 'source'
        snapshot.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(snapshot, filter='data')
        worker = '''import json,sys
from pathlib import Path
from history_core.sources import Indexer,parse_codex_session_file,parse_claude_session_file
root,fixture,out,cache=map(Path,sys.argv[1:])
spec=json.loads(fixture.read_text());indexers={}
for source,parser,sub in [('codex',parse_codex_session_file,'sessions'),('claude',parse_claude_session_file,'projects')]:
 d=cache/source;d.mkdir(parents=True)
 idx=Indexer(root/source/sub,d,source,parse_file_fn=parser,parser_version=5)
 idx.maybe_update_index(0);indexers[source]=idx
rows=[]
for question in spec['queries']:
 idx=indexers[question['source']]
 page=idx.list_sessions_page(q=question['q'],limit=5,sort='last')
 matches=page['items'];located=False;calls=1
 for row in matches:
  evidence=idx.search_session_messages(row['id'],question['q'],limit=3);calls+=1
  if row['id']==question['session'] and any(x['message_index']==question['message_index'] for x in evidence['matches']):located=True
 rows.append({'id':question['id'],'query':question['q'],'oracle_source':question['source'],
 'top5_sessions':[r['id'] for r in matches], 'session_hit_at_5':any(r['id']==question['session'] for r in matches),
 'first_screen_message_evidence_hit':False,'located_after_open_and_in_session_search':located,
 'measured_read_calls':calls,'human_operation_count':None,'human_seconds':None})
neg=[]
for q in spec['negatives']:
 counts={s:len(i.list_sessions_page(q=q['q'],limit=5)['items']) for s,i in indexers.items()}
 neg.append({'id':q['id'],'query':q['q'],'matches_by_source':counts,'pass':not any(counts.values())})
for idx in indexers.values():idx.conn.close()
out.write_text(json.dumps({'questions':rows,'negatives':neg},ensure_ascii=False,indent=2))
'''
        env = dict(os.environ, HOME=str(isolated / 'empty-home'), PYTHONDONTWRITEBYTECODE='1')
        Path(env['HOME']).mkdir()
        env.pop('DISPLAY', None)
        env.pop('PYTHONPATH', None)
        subprocess.run([sys.executable, '-B', '-c', worker, str(Path(dataset).resolve()), str(QUESTIONS), str(output), str(isolated / 'cache')],
                       cwd=snapshot, env=env, check=True, timeout=120)
        result = json.loads(output.read_text())
        source_text = (snapshot / 'history_core/service.py').read_text()
        frontend_text = (snapshot / 'static/app.js').read_text()
    result.update(schema_version='history.reuse-baseline.v1', baseline_head=head,
                  archive_sha256=hashlib.sha256(archive).hexdigest(), questions_sha256=sha256(QUESTIONS),
                  dataset_sha256=manifest['dataset_sha256'], recorded_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  source_selection='oracle_target_source; more favorable than unknown-source user workflow',
                  evidence_api_observation='Session list has no message snippets; exact message requires a separate per-session search.',
                  cross_source_api_present='def search_all' in source_text,
                  frontend_source_selected='currentSource' in frontend_text,
                  positive_session_hit_at_5=sum(r['session_hit_at_5'] for r in result['questions']) / 20,
                  positive_evidence_hit_at_5=0.0,
                  independent_human_trial='not_run',
                  five_user_tasks={task: {'status': 'not_run', 'human_seconds': None} for task in load_questions()['user_tasks']},
                  capability_matrix={'codex_jsonl': 'measured', 'claude_jsonl': 'measured', 'openclaw_jsonl': 'not_measured',
                                     'opencode_sqlite': 'not_measured', 'hermes_sqlite': 'not_measured'})
    write_json(output, result)
    return result


def expected_stores(spec, dataset):
    """Resolve the frozen logical roots using the public source-store contract."""
    return {source: hashlib.sha256(json.dumps([
        spec['system'], source, str((Path(dataset) / details['relative_root']).resolve())
    ], ensure_ascii=False).encode()).hexdigest() for source, details in spec['stores'].items()}


def hit_target(question, item, store, system):
    return (item.get('system') == system and item.get('source') == question['source'] and item.get('store_id') == store
            and item.get('id') == question['session']
            and any(s.get('message_index') == question['message_index'] for s in item.get('snippets', [])))


def evaluate_responses(spec, responses, stores):
    positives, negatives = [], []
    for question in spec['queries']:
        response = responses[question['id']]
        items = response.get('items', [])
        positives.append({'id': question['id'], 'query': question['q'],
                          'hit_at_5': any(hit_target(question, item, stores[question['source']], spec['system']) for item in items[:5]),
                          'result_count': len(items), 'truncated': response.get('truncated'),
                          'top5': [{'source': x.get('source'), 'store_id': x.get('store_id'), 'id': x.get('id'),
                                    'message_indices': [s.get('message_index') for s in x.get('snippets', [])]} for x in items[:5]],
                          'payload_bounds_ok': len(items) <= 20 and all(len(x.get('snippets', [])) <= 3 and all(len(s.get('text', '')) <= 240 for s in x.get('snippets', [])) for x in items)})
    for question in spec['negatives']:
        response = responses[question['id']]
        negatives.append({'id': question['id'], 'query': question['q'], 'result_count': len(response.get('items', [])),
                          'pass': response.get('items') == []})
    rate = sum(x['hit_at_5'] for x in positives) / len(positives)
    return {'positive_queries': positives, 'negative_queries': negatives, 'positive_hit_at_5': rate,
            'pass': rate >= spec['thresholds']['positive_hit_at_5'] and all(x['pass'] for x in negatives)
                    and all(x['payload_bounds_ok'] for x in positives)}


def serve(dataset, cache, ready):
    """Real application Handler with only two explicitly supplied synthetic sources."""
    from http.server import ThreadingHTTPServer
    from app import Handler, SourceBackend
    from history_core.sources import parse_codex_session_file, parse_claude_session_file
    backends = {}
    for source, parser in (('codex', parse_codex_session_file), ('claude', parse_claude_session_file)):
        backend = SourceBackend(system='linux', source=source, root_dir=dataset / source,
            sessions_dir=source_dir(dataset, source), data_dir=cache, db_filename='index_%s.sqlite' % source,
            parse_file_fn=parser, parser_version=5, scan_interval=3600,
            archived_dir=cache / 'archived', deleted_dir=cache / 'deleted', recall_db_path=None, read_only=True)
        if backend.last_refresh_error:
            raise RuntimeError(backend.last_refresh_error)
        backends[('linux', source)] = backend
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'static'), source_backends=backends, runtime_system='linux', demo=True))
    counts = {source: backend.indexer.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] for (_, source), backend in backends.items()}
    write_json(ready, {'url': 'http://127.0.0.1:%d' % server.server_port, 'pid': os.getpid(), 'indexed_counts': counts})
    server.serve_forever()


@contextmanager
def local_server(dataset, output):
    with tempfile.TemporaryDirectory(prefix='reuse-http-', dir=output.parent) as temp:
        isolated = Path(temp)
        home, cache, ready = isolated / 'home', isolated / 'cache', isolated / 'ready.json'
        home.mkdir(); cache.mkdir()
        env = dict(os.environ, HOME=str(home), PYTHONDONTWRITEBYTECODE='1')
        env.pop('DISPLAY', None)
        env.pop('PYTHONPATH', None)
        log_path = output.with_suffix('.server.log')
        with log_path.open('w') as log:
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '_serve', '--dataset', str(dataset),
                                        '--cache', str(cache), '--ready', str(ready)], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 180
                while not ready.exists():
                    if process.poll() is not None:
                        raise RuntimeError('server_failed; see ' + str(log_path))
                    if time.monotonic() > deadline:
                        raise RuntimeError('server_index_timeout')
                    time.sleep(.1)
                info = json.loads(ready.read_text())
                yield info
                if list(home.rglob('*')):
                    raise AssertionError('server_wrote_to_isolated_home')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)


def measure(url, dataset, output, *, quality_only=False, managed=None):
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password:
        raise ValueError('local_http_url_required')
    manifest = verify_dataset(dataset, require_performance=not quality_only)
    if managed is not None and managed['indexed_counts'] != manifest['counts']:
        raise ValueError('server_indexed_count_does_not_match_corpus')
    code_before = environment()
    spec = load_questions()
    opener = build_opener(ProxyHandler({}))
    def request(q):
        target = url.rstrip('/') + '/api/reuse/search?' + urlencode({'q': q, 'limit': 20})
        start = time.perf_counter_ns()
        with opener.open(target, timeout=60) as response:
            raw = response.read()  # Includes receipt of the entire first-screen JSON.
        elapsed_ms = (time.perf_counter_ns() - start) / 1e6
        return json.loads(raw), elapsed_ms
    first_payload, first_ms = request(spec['queries'][0]['q'])
    for number in range(5):
        request(spec['queries'][number]['q'])
    responses, samples = {}, []
    sequence = spec['queries'] + spec['negatives']
    for number in range(24 if quality_only else 100):
        question = sequence[number % len(sequence)]
        payload, elapsed = request(question['q'])
        responses[question['id']] = payload
        samples.append({'sample': number + 1, 'query_id': question['id'], 'elapsed_ms': elapsed})
    stores = expected_stores(spec, dataset)
    quality = evaluate_responses(spec, responses, stores)
    p95 = nearest_rank([x['elapsed_ms'] for x in samples])
    code_after = environment()
    source_stable = code_before['source_tree_sha256'] == code_after['source_tree_sha256']
    result = {'schema_version': 'history.reuse-http-benchmark.v1', 'environment': code_before,
              'questions_sha256': sha256(QUESTIONS), 'dataset_sha256': manifest['dataset_sha256'],
              'dataset_counts': manifest['counts'], 'samples': samples, 'warmup_requests': 5,
              'resolved_fixture_stores': stores,
              'percentile_method': 'nearest-rank ceil(N * 0.95)', 'http_p95_ms': p95,
              'measurement_boundary': 'before local HTTP request to complete first-screen JSON receipt',
              'first_query': {'elapsed_ms': first_ms, 'query_id': spec['queries'][0]['id'],
                              'new_service_process_verified': managed is not None,
                              'os_cold_cache': 'not_claimed', 'server': managed or 'external; process age unknown'},
              'quality': quality, 'performance_gate': 'not_run' if quality_only else ('pass' if p95 <= 1000 else 'fail'),
              'browser_paint_ms': 'not_measured', 'independent_human_trial': 'not_run',
              'native_sqlite_performance': 'not_measured; JSONL result does not cover native databases',
              'source_stable_during_run': source_stable,
              'status': 'pass' if quality['pass'] and (quality_only or p95 <= 1000) and source_stable else 'fail'}
    # Detect source mutation by all queries/refresh before claiming a read-only run.
    verify_dataset(dataset, require_performance=not quality_only)
    result['source_unchanged'] = True
    write_json(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('baseline', 'measure', '_serve'):
        sub = commands.add_parser(command)
        sub.add_argument('--dataset', type=Path, required=True)
        if command == '_serve':
            sub.add_argument('--cache', type=Path, required=True)
            sub.add_argument('--ready', type=Path, required=True)
        else:
            sub.add_argument('--out', type=Path, required=True)
            if command == 'measure':
                sub.add_argument('--url')
                sub.add_argument('--quality-only', action='store_true')
    args = parser.parse_args()
    dataset = args.dataset.resolve()
    if args.command == '_serve':
        serve(dataset, args.cache, args.ready)
        return 0
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.command == 'baseline':
        result = baseline(dataset, output)
    elif args.url:
        result = measure(args.url, dataset, output, quality_only=args.quality_only)
    else:
        verify_dataset(dataset, require_performance=not args.quality_only)
        with local_server(dataset, output) as server:
            result = measure(server['url'], dataset, output, quality_only=args.quality_only, managed=server)
    print(json.dumps({key: result[key] for key in ('status', 'positive_session_hit_at_5', 'positive_evidence_hit_at_5', 'http_p95_ms') if key in result}))
    return 1 if result.get('status') == 'fail' else 0


if __name__ == '__main__':
    raise SystemExit(main())
