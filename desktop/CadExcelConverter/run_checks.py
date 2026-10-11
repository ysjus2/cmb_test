from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
checks = ['essenpoly_selftest.py', 'conduit_selftest.py', 'full_layer_selftest.py',
          'navigation_selftest.py', 'selftest.py', 'network_extract_selftest.py',
          'pipe_endpoint_selftest.py', 'identity_selftest.py', 'cache_selftest.py',
          'zoom_selftest.py', 'extract_display_selftest.py', 'current_features_selftest.py']
for check in checks:
    print(f'CHECK {check}', flush=True)
    subprocess.run([sys.executable, str(root / check)], cwd=root, check=True)

from online_viewer import html
page = html("test-kakao-key", "test-local-token")
assert 'const LOCAL_API_TOKEN="test-local-token";' in page
assert "apiCall('regions')" in page
assert "apiCall('select',{region:" in page
assert "apiCall('objects',{west:" in page
assert "pywebview.api" not in page
assert "/api/" in page
print('ONLINE_VIEWER_LOCAL_API_OK')

print('ALL CURRENT CHECKS PASSED')


from types import SimpleNamespace
from admin_upload import classify_entity

def _e(layer, block=""):
    return SimpleNamespace(layer=layer, block_name=block)

assert classify_entity(_e("TS_BASEMAP")) is None
assert classify_entity(_e("CN_F_CLOSURE")) == "FIBER"
assert classify_entity(_e("CN_C_ONU")) == "FIBER"
assert classify_entity(_e("CN_C_CABLE")) == "COAX"
assert classify_entity(_e("CN_C_AMP")) == "COAX"
assert classify_entity(_e("CN_L_POLE")) == "POLE"
assert classify_entity(_e("CN_M_USER_TEST")) == "USER"
print("UPLOAD_CLASSIFICATION_OK")

assert "startsWith('TS_')" in page
print("ONLINE_TS_LAYER_EXCLUSION_OK")
