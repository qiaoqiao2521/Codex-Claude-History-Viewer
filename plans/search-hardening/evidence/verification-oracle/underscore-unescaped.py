#!/usr/bin/env python3
from pathlib import Path
import runpy,sys
ROOT=Path('/home/muqiao/桌面/Codex-Claude-History-Viewer');BASE=Path('/tmp/hv-verify-oracle-wwrkfra4/verification/corrected')
sys.path.insert(0,str(ROOT))
from history_core import reuse
old=reuse._escape_sql_like
reuse._escape_sql_like=lambda value:old(value).replace(chr(92)+'_','_')
assert reuse._escape_sql_like('_') == '_'
print('CONFIRMED_UNDERSCORE_PATTERN',repr(reuse._escape_sql_like('_')))
sys.argv=[str(BASE/'probe.py'),str(ROOT),str(BASE/'underscore-unescaped-cache')]
try:
    runpy.run_path(str(BASE/'probe.py'),run_name='__main__')
except SystemExit as exc:
    print('INJECTED_MUTATION: '+'SQL LIKE underscore escape removed'+'; PROBE_EXIT='+str(exc.code))
    raise
