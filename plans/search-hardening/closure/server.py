#!/usr/bin/env python3
"""Start/stop only the frozen, synthetic acceptance server recorded here."""
import argparse
from pathlib import Path
import json
import os
import signal
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument('action', choices=['start', 'stop'])
p.add_argument('--run', type=Path, required=True)
p.add_argument('--source', type=Path)
p.add_argument('--home', type=Path)
p.add_argument('--port', type=int, default=8843)
a = p.parse_args()
run = a.run.resolve()
record = run / 'runtime.json'
if a.action == 'stop':
    saved = json.loads(record.read_text())
    process = Path('/proc') / str(saved['pid'])
    if process.exists():
        if os.readlink(process / 'cwd') != saved['cwd'] or (process / 'cmdline').read_bytes().split(b'\0')[:-1] != [s.encode() for s in saved['command']]:
            raise RuntimeError('Process identity changed; refusing to stop')
        os.kill(saved['pid'], signal.SIGTERM)
        for _ in range(30):
            if not process.exists() or (process / 'stat').read_text().split()[2] == 'Z':
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Process has not stopped')
    print('stopped', saved['pid'])
else:
    if not a.source or not a.home:
        p.error('start needs --source and --home')
    run.mkdir(parents=True, exist_ok=True)
    if record.exists() and (Path('/proc') / str(json.loads(record.read_text())['pid'])).exists():
        raise RuntimeError('Recorded process exists; verify and stop it first')
    home = a.home.resolve()
    command = ['/usr/bin/python3', '-B', '-u', 'app.py', '--host', '127.0.0.1', '--port', str(a.port),
               '--scan-interval', '3600', '--data-dir', str(run / 'cache'),
               '--codex-dir', str(home / '.codex'), '--claude-dir', str(home / '.claude'), '--no-wsl']
    environment = {'HOME': str(home), 'PATH': os.defpath, 'LANG': 'C.UTF-8',
                   'XDG_CONFIG_HOME': str(home / '.config'), 'XDG_DATA_HOME': str(home / '.local/share'),
                   'XDG_STATE_HOME': str(home / '.local/state'), 'XDG_CACHE_HOME': str(home / '.cache')}
    with (run / 'server.log').open('ab') as log:
        child = subprocess.Popen(command, cwd=a.source.resolve(), env=environment, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
    record.write_text(json.dumps({'pid': child.pid, 'cwd': str(a.source.resolve()), 'command': command,
                                 'environment': environment}, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'pid': child.pid, 'url': 'http://127.0.0.1:'+str(a.port)}))
