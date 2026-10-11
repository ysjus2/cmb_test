"""Run the generated Viewer JavaScript with a deterministic Kakao adapter."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from online_viewer import html

node = os.environ.get('CMB_TEST_NODE') or shutil.which('node')
if not node:
    raise RuntimeError('Node.js is required for executable Viewer regression checks')
page = html('test-key', 'test-token')
script = page.rsplit('<script>', 1)[1].split('</script>', 1)[0]
script = script.split("['pointerdown','pointermove'", 1)[0]
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / 'viewer.js'
    path.write_text(script, encoding='utf-8')
    subprocess.run([node, str(Path(__file__).with_name('online_render_selftest.cjs')), str(path)], check=True)
