"""Read a local-day briefing from the Web's existing index, never whole audits."""
from .activity import SUPPORTED, window, local_timestamp, window_metadata
from .evidence import redact_text, source_store_id
from .reuse import index_revision, query_budget


def build_window_briefing(backend, date, timezone, project=None, limit=2000):
    start, end = window(date, timezone)
    source = backend.source
    indexer = backend.indexer
    coverage = dict(supported=source in SUPPORTED, freshness='unknown',
                    last_successful_refresh=getattr(backend, 'last_refreshed_at', None),
                    checked_through=None, query_budget_seconds=2,
                    evidence_limit_per_session=6, excerpt_chars=600)
    report = dict(schema_version='history.web-briefing.v2', date=date, timezone=timezone,
                  source=source, window=window_metadata(start, end, timezone),
                  overview=dict(session_count=0, project_count=0, message_count=0),
                  items=[], coverage=coverage, partial=True, truncated=False,
                  session_limit=limit,
                  interpretation='用户消息是意图，助手消息是报告；历史记录不证明当前状态。')
    if not coverage['supported']:
        coverage['reason'] = 'unsupported'
        return report
    if indexer is None or getattr(backend, 'last_refresh_error', None):
        coverage.update(reason='source_unavailable', freshness='stale')
        return report
    system = getattr(backend, 'system', 'linux')
    revision = index_revision(indexer)
    store = source_store_id(system, source, indexer)
    public = "role IN ('user','assistant','tool') AND kind NOT LIKE 'context%' AND kind NOT LIKE 'raw_json%' AND kind NOT LIKE '%reasoning%' AND kind != 'thinking'"
    where = f'activity_ts_ms>=? AND activity_ts_ms<? AND {public}'
    params = [start, end]
    if project is not None:
        where += ' AND session_id IN (SELECT id FROM sessions WHERE cwd=?)'
        params.append(project)
    with query_budget(indexer) as conn:
        total = conn.execute(f'SELECT COUNT(DISTINCT session_id) FROM messages WHERE {where}', params).fetchone()[0]
        rows = conn.execute(f'''SELECT session_id, MIN(activity_ts_ms) first_ms,
            MAX(activity_ts_ms) last_ms, COUNT(*) n FROM messages WHERE {where}
            GROUP BY session_id ORDER BY last_ms DESC, session_id LIMIT ?''', params + [limit]).fetchall()
        coverage['messages_without_verified_time'] = conn.execute(
            f'SELECT COUNT(*) FROM messages WHERE activity_ts_ms IS NULL AND {public}').fetchone()[0]
        coverage['unparsed_records'] = conn.execute("SELECT COUNT(*) FROM messages WHERE kind LIKE 'raw_json%'").fetchone()[0]
        coverage['indexed'] = bool(conn.execute('SELECT 1 FROM sessions LIMIT 1').fetchone()) or bool(coverage['last_successful_refresh'])
        for row in rows:
            sid = row['session_id']
            meta = conn.execute('SELECT cwd FROM sessions WHERE id=?', (sid,)).fetchone()
            messages = conn.execute(f'''WITH numbered AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY ts_ms,id)-1 message_index FROM messages WHERE session_id=?)
                SELECT message_index,role,kind,activity_ts_ms,text,
                length(text)>600 text_truncated FROM numbered
                WHERE activity_ts_ms>=? AND activity_ts_ms<? AND {public}
                ORDER BY activity_ts_ms DESC,id DESC LIMIT 6''', (sid,start,end)).fetchall()
            identity = dict(system=system, source=source, store_id=store,
                            session_id=sid, source_revision=revision)
            evidence = [dict(identity, message_index=m['message_index'], timestamp_ms=m['activity_ts_ms'],
                             timestamp_local=local_timestamp(m['activity_ts_ms'], timezone),
                             role=m['role'], kind=m['kind'], text=redact_text(m['text'] or '')[:600],
                             text_truncated=bool(m['text_truncated'])) for m in reversed(messages)]
            report['items'].append(dict(identity, project=redact_text(meta['cwd'] or '') if meta else '',
                                        message_count=row['n'], evidence=evidence,
                                        evidence_truncated=row['n']>len(evidence)))
    if index_revision(indexer) != revision:
        raise ValueError('index_revision_changed')
    report['overview'] = dict(session_count=len(rows), project_count=len({x['project'] for x in report['items'] if x['project']}),
                              message_count=sum(x['message_count'] for x in report['items']))
    report['truncated'] = total > len(rows)
    coverage.update(candidate_count=total, reason='cached_snapshot',
                    note='仅按索引中有明确时间的公开消息统计；缓存新鲜度未知，不代表已检查全部最新工作。')
    return report
