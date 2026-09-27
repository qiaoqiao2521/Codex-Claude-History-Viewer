#!/usr/bin/env python3
"""Create an isolated runtime snapshot; no cache, private history or credentials."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--repo', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
repo = a.repo.resolve()
out = a.out.resolve()
out.mkdir(parents=True, exist_ok=False)
files = [Path('app.py'), Path('VERSION')]
for folder in ('audit', 'history_core', 'static'):
    files += [f.relative_to(repo) for f in (repo / folder).rglob('*')
              if f.is_file() and '__pycache__' not in f.parts and f.suffix in ('.py', '.js', '.html', '.css')]
hashes = {}
for relative in sorted(files):
    data = (repo / relative).read_bytes()
    target = out / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    hashes[str(relative)] = hashlib.sha256(data).hexdigest()
manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'source_repo': str(repo),
            'head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip(),
            'python': subprocess.check_output(['python3','--version'], text=True).strip(), 'files': hashes}
(out / 'snapshot.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n')
print(json.dumps({'snapshot': str(out), 'files': len(files)}))
