"""Synthetic evidence-only replay: no real history or network access."""
import json
import tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from history_core import query_activity

def main():
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);source=root/'sessions';source.mkdir()
        rows=[dict(type='session_meta',timestamp='2026-09-29T12:00:00Z',payload=dict(id='fixture',cwd='/synthetic/project'))]
        for i in range(12):
            role='user' if i==0 else 'assistant'
            text='STILL IN PROGRESS' if i==0 else 'record '+str(i)
            if i==11:text='B'*2300+'BODY END'
            rows.append(dict(type='response_item',timestamp=f'2026-09-29T12:00:{i:02d}Z',payload=dict(type='message',role=role,content=[dict(type='input_text',text=text)])))
        (source/'fixture.jsonl').write_text('\n'.join(json.dumps(x) for x in rows))
        def query(**args):
            return query_activity({'codex':source},date='2026-09-29',timezone='Asia/Shanghai',data_dir=root/'cache',**args)['sources'][0]
        first=query(refresh=True,evidence_limit=8);item=first['items'][0]
        assert 'STILL IN PROGRESS' not in json.dumps(item['evidence'])
        assert item['next_message_offset']==8
        expanded=query(session_id='fixture',evidence_limit=8,message_offset=8,revisions={'codex':first['index_revision']})
        assert 'STILL IN PROGRESS' in json.dumps(expanded['items'][0]['evidence'])
        tail=item['evidence'][-1]
        body=query(session_id='fixture',message_index=tail['message_index'],text_offset=tail['next_text_offset'],revisions={'codex':first['index_revision']})
        assert 'BODY END' in json.dumps(body)
        assert datetime.fromtimestamp(tail['timestamp_ms']/1000,ZoneInfo('Asia/Shanghai')).isoformat()=='2026-09-29T20:00:11+08:00'
        from unittest.mock import patch
        from history_core import activity
        original=activity._manifest
        calls=[]
        def append_after_scan(root_path,source_name):
            calls.append(1)
            if len(calls)==2:
                with (source/'fixture.jsonl').open('a') as stream:stream.write('\n')
            return original(root_path,source_name)
        with patch('history_core.activity._manifest',side_effect=append_after_scan):
            concurrent=query(refresh=True)
        assert concurrent['coverage']['freshness']=='stale'
        assert concurrent['coverage']['indexed'] is True
        assert concurrent['items'][0]['window_message_count']==12
        missing=query_activity({'mcode':root/'missing'},date='2026-09-29',timezone='Asia/Shanghai',data_dir=root/'cache')
        assert missing['partial'] is True
        assert missing['sources'][0]['coverage']['reason']=='source_not_found'
        assert 'Traceback' not in json.dumps(missing)
        print(json.dumps({'recent_eight_is_partial':True,'earlier_intent_recovered_by_existing_pagination':True,'long_body_recovered_by_existing_text_pagination':True,'local_day_and_timestamp_correct':True,'concurrent_change_keeps_indexed_evidence_with_stale_disclosure':True,'missing_selected_source_disclosed_without_traceback':True}))

if __name__=='__main__':main()
