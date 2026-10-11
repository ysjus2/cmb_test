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
from admin_upload import classify_entity, _points

def _e(layer, block=""):
    return SimpleNamespace(layer=layer, block_name=block)

assert classify_entity(_e("TS_BASEMAP")) is None
assert classify_entity(_e("TL_SCCO_SIG")) is None
assert classify_entity(_e("CN_F_CLOSURE")) == "FIBER"
assert classify_entity(_e("CN_C_ONU")) == "FIBER"
assert classify_entity(_e("CN_C_CABLE")) == "COAX"
assert classify_entity(_e("CN_C_AMP")) == "COAX"
assert classify_entity(_e("CN_F_CABLE")) == "FIBER"
assert classify_entity(_e("CONDUIT_MAIN")) == "CONDUIT"
assert classify_entity(_e("CN_L_POLE")) == "POLE"
assert classify_entity(_e("CN_M_USER_TEST")) == "USER"
print("UPLOAD_CLASSIFICATION_OK")

assert "startsWith('TS_')" in page
print("ONLINE_TS_LAYER_EXCLUSION_OK")

# INSERT/POINT 장비는 내부 선분보다 삽입점을 우선하여 Point로 업로드되어야 한다.
device = SimpleNamespace(
    entity_type="INSERT",
    primitives=[
        ("line", [(10.0, 10.0), (20.0, 20.0)]),
        ("insert", (15.0, 15.0)),
    ],
    bbox=(10.0, 10.0, 20.0, 20.0),
)
assert _points(device) == [(15.0, 15.0)]
print("DEVICE_POINT_GEOMETRY_OK")

# 온라인 Viewer는 초기 광-only 상태와 최대 상세단계 체크 표시 규칙을 유지한다.
assert "FIBER:true,COAX:false,POLE:false,CONDUIT:false" in page
assert "const isMaxDetail=mapLevel<=1;" in page
assert "groupEnabled.FIBER===true" in page
assert "return groupEnabled[group]===true;" in page
print("ONLINE_LAYER_VISIBILITY_RULES_OK")
