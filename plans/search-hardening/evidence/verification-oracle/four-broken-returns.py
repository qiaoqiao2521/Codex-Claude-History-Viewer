#!/usr/bin/env python3
from pathlib import Path
import runpy,sys
ROOT=Path('/home/muqiao/桌面/Codex-Claude-History-Viewer');BASE=Path('/tmp/hv-verify-oracle-wwrkfra4/verification/corrected')
sys.path.insert(0,str(ROOT))
from history_core import reuse
original=reuse.search
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
reuse.search=damaged
sys.argv=[str(BASE/'probe.py'),str(ROOT),str(BASE/'four-broken-returns-cache')]
try:
    runpy.run_path(str(BASE/'probe.py'),run_name='__main__')
except SystemExit as exc:
    print('INJECTED_MUTATION: '+'wrong source/store, wrong excerpt body, wrong metadata status, unexpected errors/partial'+'; PROBE_EXIT='+str(exc.code))
    raise
