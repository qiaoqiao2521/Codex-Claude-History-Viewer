#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime
import json,sys
ROOT=Path('/home/muqiao/桌面/Codex-Claude-History-Viewer');BASE=Path('/tmp/hv-verify-oracle-wwrkfra4/verification/corrected')
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
