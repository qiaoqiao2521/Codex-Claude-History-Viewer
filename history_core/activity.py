"""Explicit local-day evidence, using the existing source parsers and index.

No inferred accomplishments. Cache observations are historical, never a claim
that a live source has been completely inspected through the current time.
"""
import argparse
import hashlib
import json
import os
import time
from datetime import date as Date, datetime, timedelta, timezone as UTC
from pathlib import Path
from zoneinfo import ZoneInfo

from .evidence import redact_text, source_store_id
from .providers import canonical_source, include_file, file_suffixes
from .reuse import query_budget, error_code

SUPPORTED = {'codex', 'claude', 'mcode'}
DEFAULT_ROOTS = {'codex': '.codex/sessions', 'claude': '.claude/projects',
                 'mcode': '.minimax/v2/sessions'}


def window(date, timezone):
    day = Date.fromisoformat(date)
    if day.isoformat() != date:
        raise ValueError('date_requires_YYYY_MM_DD')
    zone = ZoneInfo(timezone)
    start = datetime.combine(day, datetime.min.time(), zone)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), zone)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _now():
    return datetime.now(UTC.utc).isoformat()


def _manifest(root, source):
    """Stat only accepted recordings, never follow links or manifest paths."""
    found = {}
    def fail(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        for name in dirs + files:
            if (Path(directory) / name).is_symlink():
                raise ValueError('source_symlink_not_allowed')
        for name in files:
            path = Path(directory) / name
            if path.suffix not in file_suffixes(source) or not include_file(source, path):
                continue
            paths = [path]
            if source == 'mcode':
                paths.append(path.parent / 'manifest.json')
            for part in paths:
                if part.is_symlink():
                    raise ValueError('source_symlink_not_allowed')
                with part.open("rb"):
                    pass
                st = part.stat()
                found[str(part.relative_to(root))] = [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
    return found


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _state(indexer, key):
    row = indexer.conn.execute('SELECT value FROM reader_state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _put(indexer, key, value):
    with indexer.conn:
        indexer.conn.execute('INSERT OR REPLACE INTO reader_state VALUES (?,?)', (key, json.dumps(value)))


def read_store(indexer, source, root, *, date, timezone, refresh=False,
               limit=100, offset=0, index_revision=None, session_id=None, evidence_limit=6, message_offset=0, message_index=None, text_offset=0):
    start, end = window(date, timezone)
    if source not in SUPPORTED:
        raise ValueError('activity_source_unsupported')
    if not 1 <= limit <= 500 or not 1 <= evidence_limit <= 100 or offset < 0 or message_offset < 0:
        raise ValueError('invalid_activity_budget')
    if text_offset < 0 or (message_index is not None and (message_index < 0 or not session_id)):
        raise ValueError('message_index_requires_session')
    if text_offset and (message_index is None or not index_revision):
        raise ValueError('text_offset_requires_message_and_revision')
    started = time.monotonic()
    coverage = dict(source=source, supported=True, readable=True, indexed=False,
                    freshness='unknown', last_successful_refresh=None,
                    checked_through=None, observation_scope='selected recordings snapshot; not live completeness',
                    refresh_requested=refresh, files_observed=0, files_changed=None,
                    query_budget_seconds=2, query_budget_scope='SQLite VM only; file I/O, refresh and formatting measured separately', message_limit_per_session=evidence_limit)
    if refresh:
        try:
            before = _manifest(root, source)
            prior = _state(indexer, 'activity_observation') or {}
            coverage['files_deleted'] = len(set(prior.get('manifest', {}))-set(before))
            coverage['files_changed'] = sum(prior.get('manifest', {}).get(k) != v for k, v in before.items())
            skipped = set()
            for attempt in range(3):
                try:
                    indexer.scan_sessions(skipped_paths=skipped, build_audits=False, preserve_recordings=True)
                    break
                except ValueError as exc:
                    changed = getattr(exc, 'changed_path', None)
                    if changed is None or attempt == 2:
                        raise
                    skipped.add(changed)
            if skipped:
                raise ValueError('partial_refresh_unstable_recordings: ' + ', '.join(str(p.relative_to(root)) for p in sorted(skipped)))
            after = _manifest(root, source)
            if before != after:
                raise ValueError('source_changed_during_refresh')
            observation = dict(at=_now(), manifest=after, fingerprint=_digest(after),
                               revision=indexer.conn.execute("SELECT value FROM reader_state WHERE key='revision'").fetchone()[0])
            _put(indexer, 'activity_observation', observation)
            _put(indexer, 'activity_refresh_error', None)
        except Exception as exc:
            if isinstance(exc, OSError):
                coverage['readable'] = False
            _put(indexer, 'activity_refresh_error', type(exc).__name__ + ':' + str(exc))
    observation = _state(indexer, 'activity_observation')
    refresh_error = _state(indexer, 'activity_refresh_error')
    if observation:
        coverage.update(indexed=True, last_successful_refresh=observation['at'])
    try:
        current = _manifest(root, source)
        coverage.update(readable=True, last_observed_at=_now(), files_observed=len(current))
        if observation:
            coverage['freshness'] = 'observed_unchanged' if _digest(current) == observation['fingerprint'] else 'stale'
    except Exception as exc:
        coverage.update(readable=False, freshness='unknown', observation_error=type(exc).__name__)
    coverage['indexed'] = bool(observation) or bool(indexer.conn.execute('SELECT 1 FROM sessions LIMIT 1').fetchone())
    if refresh_error:
        coverage.update(refresh_error=refresh_error, freshness='stale')
    store = source_store_id('local', source, indexer)
    with query_budget(indexer) as conn:
        revision = _digest([store, conn.execute("SELECT value FROM reader_state WHERE key='revision'").fetchone()[0]])
        if ((offset or message_offset) and not index_revision) or (index_revision and index_revision != revision):
            raise ValueError('activity_revision_changed_or_missing: restart at offset 0')
        where = "m.activity_ts_ms >= ? AND m.activity_ts_ms < ? AND m.role IN ('user','assistant','tool') AND m.kind NOT LIKE 'context%' AND m.kind NOT LIKE 'raw_json%' AND m.kind NOT LIKE '%reasoning%' AND m.kind != 'thinking'"
        params = [start, end]
        if session_id:
            where += ' AND m.session_id=?'
            params.append(session_id)
        total = conn.execute(f'SELECT COUNT(DISTINCT m.session_id) FROM messages m WHERE {where}', params).fetchone()[0]
        rows = conn.execute(f'''SELECT s.id, s.title, s.cwd, s.file_path, s.start_ts_ms, s.activity_metadata_json,
            MIN(m.activity_ts_ms) first_ms, MAX(m.activity_ts_ms) last_ms, COUNT(*) message_count
            FROM messages m JOIN sessions s ON s.id=m.session_id WHERE {where}
            GROUP BY s.id ORDER BY last_ms DESC, s.id LIMIT ? OFFSET ?''', params + [limit, offset]).fetchall()
        missing = conn.execute("SELECT COUNT(*) FROM messages WHERE activity_ts_ms IS NULL AND role IN ('user','assistant','tool') AND kind NOT LIKE 'context%'").fetchone()[0]
        coverage['messages_without_verified_time'] = missing
        metadata = [json.loads(r[0] or '{}') for r in conn.execute('SELECT activity_metadata_json FROM sessions')]
        coverage['identity_conflicts'] = sum(bool(m.get('identity_conflict')) for m in metadata)
        coverage['recording_warnings'] = [m['warnings'] for m in metadata if any(m.get('warnings', {}).values())]
        coverage['excluded_records'] = ['system/context, internal reasoning, malformed/unrecognized records',
                                       'Claude agent-* child files are not indexed by the existing provider'] if source == 'claude' else ['system/context, internal reasoning, malformed/unrecognized records']
        if observation and observation.get('revision') != conn.execute("SELECT value FROM reader_state WHERE key='revision'").fetchone()[0]:
            coverage['freshness'] = 'stale'
        coverage['unparsed_indexed_records'] = conn.execute("SELECT COUNT(*) FROM messages WHERE kind LIKE 'raw_json:%'").fetchone()[0]
        items = []
        body_chars = 0
        for row in rows:
            identity = dict(system='local', source=source, store_id=store, session_id=row['id'], source_revision=revision)
            # Number the full session before applying the window, preserving reader locators.
            messages = conn.execute('''WITH numbered AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY ts_ms,id)-1 message_index
                FROM messages WHERE session_id=?)
                SELECT * FROM numbered WHERE activity_ts_ms>=? AND activity_ts_ms<?
                AND role IN ('user','assistant','tool') AND kind NOT LIKE 'context%'
                AND kind NOT LIKE 'raw_json%' AND kind NOT LIKE '%reasoning%' AND kind != 'thinking' AND (? IS NULL OR message_index=?) ORDER BY activity_ts_ms DESC,id DESC LIMIT ? OFFSET ?''',
                (row['id'], start, end, message_index, message_index, evidence_limit, message_offset)).fetchall()
            evidence = []
            for message in reversed(messages):
                text = redact_text(message['text'] or '')
                body_chars += len(text)
                meta = json.loads(message['activity_meta_json'] or '{}')
                evidence.append(dict(identity, message_index=message['message_index'],
                    timestamp_ms=message['activity_ts_ms'], role=message['role'], kind=message['kind'],
                    evidence_type=('intent' if message['role']=='user' else 'tool_record' if message['role']=='tool' or message['kind'].startswith('tool') else 'assistant_report'),
                    text=text[text_offset:text_offset+2000], text_truncated=text_offset>0 or len(text)>2000,
                    text_offset=text_offset, text_chars=len(text),
                    next_text_offset=text_offset+2000 if text_offset+2000<len(text) else None, locator=meta))
            items.append(dict(identity, title=redact_text(row['title']), title_scope='session context; may predate requested window',
                session_start_ms=row['start_ts_ms'], evidence_order='latest window messages, displayed chronologically; offset reads older records', project=redact_text(row['cwd'] or ''),
                native_session_id=json.loads(row['activity_metadata_json'] or '{}').get('native_session_id', row['id']),
                first_activity_ms=row['first_ms'], last_activity_ms=row['last_ms'],
                window_message_count=row['message_count'], evidence=evidence,
                evidence_truncated=message_offset>0 or row['message_count']>len(evidence),
                next_message_offset=message_offset+len(evidence) if message_offset+len(evidence)<row['message_count'] else None,
                relation=json.loads(row['activity_metadata_json'] or '{}'),
                recording=str(Path(row['file_path']).relative_to(root))))
        coverage.update(candidate_count=total, returned_sessions=len(items),
                        evidence_messages_read=sum(len(x['evidence']) for x in items), body_chars_read=body_chars,

                        truncated=offset+len(items)<total,
                        wall_seconds=round(time.monotonic()-started, 6))
        final_revision = _digest([store, conn.execute("SELECT value FROM reader_state WHERE key='revision'").fetchone()[0]])
        if final_revision != revision:
            raise ValueError('activity_revision_changed: restart at offset 0')
        return dict(source=source, store_id=store, index_revision=revision, coverage=coverage,
                    items=items, next_offset=offset+len(items) if offset+len(items)<total else None)


def query_activity(stores, *, date, timezone, data_dir, refresh=False, limit=100,
                   offset=0, revisions=None, session_id=None, evidence_limit=6, message_offset=0, message_index=None, text_offset=0):
    """Each explicit (source, sessions_root) remains a separate identity and page."""
    from .reader import HistoryReader
    start, end = window(date, timezone)
    if not stores:
        raise ValueError('source_selection_required')
    if revisions is not None and not isinstance(revisions, dict):
        raise ValueError('revisions_must_be_object')
    if len(stores) != len(set(canonical_source(s) for s in stores)):
        raise ValueError('duplicate_source_selection')
    results = []
    for name, root in stores.items():
        source = canonical_source(name)
        if source not in SUPPORTED:
            results.append(dict(source=source, items=[], coverage=dict(supported=False, readable=None,
                indexed=None, freshness='unknown', last_successful_refresh=None, last_observed_at=None, checked_through=None, truncated=None, query_budget_seconds=2, reason='activity_source_unsupported')))
            continue
        try:
            with HistoryReader(source, root, data_dir, validate_tree=False) as reader:
                results.append(reader.activity(date=date, timezone=timezone, refresh=refresh,
                    limit=limit, offset=offset, index_revision=(revisions or {}).get(source),
                    session_id=session_id, evidence_limit=evidence_limit, message_offset=message_offset, message_index=message_index, text_offset=text_offset))
        except Exception as exc:
            results.append(dict(source=source, items=[], coverage=dict(supported=True, readable=False if isinstance(exc, OSError) else None,
                indexed=None, freshness='unknown', last_successful_refresh=None, last_observed_at=None, checked_through=None, truncated=None, query_budget_seconds=2, reason=error_code(exc), detail=redact_text(str(exc)))))
    return dict(schema_version='history.activity.v1', date=date, timezone=timezone,
                window=dict(start_ms=start, end_ms=end, semantics='[start,end)'), sources=results,
                partial=any(not r['coverage'].get('indexed') or r['coverage'].get('freshness')!='observed_unchanged'
                            or r['coverage'].get('identity_conflicts') or r['coverage'].get('unparsed_indexed_records') or r['coverage'].get('recording_warnings') or r['coverage'].get('messages_without_verified_time') or r['coverage'].get('truncated')
                            for r in results),
                interpretation='User text is intent; assistant text is a report; tool records are evidence, not proof of present project state.')


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--timezone', required=True)
    parser.add_argument('--sources', required=True, help='Comma-separated source names')
    parser.add_argument('--store', action='append', default=[], help='source=/explicit/sessions/root')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--refresh', action='store_true', help='Explicit incremental refresh; default cached evidence plus stat observation')
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--revisions', default='{}', help='JSON source:index_revision from previous page')
    parser.add_argument('--session-id')
    parser.add_argument('--message-index', type=int, help='Exact indexed message within the requested day/session')
    parser.add_argument('--text-offset', type=int, default=0, help='Offset in redacted text; requires exact message and revision')
    parser.add_argument('--message-offset', type=int, default=0, help='Within each windowed session; requires revisions')
    parser.add_argument('--evidence-limit', type=int, default=6)
    args = parser.parse_args(argv)
    selected = [canonical_source(s.strip()) for s in args.sources.split(',')]
    if not all(selected) or len(set(selected)) != len(selected):
        parser.error('sources must be nonempty and distinct')
    overrides = dict(x.split('=', 1) for x in args.store)
    if set(overrides)-set(selected):
        parser.error('store override must name a selected source')
    stores = {s: Path(overrides[s]).expanduser() if s in overrides else Path.home()/DEFAULT_ROOTS[s]
              if s in DEFAULT_ROOTS else None for s in selected}
    result = query_activity(stores, date=args.date, timezone=args.timezone, data_dir=args.data_dir,
        refresh=args.refresh, limit=args.limit, offset=args.offset, revisions=json.loads(args.revisions),
        session_id=args.session_id, evidence_limit=args.evidence_limit, message_offset=args.message_offset, message_index=args.message_index, text_offset=args.text_offset)
    print(json.dumps(result, ensure_ascii=False))
    return 0
