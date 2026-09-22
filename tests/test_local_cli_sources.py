"""Source expansion contracts: real adapters, isolated synthetic histories."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlencode
from unittest.mock import patch

from history_core import HistoryReader, service, reuse
from history_core.sources import Indexer
from history_core.providers import parser_for, include_file, opencode_database, copilot_root
from history_core.evidence import selection_bundle, raw_record
from history_core.diagnostics import optional_missing_source
from test_agy import blob as agy_blob, step as agy_step


def seed_sources(root):
    ts = '2026-09-22T00:00:00Z'
    rows = {
        'codebuddy': [
            {'sessionId':'cbc-fixture','cwd':'/fixture/repo','type':'message','id':'u','timestamp':ts,'role':'user','content':[{'type':'input_text','text':'localneedle repair'}]},
            {'sessionId':'cbc-fixture','type':'message','id':'a','timestamp':ts,'role':'assistant','content':[{'type':'output_text','text':'localneedle remains'}]}],
        'pi': [
            {'type':'session','version':3,'id':'pi-fixture','cwd':'/fixture/repo','timestamp':ts},
            {'type':'message','id':'u','parentId':None,'timestamp':ts,'message':{'role':'user','content':[{'type':'text','text':'localneedle repair'}],'timestamp':ts}},
            {'type':'message','id':'a','parentId':'u','timestamp':ts,'message':{'role':'assistant','content':[{'type':'text','text':'localneedle remains'}],'timestamp':ts,'usage':{'input':10,'output':2,'cacheRead':3,'totalTokens':15}}}],
        'copilot': [
            {'type':'session.start','id':'s','timestamp':ts,'data':{'sessionId':'copilot-fixture','context':{'cwd':'/fixture/repo'}}},
            {'type':'user.message','id':'u','timestamp':ts,'data':{'content':'localneedle repair'}},
            {'type':'assistant.message','id':'a','timestamp':ts,'data':{'content':'localneedle remains'}}],
    }
    locations = {}
    for source, records in rows.items():
        folder = root / source / ('projects' if source == 'codebuddy' else 'session-state/copilot-fixture' if source == 'copilot' else 'sessions/project')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ('events.jsonl' if source == 'copilot' else source+'-fixture.jsonl')
        path.write_text(''.join(json.dumps(x)+'\n' for x in records))
        locations[source] = (root/source/('projects' if source=='codebuddy' else 'session-state' if source=='copilot' else 'sessions'), path)
    folder = root/'gemini/tmp/hash/chats'; folder.mkdir(parents=True, exist_ok=True)
    path = folder/'session-fixture.json'
    path.write_text(json.dumps({'sessionId':'gemini-fixture','projectHash':'hash','startTime':ts,'lastUpdated':ts,
                               'messages':[{'id':'u','type':'user','timestamp':ts,'content':'localneedle repair'},
                                           {'id':'a','type':'gemini','timestamp':ts,'content':'localneedle remains','tokens':{'input':10,'output':2,'cached':3,'total':12}}]}, indent=2))
    locations['gemini'] = (root/'gemini/tmp', path)
    return locations


class LocalCliSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.locations = seed_sources(self.root)

    def test_machine_refresh_search_handoff_source_identity_and_unchanged_bytes(self):
        for source, (folder, path) in self.locations.items():
            with self.subTest(source=source):
                original = path.read_bytes()
                with HistoryReader('cbc' if source=='codebuddy' else source, folder, self.root/'cache') as reader:
                    reader.refresh()
                    rows = reader.search(query='localneedle')['items']
                    self.assertEqual(len(rows),1)
                    data = reader.handoff(rows[0]['id'])
                    self.assertEqual(data['authorization'],'context_only')
                    self.assertTrue(data['payload']['session'].startswith(source+':'))
                    self.assertIn('localneedle', data['standard'])
                    self.assertEqual(data['payload']['provenance']['content_revision'], 'sha256:'+hashlib.sha256(original).hexdigest())
                    if source=='pi': self.assertNotEqual(data['payload']['status'],'completed')
                self.assertEqual(path.read_bytes(), original)

    def test_cross_source_search_selection_and_exact_json_evidence(self):
        sources=[]
        for source,(folder,path) in self.locations.items():
            idx=Indexer(folder,self.root,source,db_filename=source+'.sqlite',parse_file_fn=parser_for(source),file_filter_fn=lambda p,s=source:include_file(s,p))
            self.addCleanup(idx.conn.close);idx.scan_sessions();sources.append(('linux',source,idx))
        found=reuse.search(sources,query='localneedle')
        self.assertEqual({x['source'] for x in found['items']},set(self.locations))
        self.assertEqual(reuse.search(sources,query='localneedle',source='cbc')['items'][0]['source'],'codebuddy')
        for system,source,idx in sources:
            sid=idx.query_sessions()[0]['id']
            audit,handoff=service.audit_handoff(idx,sid)
            rev=handoff['payload']['provenance']['content_revision']
            bundle=selection_bundle(sources,[{'system':system,'source':source,'session_id':sid,'message_index':0,'content_revision':rev}])
            self.assertIn('localneedle',bundle['markdown'])
            evidence=next(x for x in audit['evidence'] if x['type']=='user_prompt')
            raw=raw_record(idx,sid,{'content_revision':rev},evidence_id=evidence['id'])
            self.assertIn('localneedle',raw['text'])
            if source=='gemini':
                self.assertEqual(raw['json_pointer'],'/messages/0')
                self.assertEqual(json.loads(raw['text'])['id'],'u')

    def test_gemini_migration_shadow_and_subagent_discovery(self):
        folder,path=self.locations['gemini']
        self.assertTrue(include_file('gemini',path))
        path.with_suffix('.jsonl').write_text('{}\n')
        self.assertFalse(include_file('gemini',path))
        self.assertTrue(include_file('gemini',path.parent/'parent-id'/'child-id.jsonl'))
        self.assertFalse(include_file('gemini',folder/'settings.json'))

    def test_complete_materialization_required_for_handoff(self):
        folder,path=self.locations['gemini']
        with HistoryReader('gemini',folder,self.root/'cache') as reader:
            reader.refresh()
            with patch('history_core.provenance.MAX_SOURCE_BYTES', 100):
                with self.assertRaisesRegex(ValueError,'handoff_source_limit_exceeded'):
                    reader.handoff('gemini-fixture')

    def test_opencode_xdg_and_explicit_missing_root(self):
        with patch.dict(os.environ,{'XDG_DATA_HOME':str(self.root/'xdg')}):
            self.assertEqual(opencode_database(),self.root/'xdg/opencode/opencode.db')
            self.assertEqual(opencode_database(self.root/'missing.db'),self.root/'missing.db')

    def test_copilot_snap_discovery_and_regular_precedence(self):
        with patch('history_core.providers.Path.home',return_value=self.root):
            snap=self.root/'snap/copilot-cli/common/.copilot';(snap/'session-state').mkdir(parents=True)
            self.assertEqual(copilot_root(),snap)
            (self.root/'.copilot/session-state').mkdir(parents=True)
            self.assertEqual(copilot_root(),self.root/'.copilot')

    def test_prime_has_distinct_identity_and_cache_from_pi(self):
        folder,_=self.locations['pi']
        with HistoryReader('prime-agent',folder,self.root/'cache') as reader:
            reader.refresh()
            self.assertEqual(reader.handoff('pi-fixture')['payload']['session'],'prime:pi-fixture')

    def test_optional_discovery_never_hides_permissions_cache_or_previous_success(self):
        missing = self.root/'missing'
        backend = SimpleNamespace(optional_discovery=True,last_refreshed_at=None,
                                  sessions_dir=missing,indexer=None)
        self.assertTrue(optional_missing_source(backend))
        backend.optional_discovery = False
        self.assertFalse(optional_missing_source(backend))
        backend.optional_discovery = True
        backend.last_refreshed_at = '2026-09-22T00:00:00Z'
        self.assertFalse(optional_missing_source(backend))
        backend.last_refreshed_at = None
        with patch('history_core.diagnostics.Path.stat',side_effect=PermissionError('fixture')):
            self.assertFalse(optional_missing_source(backend))
        missing.mkdir()
        self.assertFalse(optional_missing_source(backend))
        missing.rmdir()
        folder, _ = self.locations['pi']
        idx = Indexer(folder,self.root,'pi',parse_file_fn=parser_for('pi'))
        self.addCleanup(idx.conn.close)
        backend.indexer = idx
        self.assertTrue(optional_missing_source(backend))
        idx.scan_sessions()
        self.assertFalse(optional_missing_source(backend))
        idx.conn.execute('DROP TABLE sessions')
        self.assertFalse(optional_missing_source(backend))


def seed_native_database(path, source):
    """ZCode's session table omits usage; its assistant message has it instead."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT,
            slug TEXT, directory TEXT, title TEXT, version TEXT, share_url TEXT,
            summary_additions INTEGER, summary_deletions INTEGER, summary_files INTEGER,
            summary_diffs TEXT, time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
            sequence INTEGER, data TEXT);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
            time_created INTEGER, sequence INTEGER, data TEXT);
        CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, name TEXT);
    ''')
    if source == 'opencode':
        for field, kind in [('agent','TEXT'),('model','TEXT'),('cost','REAL')]+[
                (name,'INTEGER') for name in ('tokens_input','tokens_output','tokens_reasoning','tokens_cache_read','tokens_cache_write')]:
            conn.execute('ALTER TABLE session ADD COLUMN '+field+' '+kind)
    sid = source + '-fixture'
    conn.execute('INSERT INTO session (id,project_id,directory,title,time_created,time_updated) VALUES (?,?,?,?,?,?)',
                 (sid,'fixture','/fixture/repo',source+' localneedle fixture',1790035200000,1790035201000))
    for n, role in enumerate(('user','assistant')):
        mid = source + '-' + role
        native = {'role':role, 'modelID':'fixture-model'}
        if role == 'assistant':
            native.update(cost=0.01,tokens={'input':10,'output':2,'reasoning':0,'cache':{'read':3,'write':0}})
        conn.execute('INSERT INTO message VALUES (?,?,?,?,?)',(mid,sid,1790035200000+n,n,json.dumps(native)))
        conn.execute('INSERT INTO part VALUES (?,?,?,?,?,?)',
                     (mid+'-text',mid,sid,1790035200000+n,n,json.dumps({'type':'text','text':'localneedle '+role})))
    conn.commit()
    conn.close()


def seed_agy_store(summary_path):
    """Explicit protobuf fixtures; opaque legacy/unknown bytes never become text."""
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    conversations = summary_path.parent/'conversations'; conversations.mkdir()
    rows = {
        'decoded-fixture':[(14,3,0,agy_step(14,agy_blob(1,'agymarker decoded body')))],
        'partial-fixture':[(14,3,0,agy_step(14,agy_blob(1,'agymarker partial body'))),
                           (999,3,0,agy_step(999,agy_blob(1,'OPAQUE-UNKNOWN-MUST-NOT-BE-SEARCHABLE')))],
        'legacy-fixture':None,
    }
    paths = {}
    with sqlite3.connect(summary_path) as db:
        db.execute('CREATE TABLE conversation_summaries(conversation_id TEXT PRIMARY KEY,title TEXT,step_count INTEGER,'
                   'last_modified_time TEXT,workspace_uris TEXT)')
        for sid, steps in rows.items():
            db.execute('INSERT INTO conversation_summaries VALUES(?,?,?,?,?)',
                       (sid,'agymarker '+sid,len(steps or []),'2026-09-22T00:00:00Z',json.dumps(['file:///fixture/agy'])))
            path = conversations/(sid+('.pb' if steps is None else '.db'))
            paths[sid] = path
            if steps is None:
                path.write_bytes(b'OPAQUE-LEGACY-MUST-NOT-BE-SEARCHABLE')
                continue
            with sqlite3.connect(path) as transcript:
                transcript.execute('CREATE TABLE steps(idx INTEGER PRIMARY KEY,step_type INTEGER,status INTEGER,step_format INTEGER,step_payload BLOB)')
                transcript.executemany('INSERT INTO steps VALUES(?,?,?,?,?)',[(n,*step) for n,step in enumerate(steps)])
    return paths


class LocalCliBootHttpTests(unittest.TestCase):
    """Boot the production entry point under fake HOME, never developer histories.

    An allowlisted temporary app copy also prevents the legacy Hermes sibling
    fallback from discovering a real checkout next to the developer repository.
    """
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root/'home'; self.home.mkdir()
        self.app_root = self.root/'app'; self.app_root.mkdir()
        repository = Path(__file__).resolve().parents[1]
        for name in ('app.py','VERSION'):
            shutil.copy2(repository/name, self.app_root/name)
        for name in ('history_core','audit','static','demo'):
            shutil.copytree(repository/name, self.app_root/name, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        seeded = seed_sources(self.root/'seed')
        destinations = {'codebuddy':'.codebuddy/projects','gemini':'.gemini/tmp',
                        'pi':'.pi/agent/sessions','copilot':'snap/copilot-cli/common/.copilot/session-state'}
        self.paths = {}
        for source, (folder,path) in seeded.items():
            target = self.home/destinations[source]
            shutil.copytree(folder,target)
            self.paths[source] = target/path.relative_to(folder)
        prime = self.home/'.prime/agent/sessions/fixture/prime.jsonl'
        prime.parent.mkdir(parents=True)
        prime.write_bytes(self.paths['pi'].read_bytes().replace(b'pi-fixture',b'prime-fixture'))
        self.paths['prime'] = prime
        for source, suffix in [('zcode','.zcode/cli/db/db.sqlite'),('opencode','.local/share/opencode/opencode.db')]:
            self.paths[source] = self.home/suffix
            seed_native_database(self.paths[source],source)
        self.original = {path:path.read_bytes() for path in self.paths.values()}
        self.env = {key:value for key,value in os.environ.items() if not (
            key.startswith(('CODEBUDDY_','GEMINI_','PI_','PRIME_','XDG_','PYTHON')) or key in ('CODEX_HOME','CLAUDE_CONFIG_DIR'))}
        self.env.update(HOME=str(self.home),XDG_DATA_HOME=str(self.home/'.local/share'),
                        XDG_CONFIG_HOME=str(self.home/'.config'),PYTHONDONTWRITEBYTECODE='1')
        self.process = None
        self.addCleanup(self.stop)

    def start(self, *args):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
        self.url = 'http://127.0.0.1:'+str(port)
        self.log = (self.root/'server.log').open('w+')
        self.process = subprocess.Popen([sys.executable,'app.py','--host','127.0.0.1','--port',str(port),
            '--no-wsl','--scan-interval','3600','--data-dir',str(self.root/'cache'),*args],
            cwd=self.app_root,env=self.env,stdout=self.log,stderr=subprocess.STDOUT)
        deadline = time.monotonic()+10
        while time.monotonic()<deadline:
            if self.process.poll() is not None:
                self.log.seek(0); self.fail('isolated app exited: '+self.log.read())
            try:
                status, data = self.request('/api/reuse/health')
                if status == 200:
                    return data
            except (OSError,urllib.error.URLError):
                pass
            time.sleep(0.05)
        self.fail('isolated HTTP server did not become ready')

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
            self.log.close()
            self.process = None

    def request(self, path, payload=None):
        req = urllib.request.Request(self.url+path,
            data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=3) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as exc:
            with exc: return exc.code,json.load(exc)

    def test_default_discovery_search_projects_messages_and_diagnostics(self):
        report = self.start()
        health = {item['source']:item for item in report['sources']}
        for source in self.paths:
            with self.subTest(source=source):
                self.assertEqual(health[source]['status'],'ready',health[source])
                self.assertEqual(health[source]['count'],1)
                status, result = self.request('/api/reuse/search?'+urlencode({'q':'localneedle','source':source}))
                self.assertEqual(status,200)
                self.assertEqual(len(result['items']),1,result)
                item = result['items'][0]
                self.assertEqual(item['source'],source)
                self.assertTrue(item['snippets'])
                route = '/api/linux/'+source+'/session/'+item['id']+'/messages?'+urlencode({'source_revision':item['source_revision']})
                self.assertEqual(self.request(route)[0],200)
        status, result = self.request('/api/reuse/projects')
        self.assertEqual(status,200)
        bound = next(item for item in result['items'] if item['project']=='/fixture/repo')
        self.assertEqual({item['source'] for item in bound['sources']},set(self.paths)-{'gemini'},result)
        self.assertEqual(bound['session_count'],6)
        self.assertNotIn('cbc',health)
        self.assertNotIn('prime-agent',health)
        diagnostic = json.dumps(report['diagnostic'])
        for forbidden in (str(self.home),'localneedle','fixture-model'):
            self.assertNotIn(forbidden,diagnostic)
        self.stop()
        for path, original in self.original.items():
            self.assertEqual(path.read_bytes(),original)

    def test_revision_bound_http_selection_and_gemini_json_pointer(self):
        self.start()
        for source in ('codebuddy','gemini','pi','prime','copilot'):
            with self.subTest(source=source):
                _, found = self.request('/api/reuse/search?'+urlencode({'source':source,'q':'localneedle'}))
                sid = found['items'][0]['id']
                query = {'system':'linux','source':source,'session':sid}
                status, item = self.request('/api/reuse/evidence?'+urlencode(query))
                self.assertEqual(status,200)
                self.assertEqual(item['provenance']['status'],'captured')
                ref = item['evidence'][0]  # First explicit user prompt in each fixture.
                binding = {'content_revision':item['provenance']['content_revision']}
                status, raw = self.request('/api/reuse/raw?'+urlencode(dict(query,**binding,evidence_id=ref['id'])))
                self.assertEqual(status,200)
                if source == 'gemini':
                    self.assertEqual(raw['json_pointer'],'/messages/0')
                    self.assertEqual(json.loads(raw['text'])['id'],'u')
                else:
                    self.assertEqual(raw['text'],self.paths[source].read_text().splitlines()[raw['line_no']-1])
                selected = dict(query,**binding,session_id=sid,message_index=found['items'][0]['snippets'][0]['message_index'])
                status, bundle = self.request('/api/reuse/selection',{'selections':[selected]})
                self.assertEqual(status,200,bundle)
                self.assertEqual(bundle['items'][0]['source'],source)
                self.assertIn('localneedle',bundle['markdown'])
                with self.paths[source].open('ab') as stream: stream.write(b'\n')
                status, stale = self.request('/api/reuse/selection',{'selections':[selected]})
                self.assertEqual(status,409,stale)
                self.assertEqual(stale['error'],'selection_stale')
                self.assertEqual(self.request('/api/reuse/refresh',{'system':'linux','source':source})[0],200)
                self.assertEqual(self.request('/api/reuse/selection',{'selections':[selected]})[0],409)
                stale_link = '/api/linux/'+source+'/session/'+sid+'/messages?'+urlencode(
                    {'source_revision':found['items'][0]['source_revision']})
                self.assertEqual(self.request(stale_link)[0],409)

    def test_demo_ignores_source_environment_and_explicit_native_paths(self):
        agy = self.home/'.gemini/antigravity-cli/conversation_summaries.db'
        desktop = self.home/'.gemini/antigravity/conversation_summaries.db'
        for summary in (agy,desktop):
            paths = seed_agy_store(summary)
            self.original.update({path:path.read_bytes() for path in (summary,*paths.values())})
        self.env.update(CODEBUDDY_CONFIG_DIR=str(self.home/'.codebuddy'),GEMINI_CLI_HOME=str(self.home/'.gemini'),
            PI_CODING_AGENT_DIR=str(self.home/'.pi/agent'),PI_CODING_AGENT_SESSION_DIR=str(self.paths['pi'].parent),
            PRIME_AGENT_CODING_AGENT_DIR=str(self.home/'.prime/agent'),PRIME_AGENT_SESSION_DIR=str(self.paths['prime'].parent))
        report = self.start('--demo','--zcode-state-db',str(self.paths['zcode']),
                            '--opencode-state-db',str(self.paths['opencode']),
                            '--agy-state-db',str(agy),'--antigravity-state-db',str(desktop),
                            '--copilot-dir',str(self.paths['copilot'].parents[2]))
        self.assertTrue(report['demo'])
        status, found = self.request('/api/reuse/search?q=localneedle')
        self.assertEqual(status,200)
        self.assertEqual(found['items'],[],found)
        self.assertEqual(self.request('/api/reuse/search?q=agymarker')[1]['items'],[])
        for item in report['sources']:
            if item.get('path'):
                self.assertTrue(Path(item['path']).is_relative_to(self.app_root/'demo'),item)
        status, sources = self.request('/api/sources')
        self.assertEqual(status,200)
        self.assertFalse({'opencode','zcode','hermes','agy','antigravity'} & {item['source'] for item in sources['sources']})
        self.stop()
        for path, original in self.original.items():
            self.assertEqual(path.read_bytes(),original)
        self.assertTrue((self.root/'cache/demo-isolated').is_dir())

    def test_absent_unconfigured_sources_do_not_poison_search_pagination(self):
        shutil.rmtree(self.home/'.prime')
        report = self.start()
        by_source = {item['source']:item for item in report['sources']}
        self.assertEqual(by_source['prime']['status'],'not_found')
        self.assertEqual(by_source['agy']['status'],'not_found')
        self.assertEqual(by_source['antigravity']['status'],'not_found')
        status, page = self.request('/api/reuse/search?q=localneedle&limit=1')
        self.assertEqual(status,200)
        self.assertFalse(page['partial'],page)
        self.assertEqual(page['errors'],[])
        self.assertTrue(page['next_cursor'])
        status, second = self.request('/api/reuse/search?'+urlencode(
            {'q':'localneedle','limit':1,'cursor':page['next_cursor']}))
        self.assertEqual(status,200,second)
        self.assertNotEqual(page['items'][0]['source'],second['items'][0]['source'])

    def test_explicit_missing_source_is_partial(self):
        missing = self.home/'explicit-missing-pi'
        self.start('--pi-dir',str(missing))
        status, page = self.request('/api/reuse/search?q=localneedle&limit=1')
        self.assertEqual(status,200)
        self.assertTrue(page['partial'])
        self.assertIn('pi',{item['source'] for item in page['errors']})
        self.assertIsNone(page['next_cursor'])

    def test_source_disappearing_after_successful_scan_stays_partial(self):
        report = self.start()
        self.assertEqual(next(item for item in report['sources'] if item['source']=='pi')['status'],'ready')
        shutil.rmtree(self.home/'.pi')
        self.request('/api/reuse/refresh',{'system':'linux','source':'pi'})
        status, page = self.request('/api/reuse/search?q=localneedle&limit=1')
        self.assertEqual(status,200)
        self.assertTrue(page['partial'])
        self.assertIn('pi',{item['source'] for item in page['errors']})
        self.assertIsNone(page['next_cursor'])

    def test_explicit_missing_environment_source_is_partial(self):
        self.env['PRIME_AGENT_SESSION_DIR'] = str(self.home/'missing-explicit-sessions')
        self.start()
        status, page = self.request('/api/reuse/search?q=localneedle')
        self.assertEqual(status,200)
        self.assertTrue(page['partial'])
        self.assertIn('prime',{item['source'] for item in page['errors']})

    def test_missing_source_with_retained_cache_is_partial_after_process_restart(self):
        self.start()
        self.stop()
        shutil.rmtree(self.home/'.pi')
        self.start()
        status, page = self.request('/api/reuse/search?q=localneedle')
        self.assertEqual(status,200)
        self.assertTrue(page['partial'])
        self.assertIn('pi',{item['source'] for item in page['errors']})

    def test_codebuddy_file_history_keeps_native_raw_and_failure_status(self):
        records = [
            {'type':'function_call','id':'edit-row','callId':'edit-call','name':'Edit',
             'arguments':json.dumps({'file_path':'src/a.py','old_string':'old-value','new_string':'new-value'})},
            {'type':'function_call_result','id':'edit-result','callId':'edit-call','name':'Edit',
             'status':'completed','output':{'type':'text','text':'Permission denied'},
             'providerData':{'toolResult':{'error':'permission denied'}}}]
        with self.paths['codebuddy'].open('a') as stream:
            for record in records:
                stream.write(json.dumps(dict(record,sessionId='cbc-fixture',cwd='/fixture/repo',timestamp='2026-09-22T00:00:02Z'))+'\n')
        self.start()
        status, page = self.request('/api/reuse/timeline?'+urlencode({'project':'/fixture/repo','file':'src/a.py'}))
        self.assertEqual(status,200)
        item = next(entry for entry in page['items'] if entry['source']=='codebuddy')
        self.assertEqual(item['diff_status'],'available')
        change = item['file_changes'][0]
        self.assertEqual(change['status'],'failed')
        self.assertEqual(change['current_file_status'],'unknown')
        self.assertIn('-old-value',change['diff'])
        self.assertIn('+new-value',change['diff'])
        status, raw = self.request('/api/reuse/raw?'+urlencode({'system':'linux','source':'codebuddy',
            'session':'cbc-fixture','line_no':change['raw_ref']['line_no'],
            'content_revision':item['provenance']['content_revision']}))
        self.assertEqual(status,200)
        self.assertEqual(json.loads(raw['text'])['type'],'function_call')
        self.assertEqual(json.loads(raw['text'])['callId'],'edit-call')

    def test_usage_http_deduplicates_native_updates_without_adding_cache_twice(self):
        cbc = {'type':'message','sessionId':'cbc-fixture','role':'assistant','content':[{'type':'output_text','text':'usage fixture'}],
               'timestamp':'2026-09-22T00:00:03Z','providerData':{'messageId':'same-provider-message'},
               'message':{'usage':{'input_tokens':10,'output_tokens':2,'cache_read_input_tokens':3,'total_tokens':12}}}
        with self.paths['codebuddy'].open('a') as stream:
            for row_id in ('partial','final'):
                stream.write(json.dumps(dict(cbc,id=row_id))+'\n')
        pi_lines = self.paths['pi'].read_bytes().splitlines()
        with self.paths['pi'].open('ab') as stream: stream.write(pi_lines[-1]+b'\n')
        gemini = json.loads(self.paths['gemini'].read_text())
        gemini['messages'].append(dict(gemini['messages'][-1]))
        self.paths['gemini'].write_text(json.dumps(gemini))
        self.start()
        for source, expected in (('codebuddy',12),('gemini',12),('pi',15),('prime',15),('zcode',12)):
            with self.subTest(source=source):
                status, usage = self.request('/api/linux/'+source+'/usage')
                self.assertEqual(status,200)
                self.assertEqual(usage['totals']['total'],expected,usage)
                self.assertEqual(usage['totals']['cached'],3)

    def test_agy_default_discovery_memory_index_coverage_and_pagination(self):
        for source, folder in (('agy','antigravity-cli'),('antigravity','antigravity')):
            seed_agy_store(self.home/'.gemini'/folder/'conversation_summaries.db')
        originals = {path:path.read_bytes() for path in (self.home/'.gemini').rglob('*') if path.is_file()}
        report = self.start()
        for source in ('agy','antigravity'):
            with self.subTest(source=source):
                source_health = next(item for item in report['sources'] if item['source']==source)
                self.assertEqual(source_health['status'],'partial')
                self.assertEqual(source_health['count'],3)
                self.assertEqual(source_health['content_coverage'],
                    {'decoded_text':1,'partial_unsupported_steps':1,'unsupported_legacy_protobuf':1})
                items, cursor = [], None
                for _ in range(3):
                    query = {'q':'agymarker','source':source,'limit':1}
                    if cursor: query['cursor'] = cursor
                    status, page = self.request('/api/reuse/search?'+urlencode(query))
                    self.assertEqual(status,200,page)
                    self.assertTrue(page['partial'])
                    self.assertEqual(page['errors'],[])
                    self.assertEqual(page['pagination_status'],'available')
                    self.assertEqual(page['content_warnings'],[{'system':'linux','source':source,'incomplete_sessions':2}])
                    items.extend(page['items'])
                    cursor = page['next_cursor']
                    if len(items)<3: self.assertTrue(cursor)
                self.assertIsNone(cursor)
                self.assertEqual({item['id'] for item in items},{'decoded-fixture','partial-fixture','legacy-fixture'})
                self.assertEqual({item['content_status'] for item in items},
                    {'decoded_text','partial_unsupported_steps','unsupported_legacy_protobuf'})
                for item in items:
                    status, messages = self.request('/api/linux/'+source+'/session/'+item['id']+'/messages?'+urlencode(
                        {'source_revision':item['source_revision']}))
                    self.assertEqual(status,200,messages)
                    self.assertNotIn('OPAQUE-',json.dumps(messages))
                status, hidden = self.request('/api/reuse/search?'+urlencode({'q':'OPAQUE-','source':source}))
                self.assertEqual(status,200)
                self.assertEqual(hidden['items'],[])
        status, projects = self.request('/api/reuse/projects')
        self.assertEqual(status,200)
        project = next(item for item in projects['items'] if item['project']=='/fixture/agy')
        self.assertEqual(project['session_count'],6)
        self.assertEqual({item['source'] for item in project['sources']},{'agy','antigravity'})
        self.assertEqual(projects['errors'],[])
        self.stop()
        for path, original in originals.items(): self.assertEqual(path.read_bytes(),original)

    def test_agy_raw_change_rejects_cached_search_reader_pages_and_http_deep_links(self):
        summary = self.home/'.gemini/antigravity-cli/conversation_summaries.db'
        paths = seed_agy_store(summary)
        self.start()
        status, page = self.request('/api/reuse/search?'+urlencode({'q':'agymarker','source':'agy','limit':1}))
        self.assertEqual(status,200)
        item = page['items'][0]
        suffix = '?'+urlencode({'source_revision':item['source_revision']})
        routes = ['/api/linux/agy/session/'+item['id']+ending+suffix for ending in ('','/messages','/message/0')]
        for route in routes: self.assertEqual(self.request(route)[0],200)
        summary_before = summary.read_bytes()
        with HistoryReader('agy',summary) as reader:
            first = reader.search(query='agymarker',limit=1)
            with sqlite3.connect(paths['decoded-fixture']) as db:
                db.execute('UPDATE steps SET step_payload=? WHERE idx=0',
                           (agy_step(14,agy_blob(1,'changed-source-marker')),))
            self.assertEqual(summary.read_bytes(),summary_before,'Only a conversation changed; summary DB is unchanged')
            with self.assertRaisesRegex(ValueError,'source_changed_since_index'):
                reader.search(query='agymarker')
            with self.assertRaisesRegex(ValueError,'source_changed_since_index'):
                reader.search(query='agymarker',offset=1,index_revision=first['index_revision'])
            for route in routes:
                status, stale = self.request(route)
                self.assertEqual(status,409,stale)
                self.assertEqual(stale['error'],'index_revision_changed')
            status, stale_search = self.request('/api/reuse/search?q=agymarker&source=agy')
            self.assertEqual(status,200)
            self.assertEqual(stale_search['items'],[])
            self.assertIn('source_changed_since_index',{error['error'] for error in stale_search['errors']})
            self.assertEqual(self.request('/api/reuse/search?'+urlencode(
                {'q':'agymarker','source':'agy','limit':1,'cursor':page['next_cursor']}))[0],409)
            reader.refresh()
            self.assertEqual(len(reader.search(query='changed-source-marker')['items']),1)
            with self.assertRaisesRegex(ValueError,'index_revision_changed'):
                reader.search(query='agymarker',offset=1,index_revision=first['index_revision'])
        self.assertEqual(self.request('/api/reuse/refresh',{'system':'linux','source':'agy'})[0],200)
        for route in routes: self.assertEqual(self.request(route)[0],409)
        status, fresh = self.request('/api/reuse/search?q=changed-source-marker&source=agy')
        self.assertEqual(status,200)
        self.assertEqual(fresh['items'][0]['id'],'decoded-fixture')
