#!/usr/bin/env python3
"""Reproduce audit-evidence defects using only synthetic temp fixtures.
Never writes the product repository and never starts a server.
"""
from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path('/home/muqiao/桌面/Codex-Claude-History-Viewer')
HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'plans/search-hardening/evidence'


def run(name, command):
    result=subprocess.run(command,capture_output=True,text=True,cwd=HERE)
    (HERE/(name+'.stdout.txt')).write_text(result.stdout)
    (HERE/(name+'.stderr.txt')).write_text(result.stderr)
    (HERE/(name+'.result.json')).write_text(json.dumps({'command':command,'cwd':str(HERE),'exit_code':result.returncode},ensure_ascii=False,indent=2)+'\n')
    print(name, 'exit=',result.returncode)
    return result

# Save hashes so source drift remains visible when this entry point is replayed.
paths=['history_core/reuse.py','history_core/sources.py','history_core/providers.py']
paths+=['plans/search-hardening/evidence/'+n for n in ['build_fixture.py','fixture_v2.py','probe.py','manifest.json','clusters2.py']]
(HERE/'source_hashes.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},indent=2)+'\n')
for variant in ('archived','corrected'):
    base=HERE/variant
    (base/'home/.codex/sessions/2026/09/06').mkdir(parents=True,exist_ok=True)
    (base/'home/.claude/projects/proj-claude').mkdir(parents=True,exist_ok=True)
    for name in ('build_fixture.py','fixture_v2.py','probe.py','clusters2.py'):
        text=(SOURCE/name).read_text().replace('/tmp/cchv-hardening',str(base))
        text=text.replace(str(base/'mutant'),str(ROOT))
        if variant=='corrected' and name=='fixture_v2.py':
            old='    m, s = divmod(n, 60)\n    return f"2026-09-06T10:{m:02d}:{s:02d}Z"'
            new='    from datetime import datetime,timedelta,timezone\n    return (datetime(2026,9,6,10,tzinfo=timezone.utc)+timedelta(seconds=n)).isoformat().replace("+00:00","Z")'
            assert old in text
            text=text.replace(old,new)
        (base/name).write_text(text)
    (base/'manifest.json').write_bytes((SOURCE/'manifest.json').read_bytes())
    for name in ('build_fixture.py','fixture_v2.py'):
        assert run(variant+'-'+name[:-3], [sys.executable,str(base/name)]).returncode==0

inspect_template='''#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json,sys
ROOT=Path(REPO_PLACEHOLDER);BASE=Path(BASE_PLACEHOLDER)
sys.path.insert(0,str(ROOT))
from history_core.sources import Indexer,parse_codex_session_file
from history_core import reuse
file=BASE/'home/.codex/sessions/2026/09/06/rollout-2026-09-06T10-41-40-delta.jsonl'
bad=[]
for n,line in enumerate(file.read_text().splitlines(),1):
    value=json.loads(line)['timestamp']
    try:datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:bad.append({'line':n,'timestamp':value})
cache=BASE/'inspect-cache';cache.mkdir(exist_ok=True)
idx=Indexer(file.parent,cache,'codex',parse_file_fn=parse_codex_session_file,parser_version=5,recall_db_path=None)
idx.scan_sessions()
actual=[dict(row) for row in idx.conn.execute("SELECT rn,ts_ms FROM (SELECT ROW_NUMBER() OVER (ORDER BY ts_ms,id)-1 rn,ts_ms,text FROM messages WHERE session_id='delta-0001') WHERE text LIKE '%完整短语%'")]
page=reuse.search([('linux','codex',idx)],query='gammaterm1 gammaterm2',limit=20)
delta=next(i for i in page['items'] if i['id']=='delta-0001')
summary={'invalid_timestamp_count':len(bad),'first_invalid':bad[:1],'last_invalid':bad[-1:],'actual_phrase_rows':actual,'snippet_indexes':[s['message_index'] for s in delta['snippets']],'snippet_contains_phrase':any('gammaterm1 gammaterm2' in s['text'] for s in delta['snippets']),'hardcoded_2106_check_reports_excluded':not any(s['message_index']==2106 for s in delta['snippets'])}
print(json.dumps(summary,ensure_ascii=False,indent=2))
idx.conn.close()
'''
for variant in ('archived','corrected'):
    base=HERE/variant
    entry=HERE/(variant+'-inspect.py')
    entry.write_text(inspect_template.replace('REPO_PLACEHOLDER',repr(str(ROOT))).replace('BASE_PLACEHOLDER',repr(str(base))))
    run(variant+'-inspect',[sys.executable,str(entry)])
    run(variant+'-probe',[sys.executable,str(base/'probe.py'),str(ROOT),str(base/'probe-cache')])
    run(variant+'-clusters2',[sys.executable,str(base/'clusters2.py')])

mutant_template='''#!/usr/bin/env python3
from pathlib import Path
import runpy,sys
ROOT=Path(REPO_PLACEHOLDER);BASE=Path(BASE_PLACEHOLDER)
sys.path.insert(0,str(ROOT))
from history_core import reuse
MUTATION_PLACEHOLDER
sys.argv=[str(BASE/'probe.py'),str(ROOT),str(BASE/'CACHE_PLACEHOLDER')]
try:
    runpy.run_path(str(BASE/'probe.py'),run_name='__main__')
except SystemExit as exc:
    print('INJECTED_MUTATION: '+DESCRIPTION_PLACEHOLDER+'; PROBE_EXIT='+str(exc.code))
    raise
'''
mutations={
'four-broken-returns':('''original=reuse.search
def damaged(*args,**kw):
    r=original(*args,**kw)
    if kw['query']=='claudedistinct':
        r['items'][0]['source']='codex';r['items'][0]['store_id']='wrong-store'
    if kw['query']=='tailneedle':
        r['items'][0]['snippets'][0]['text']='WRONG unrelated text'
    if kw['query']=='betatitle':
        r['items'][0]['snippet_status']='query_budget_exceeded'
    if kw['query']=='双千兆':
        r['errors']=[{'source':'codex','error':'source_unavailable'}];r['partial']=True
    return r
reuse.search=damaged''','wrong source/store, wrong excerpt body, wrong metadata status, unexpected errors/partial'),
'underscore-unescaped':("old=reuse._escape_sql_like\nreuse._escape_sql_like=lambda value:old(value).replace(chr(92)+'_','_')\nassert reuse._escape_sql_like('_') == '_'\nprint('CONFIRMED_UNDERSCORE_PATTERN',repr(reuse._escape_sql_like('_')))",'SQL LIKE underscore escape removed')}
for name,(mutation,description) in mutations.items():
    entry=HERE/(name+'.py')
    script=mutant_template.replace('REPO_PLACEHOLDER',repr(str(ROOT))).replace('BASE_PLACEHOLDER',repr(str(HERE/'corrected'))).replace('MUTATION_PLACEHOLDER',mutation).replace('CACHE_PLACEHOLDER',name+'-cache').replace('DESCRIPTION_PLACEHOLDER',repr(description))
    entry.write_text(script)
    run(name,[sys.executable,str(entry)])
