"""Validate the selected 1.7.0 scheduler payload against the original archive manifest."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'docs/upstream/scheduler-1.7.0-manifest.json').read_text(encoding='utf-8'))
failures = []
for file in manifest['files']:
    path = ROOT / 'vendor/hmigbot-1.7.0' / file['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != file['sha256']:
        failures.append(file['path'])
print(json.dumps({'version': manifest['version'], 'files': len(manifest['files']), 'status': 'failed' if failures else 'passed', 'failures': failures}, ensure_ascii=False))
raise SystemExit(1 if failures else 0)
