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

# Success is printed only after every regression completes.


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

# 온라인 Viewer는 초기 광-only 상태를 유지하되,
# L1~L3에서는 체크 그룹을 표시하고 L4 이상에서는 모두 숨긴다.
assert "FIBER:true,COAX:false,POLE:false,CONDUIT:false" in page
assert "const mapLevelNow=map.getLevel();" in page
assert "const detailMode=mapLevelNow<=3;" in page
assert "if(!detailMode)" in page
assert "L3 이하에서 광/동축/전주/관로 표시" in page
assert "if(myGeneration!==loadGeneration)return;" in page
assert "if(map.getLevel()>3)" in page
assert "return isMaxDetail && groupEnabled[group]===true;" in page
assert "['FIBER','COAX','CONDUIT'].map" in page
assert "+' 선:'+" in page
print("ONLINE_LAYER_VISIBILITY_RULES_OK")

# 세션 401은 Viewer 오류 표시가 아니라 종료/로그인 복귀 흐름으로 처리되어야 한다.
from online_viewer import Api, SESSION_ENDED_EXIT_CODE
from server_client_windows import ServerError
_api = Api()
_api.window = None
handled = _api._handle_error(ServerError("expired", status=401))
assert handled.get("session_ended") is True
assert _api.session_ended is True
assert SESSION_ENDED_EXIT_CODE == 41
print("SESSION_EXPIRED_VIEWER_EXIT_OK")

# Windows 온라인 Viewer는 서버 공통 지도 설정을 사용하고 기본값은 500m/200m이다.
page = html("test-kakao-key", "test-local-token")
assert "let QUERY_RADIUS_METERS=500;" in page
assert "let QUERY_RECENTER_METERS=200;" in page
assert "apiCall('map_display_settings')" in page
assert "myLat=lat;" in page and "myLng=lng;" in page
print("ONLINE_SHARED_MAP_DISPLAY_SETTINGS_OK")


# Windows 온라인 Viewer는 지역별 gzip 영구 캐시와 Revision 확인을 사용한다.
from online_viewer import CACHE_DIR
from server_client_windows import CMBServerClient
assert "online_cache" in str(CACHE_DIR)
assert hasattr(CMBServerClient, "online_versions")
assert hasattr(CMBServerClient, "online_symbols")
_api2 = Api()
assert hasattr(_api2, "_load_cache")
assert hasattr(_api2, "_save_cache")
assert hasattr(_api2, "_apply_versions")
assert hasattr(_api2, "_cache_covers")
print("WINDOWS_REVISION_CACHE_OK")


# map-viewer 내부 관리자 기능은 refresh token 회전을 피하기 위해
# 하나의 CMBServerClient를 공유해야 한다.
main_source = (root / "main.py").read_text(encoding="utf-8")
assert "def __init__(self, session_user=None, session_client=None):" in main_source
assert "self.session_client = session_client" in main_source
assert "session_client=session_client" in main_source
assert main_source.count("client = self._get_session_client()") == 3
print("SHARED_SESSION_CLIENT_OK")

subprocess.run([sys.executable, str(root / "session_regression_selftest.py")], cwd=root, check=True)
subprocess.run([sys.executable, str(root / "online_render_selftest.py")], cwd=root, check=True)
print("ALL CURRENT CHECKS PASSED")


# 지역 관리에는 지역명 수정/완전 삭제 기능이 있어야 한다.
from server_client_windows import CMBServerClient
assert hasattr(CMBServerClient, "update_region")
assert hasattr(CMBServerClient, "delete_region")
admin_users_source = (root / "admin_users.py").read_text(encoding="utf-8")
assert "지역명 수정" in admin_users_source
assert "지역 삭제" in admin_users_source
assert "서버 도면 Revision" in admin_users_source
assert "SYMBOL 데이터" in admin_users_source
assert "사용자-지역 권한 연결" in admin_users_source
print("REGION_EDIT_DELETE_UI_OK")


# 정지 계정과 일반 401 로그인 오류는 사용자 메시지를 구분해야 한다.
launcher_source = (root / "launcher.py").read_text(encoding="utf-8")
assert "ACCOUNT_DISABLED" in launcher_source
assert "사용 정지된 계정입니다. 관리자에게 문의해주세요." in launcher_source
assert "아이디 또는 비밀번호를 확인해주세요." in launcher_source
print("DISABLED_ACCOUNT_LOGIN_MESSAGE_OK")


# 런처/맵 Viewer/온라인 Viewer는 같은 refresh token 상태를 공유해야 한다.
client_source = (root / "server_client_windows.py").read_text(encoding="utf-8")
launcher_source = (root / "launcher.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "CMB_AUTH_STATE_PATH" in client_source
assert "_shared_state_lock" in client_source
assert "_sync_from_shared_state" in client_source
assert "_sync_to_shared_state" in client_source
assert "CMB_AUTH_STATE_PATH" in launcher_source
assert "self.c.on_session_expired = self.expire_session" in online_source
assert "def expire_session(self):" in online_source
print("CROSS_PROCESS_SESSION_STATE_OK")


# 관로/맨홀/핸드홀은 CN_L_POLE 계열이어도 POLE보다 CONDUIT가 우선이어야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'layer.startswith("CN_L_POLE_MANHOLE")' in admin_upload_source
assert 'layer.startswith("CN_L_POLE_HANDHOLE")' in admin_upload_source
assert 'layer.startswith("CN_L_POLE_LINE_")' in admin_upload_source
assert admin_upload_source.index('return "CONDUIT"') < admin_upload_source.index('return "POLE"')
print("CONDUIT_CLASSIFICATION_PRIORITY_OK")

# 지역 선택 시 캐시를 읽고 서버 버전만 확인한 뒤, 동일 버전이면 /layers 없이 즉시 캐시 렌더 단계로 넘어가야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
select_block = online_source.split("    def select(self, region):", 1)[1].split("    def objects(", 1)[0]
assert "self._load_cache()" in select_block
assert "self.c.online_versions(self.region)" in select_block
assert "self.c.online_layers(self.region)" not in select_block
assert '"cache_ready": cache_ready' in select_block
print("FAST_CACHE_VERSION_CHECK_OK")


# 서버 버전이 달라지면 기존 지역 캐시 파일과 메모리 데이터를 즉시 폐기해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "def _delete_cache_file(self):" in online_source
assert "version_changed = bool(previous) and previous != versions" in online_source
assert "self._delete_cache_file()" in online_source
assert '"features": {}' in online_source
assert '"coverage": []' in online_source
print("STALE_CACHE_DELETE_ON_VERSION_CHANGE_OK")


# 일반 Windows EXE는 두 번째 Launcher/Tk 인스턴스를 만들면 안 된다.
main_source = (root / "main.py").read_text(encoding="utf-8")
assert "CMB_DXF_VIEWER_SINGLE_INSTANCE_V1" in main_source
assert "CreateMutexW" in main_source
assert "ERROR_ALREADY_EXISTS" in main_source
assert "SO_EXCLUSIVEADDRUSE" in main_source
assert "SO_REUSEADDR" not in main_source
assert "activate_existing_instance()" in main_source
print("SINGLE_INSTANCE_MUTEX_OK")


# ONU는 동축기기로 분류되고 COAX 선택은 케이블(LineString)과 기기(Point)를 함께 표시해야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'if "ONU" in text:' in admin_upload_source
onu_pos = admin_upload_source.index('if "ONU" in text:')
fiber_pos = admin_upload_source.index('# 광선로 / 광장비')
assert onu_pos < fiber_pos
assert 'return "COAX"' in admin_upload_source[onu_pos:fiber_pos]

online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "const pointFeatures=features.filter" in online_source
assert "const lineFeatures=features.filter" in online_source
assert "groupEnabled[group]===true" in online_source

extract_source = (root / "server_extract.py").read_text(encoding="utf-8")
assert '"COAX": "동축(케이블+기기)"' in extract_source
assert ").upper() in groups" in extract_source
print("ONU_COAX_AND_COAX_DEVICE_RENDER_OK")


# 케이블 원본 CAD 색상은 업로드 -> 온라인 표시 -> 복구 DXF까지 보존되어야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
recovery_source = (root / "recovery_v2.py").read_text(encoding="utf-8")
assert 'attrs["_cmb_style"] = style' in admin_upload_source
assert 'style["display_color"] = display_color.lower()' in admin_upload_source
assert 'style["true_color"] = int(display_color[1:], 16)' in admin_upload_source
assert "function originalCableColor" in online_source
assert "const c=originalCableColor(p,group);" in online_source
assert 'display_color = str(style.get("display_color") or "")' in recovery_source
print("CABLE_COLOR_PRESERVATION_OK")

# 지역 삭제 경고는 도면/심볼/권한 연결까지 삭제됨을 명시해야 한다.
admin_users_source = (root / "admin_users.py").read_text(encoding="utf-8")
assert "서버 도면 Revision" in admin_users_source
assert "SYMBOL 데이터" in admin_users_source
assert "사용자-지역 권한 연결" in admin_users_source
print("REGION_CASCADE_DELETE_WARNING_OK")
