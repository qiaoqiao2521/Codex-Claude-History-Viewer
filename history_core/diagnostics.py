"""Local source status and a separate, allowlisted diagnostic export."""
from datetime import datetime, timezone
from pathlib import Path
import shlex
import sqlite3

from .reuse import query_budget
from .providers import SOURCES, FILE_SOURCES

ERRORS = {
    'FileNotFoundError': ('not_found', 'source_not_found', '未发现历史。检查来源路径，或先运行对应 Agent 创建会话。'),
    'PermissionError': ('unreadable', 'permission_denied', '当前用户无法读取来源。检查目录权限后重新读取，不要自动修改权限。'),
    'ValueError': ('unsupported', 'invalid_source_format', '来源格式无法识别。检查路径是否指向该 Agent 的历史目录。'),
    'DatabaseError': ('unsupported', 'invalid_database', '数据库格式不可读取。检查来源路径，保留原数据库。'),
    'OperationalError': ('unsupported', 'source_schema_unavailable', '数据库暂不可读或格式不支持。关闭占用后重试并核对来源版本。'),
}


def optional_missing_source(backend):
    """An unused default store isn't a failed member of an all-source query.

    Explicit configuration and lost previously indexed history remain errors.
    The diagnostic card still reports the absent path for future setup.
    """
    if not getattr(backend, 'optional_discovery', False) or getattr(backend, 'last_refreshed_at', None):
        return False
    try:
        Path(backend.sessions_dir).stat()
        return False
    except FileNotFoundError:
        pass
    except OSError:
        return False
    idx = getattr(backend, 'indexer', None)
    if idx is None:
        return True
    try:
        table = 'session' if idx.source in ('opencode', 'zcode') else 'sessions'
        with query_budget(idx) as conn:
            return conn.execute('SELECT 1 FROM ' + table + ' LIMIT 1').fetchone() is None
    except sqlite3.Error:
        return False


def inspect_backend(system, source, backend):
    idx = getattr(backend, 'indexer', None)
    root = Path(getattr(idx, 'sessions_dir', None) or getattr(idx, 'db_path', None) or backend.sessions_dir)
    result = {'system':system, 'source':source, 'path':str(root), 'count':None,
              'last_refreshed_at':getattr(backend,'last_refreshed_at',None),
              'freshness':'unknown', 'error_code':None, 'status':'unknown',
              'next_step':'显式重新读取，以核对当前来源。'}
    if getattr(backend, 'refreshing', False):
        result.update(status='indexing', next_step='正在读取来源，请稍后重新检查。')
        return result
    error = getattr(backend,'last_refresh_error',None)
    try:
        root.stat()
        if error:
            kind = str(error).split(':',1)[0]
            status,code,next_step = ERRORS.get(kind,('error','refresh_failed','读取失败。检查来源后重试；先前缓存不代表当前数据。'))
            result.update(status=status,error_code=code,next_step=next_step)
        if idx is not None:
            table = 'session' if source in ('opencode','zcode') else 'sessions'
            with query_budget(idx) as conn:
                result['count']=int(conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0])
        if not error and idx is not None:
            if getattr(backend,'refreshing',False):
                result.update(status='indexing',next_step='正在读取来源，请稍后重新检查。')
            else:
                result.update(status='ready' if result['count'] else 'empty',
                              next_step='可以搜索历史；来源更新后可重新读取。' if result['count'] else '目录可读取，尚未发现可识别会话。检查路径或先创建会话。')
        if error and result['last_refreshed_at'] and result['count']:
            result['status']='stale';result['next_step']='上次缓存仍在，但最新读取失败。修正来源后重新读取。'
    except (OSError,sqlite3.Error) as exc:
        kind=type(exc).__name__
        state,code,message=ERRORS.get(kind,('error','source_unavailable','检查来源路径与权限后重试。'))
        result.update(status=state,error_code=code,next_step=message)
        if result['last_refreshed_at']: result['status']='stale'
    flag={**{src:'--'+src+'-dir' for src in FILE_SOURCES}, **{src:'--'+src+'-state-db' for src in ('opencode','hermes','zcode','agy','antigravity')}}.get(source)
    coverage = getattr(idx, '_coverage', None)
    if isinstance(coverage, dict):
        counts = {}
        for item in coverage.values():
            state = item.get('content_status', 'unknown')
            counts[state] = counts.get(state, 0) + 1
        result['content_coverage'] = counts
        if any(key != 'decoded_text' and count for key, count in counts.items()) and result['status'] in ('ready', 'empty'):
            result['status'] = 'partial'
            result['next_step'] = '已解码 %d 个会话；其余会话有不支持的步骤、旧格式或缺失正文，结果会逐项标记。' % counts.get('decoded_text', 0)
    if flag:
        location = backend.root_dir if source in FILE_SOURCES else root
        flag = getattr(backend, 'source_flag', flag)
        location = getattr(backend, 'source_argument', location)
        result['command']='python3 app.py '+flag+' '+shlex.quote(str(location))
    return result


def health(backends, *, demo=False, version='unknown', system='linux'):
    sources=[inspect_backend(sys,src,backend) for (sys,src),backend in sorted(backends.items())]
    present={item['source'] for item in sources if item['system']==system}
    for src in SOURCES:
        if src not in present:
            sources.append({'system':system,'source':src,'status':'not_found','path':None,'count':None,
                            'error_code':'not_configured','freshness':'unknown','last_refreshed_at':None,
                            'next_step':'演示模式未加载此来源。' if demo else '未配置或未发现此来源；已有来源仍可使用。'})
    # Never serialize the richer source rows wholesale: paths/commands can carry secrets.
    diagnostic={'schema_version':'history.diagnostic.v1','version':version,'demo':bool(demo),
                'observed_at':datetime.now(timezone.utc).isoformat(),
                'sources':[{key:item.get(key) for key in ('system','source','status','count','error_code','last_refreshed_at','freshness')} for item in sources]}
    return {'demo':bool(demo),'version':version,'sources':sources,'diagnostic':diagnostic}
