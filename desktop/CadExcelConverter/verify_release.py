"""Verify the packaged smoke result and record executable/source digests."""
from pathlib import Path
import hashlib
import json
import sys

exe, smoke, output = map(Path, sys.argv[1:])
result = json.loads(smoke.read_text(encoding='utf-8'))
assert result['ok'] and result['version'] == '3.71_FINAL'
assert exe.read_bytes()[:2] == b'MZ'
root = Path(__file__).resolve().parent
manifest = {'version':'3.71_FINAL', 'executable':exe.name,
    'sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
    'packaged_smoke':result,
    'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))}}
output.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('PACKAGED_RELEASE_VERIFIED',manifest['sha256'])
