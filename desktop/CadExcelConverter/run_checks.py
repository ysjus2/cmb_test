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
from admin_upload import classify_entity, _geometry_parts

def _e(layer, block="", entity_type="INSERT"):
    return SimpleNamespace(layer=layer, block_name=block, entity_type=entity_type)

assert classify_entity(_e("TS_BASEMAP")) is None
assert classify_entity(_e("TL_SCCO_SIG")) is None
assert classify_entity(_e("CN_F_CLOSURE")) == "FIBER"
assert classify_entity(_e("CN_C_ONU")) == "COAX"
assert classify_entity(_e("CN_C_CABLE")) == "COAX"
assert classify_entity(_e("CN_C_AMP")) == "COAX"
assert classify_entity(_e("CN_F_CABLE")) == "FIBER"
assert classify_entity(_e("CONDUIT_MAIN")) == "CONDUIT"
assert classify_entity(_e("CN_L_POLE")) == "POLE"
assert classify_entity(_e("CN_L_POLEMAP_BOUND", entity_type="LWPOLYLINE")) is None
assert classify_entity(_e("CN_L_POLE_ID", entity_type="ATTRIB")) is None
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
kind, geom = _geometry_parts(device)
assert kind == "Point"
assert geom == [(15.0, 15.0)]

multi = SimpleNamespace(
    entity_type="LWPOLYLINE",
    primitives=[
        ("polyline", [(0.0, 0.0), (1.0, 1.0)]),
        ("line", [(2.0, 2.0), (3.0, 3.0)]),
    ],
    bbox=(0.0, 0.0, 3.0, 3.0),
)
kind, geom = _geometry_parts(multi)
assert kind == "MultiLineString"
assert len(geom) == 2
print("DEVICE_POINT_GEOMETRY_OK")
print("MULTIPART_SOURCE_GEOMETRY_OK")

# 온라인 Viewer는 광을 영구 캐시 레이어로 유지하고,
# L1~L3에서만 주변 기기/동축/전주/관로를 추가한다.
assert "FIBER:true,COAX:true,POLE:false,CONDUIT:false" in page
assert "const mapLevelNow=map.getLevel();" in page
assert "const detailMode=mapLevelNow<=3;" in page
assert "clearNonFiberOverlays()" in page
assert "광 캐시 표시" in page
assert "function renderFiberFeatures(features)" in page
assert "if(group==='FIBER')return false;" in page
assert "if(myGeneration!==loadGeneration)return;" in page
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


# map-viewer는 최초 실행을 서버와 완전히 분리한다.
# DXF/추출/Excel은 로컬에서 즉시 사용하고 서버 업/다운 시점에만 client를 만든다.
main_source = (root / "main.py").read_text(encoding="utf-8")
launcher_source = (root / "launcher.py").read_text(encoding="utf-8")
assert "def __init__(self, session_user=None, session_client=None, local_map_mode=False):" in main_source
assert "self.local_map_mode = bool(local_map_mode)" in main_source
assert "self.can_extract = True if self.local_map_mode" in main_source
assert 'if "--map-viewer" in sys.argv:' in main_source
assert "verified_user = session_client.me()" not in main_source
assert "local_map_mode=True" in main_source
assert "session_client=None" in main_source
assert 'state="normal"' in launcher_source
assert 'self._spawn("--map-viewer", verify_server=False)' in launcher_source
assert "if self.session_guard is not None:\n            self.session_guard.pause()" in launcher_source
map_block = main_source.split('if "--map-viewer" in sys.argv:', 1)[1].split("import socket", 1)[0]
for forbidden in ("session_client.me(", ".health(", ".regions(", ".online_layers("):
    assert forbidden not in map_block
assert "def _spawn(self, flag, verify_server=True):" in launcher_source
assert main_source.count("client = self._get_session_client()") == 3
print("OFFLINE_MAP_VIEWER_LAZY_SERVER_OK")

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
assert "도면 Revision과 객체" in admin_users_source
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
assert 'if not self.c.access_token:' in online_source
assert 'if not self.c.refresh_token:' in online_source
assert 'self.c._sync_from_shared_state()' in online_source
assert "self.object_cell_refreshing = set()" in online_source
assert "def _start_object_cell_refresh" in online_source
assert "def _polemap_cache_path(self):" in online_source
assert "def _cached_polemap_cells(self, west, south, east, north):" in online_source
assert '"cache": "stale"' in online_source
assert "서버 실패 시 버전이 오래됐더라도 기존 셀 캐시는 절대 버리지 않는다." in online_source
admin_upload_source = Path(__file__).resolve().with_name("admin_upload.py").read_text(encoding="utf-8")
assert "def _object_grid_ids(e):" in admin_upload_source
assert 'attrs["_cmb_grid_ids"] = object_grid_ids' in admin_upload_source
assert 'if len(object_grid_ids) == 1:' in admin_upload_source
assert "if started >= 2:" in online_source
assert '"pending_cells": len(missing_cells)' in online_source
assert "cached_features = [" in online_source
assert "self._feature_intersects(feature, west, south, east, north)" in online_source
clear_group_block = online_source.split("function clearGroupOverlays(group)",1)[1].split("function hideGroupOverlays",1)[0]
assert "loadGeneration++" not in clear_group_block
assert "let nonFiberLoadTimer=null;" in online_source
assert "function queueNonFiberLoad(force=false,delay=120)" in online_source
assert "function bestRegionForMapCenter(center)" in online_source
assert "async function cachedRegionForMapCenter(center)" in online_source
assert "apiCall('cached_region_probe'" in online_source
assert "def cached_region_probe(self, regions, lat, lng):" in online_source
assert "def _start_polemap_refresh(self, west, south, east, north):" in online_source
assert "현재 화면은 서버보다 로컬 Polemap 캐시를 먼저 사용한다." in online_source
assert "let matched=await cachedRegionForMapCenter(center);" in online_source
assert "async function probeRegionForMapCenter(center)" in online_source
assert "apiCall('polemap_probe'" in online_source
assert "gridDiag.stage='지역 GRID 탐색';" in online_source
assert "radius_m:2000" in online_source
assert "def polemap_probe(self, region, lat, lng, radius_m=2000):" in online_source
assert "function gridDiagText()" in online_source
assert "function centerCellFromList(cells,lat,lng)" in online_source
assert "'GRID '+String(gridDiag.centerGrid||'-')" in online_source
assert "'STAGE '+String(gridDiag.stage||'대기')" in online_source
assert "gridDiag.progress='FIBER '+String(i+1)+'/'+String(ordered.length)" in online_source
assert "regionBoundsArea(a.bounds)-regionBoundsArea(b.bounds)" in online_source
assert "'REGION '+region" in online_source
assert "'CELLS '+String(gridDiag.cells||0)" in online_source
bootstrap_tail = online_source.split("let authBootstrapped=false;",1)[1]
assert "const ok=await bootstrapAuth();" in bootstrap_tail
assert "initMap();" in bootstrap_tail
assert bootstrap_tail.index("const ok=await bootstrapAuth();") < bootstrap_tail.index("initMap();")
assert "await loadFiberViewport(false);" in online_source
assert "queueNonFiberLoad(false,0);" in online_source
assert "queueNonFiberLoad(true,0);" in online_source
assert "const FIBER_QUERY_RADIUS_METERS=10000;" in online_source
assert "gridDiag.stage='현재 GRID 광';" in online_source
assert "gridDiag.stage='현재 GRID 광 표시';" in online_source
assert "gridDiag.stage='10km 광 로딩';" in online_source
assert "gridDiag.stage='10km 광 완료';" in online_source
assert "이 함수가 끝난 뒤에만 호출부가 동축/기기 조회를 시작한다." in online_source
assert "queueNonFiberLoad(false,0);" in online_source
assert "const primary=ordered[0];" in online_source
assert "if(moved<FIBER_RECENTER_METERS && hasFiberCache)" not in online_source
assert "const FIBER_RECENTER_METERS=8000;" in online_source
assert "const FIBER_RECENTER_DELAY_MS=1000;" in online_source
assert "function scheduleFiberRecenter(force=false)" in online_source
assert "moved>=FIBER_RECENTER_METERS" in online_source
assert "fiberRecenterTimer=setTimeout(async()=>{" in online_source
assert "gridDiag.stage='광 기준점 대기';" in online_source
assert "gridDiag.stage='광 기준점 확정';" in online_source
assert "10km 광 전체가 완료된 이 중심점을 다음 8km 이동 판정의 고정점으로 사용한다." in online_source
assert "scheduleFiberRecenter(false);" in online_source
assert "lastFiberCacheLat=null,lastFiberCacheLng=null,lastFiberCacheRegion='';" in online_source
assert "layers=None" in online_source
assert "광 셀 조회는 /layers 메타데이터에 의존하지 않는다." in online_source
assert "lastFiberCacheLat=null;" in online_source
assert "const fiberLatDelta=FIBER_QUERY_RADIUS_METERS/111320;" in online_source
assert "const fiberLngDelta=FIBER_QUERY_RADIUS_METERS/(111320*fiberLngScale);" in online_source
print("CROSS_PROCESS_SESSION_STATE_OK")


# 관로/맨홀/핸드홀은 CN_L_POLE 계열이어도 POLE보다 CONDUIT가 우선이어야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'layer.startswith("CN_L_POLE_MANHOLE")' in admin_upload_source
assert 'layer.startswith("CN_L_POLE_HANDHOLE")' in admin_upload_source
assert 'layer.startswith("CN_L_POLE_LINE_")' in admin_upload_source
assert admin_upload_source.index('return "CONDUIT"') < admin_upload_source.index('return "POLE"')
print("CONDUIT_CLASSIFICATION_PRIORITY_OK")

# 지역 전환은 지역 전체 광/일반 객체 gzip을 읽지 않고 Polemap 셀 캐시만 현재 화면부터 읽어야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
select_block = online_source.split("    def select(self, region):", 1)[1].split("    def _fiber_cell_dir", 1)[0]
assert "self._load_cache()" not in select_block
assert "self._load_fiber_cache()" not in select_block
assert 'self.cache_state = {"versions": {}, "features": {}, "coverage": []}' in select_block
assert 'self.fiber_cache = {"version": "", "features": []}' in select_block
assert "def _fiber_cell_dir(self):" in online_source
assert "def _object_cell_dir(self):" in online_source
assert "def fiber_cell(self, grid_id, west, south, east, north, force=False):" in online_source
assert "def _cell_object_features(self, cell, version_signature):" in online_source
assert "def polemap(self, west, south, east, north):" in online_source
assert 'name == "fiber_cell"' in online_source
assert 'name == "polemap"' in online_source
print("FAST_POLEMAP_CELL_CACHE_OK")


# 서버 버전이 달라져도 기존 화면 캐시는 유지하고 coverage만 무효화해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "def _delete_cache_file(self):" in online_source
assert "version_changed = bool(previous) and previous != versions" in online_source
version_block = online_source.split("def _apply_versions",1)[1].split("def _version_signature",1)[0]
assert "self._delete_cache_file()" not in version_block
assert 'self.cache_state["coverage"] = []' in version_block
assert 'self.cache_state["versions"] = versions' in version_block
print("STALE_CACHE_PRESERVED_UNTIL_REFRESH_OK")


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
assert "const pointCandidates=features.filter" in online_source
assert "const pointFeatures=[...deviceFeatureMap.values()];" in online_source
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
assert "CAD에서 추출한 실제 선 색상을 최우선으로 복원한다." in online_source
assert "function hideGroupOverlays(group)" in online_source
assert "function showGroupOverlays(group)" in online_source
assert "COAX reopen" not in online_source
assert 'display_color = str(style.get("display_color") or "")' in recovery_source
print("CABLE_COLOR_PRESERVATION_OK")

# 지역 삭제 경고는 도면/심볼/권한 연결까지 삭제됨을 명시해야 한다.
admin_users_source = (root / "admin_users.py").read_text(encoding="utf-8")
assert "도면 Revision과 객체" in admin_users_source
assert "SYMBOL 데이터" in admin_users_source
assert "사용자-지역 권한 연결" in admin_users_source
print("REGION_CASCADE_DELETE_WARNING_OK")

# 서버 revision 확인은 앱 실행 세션 동안 지역별 최초 1회만 수행한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "self.checked_regions = set()" in online_source
assert "self.version_check_lock = threading.Lock()" in online_source
assert "if not force and region in self.checked_regions:" in online_source
assert "self.checked_regions.add(region)" in online_source
assert "now - self.last_version_check < 60" not in online_source
print("ONCE_PER_REGION_VERSION_CHECK_OK")

# 온라인 Viewer는 정보용 POINT를 기기로 렌더하지 않고 동일 기기 키를 1회만 렌더해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert "function isInfoPointFeature(f)" in online_source
assert "function deviceFeatureKey(f)" in online_source
assert "const deviceFeatureMap=new Map();" in online_source
assert "if(!deviceFeatureMap.has(key))deviceFeatureMap.set(key,f);" in online_source
assert "if(kind==='generic' && entityType!=='INSERT' && !explicitDevice)return false;" in online_source
assert 'str(e.entity_type or "").upper() == "INSERT"' in admin_upload_source
assert 'in {"INSERT", "POINT"}' not in admin_upload_source.split('attrs["_cmb_is_device"]',1)[1].split('for src_key',1)[0]
print("UNIQUE_DEVICE_RENDER_OK")

# 줌 레벨 전환은 API 재호출 없이 기존 메모리 오버레이 표시/숨김만 수행해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "function applyZoomVisibility(mapLevel)" in online_source
zoom_block = online_source.split("kakao.maps.event.addListener(map,'zoom_changed'",1)[1].split("});",1)[0]
assert "applyZoomVisibility(level)" in zoom_block
assert "loadObjects(true)" not in zoom_block
assert "lastDetailMode=(level<=3);" in zoom_block
print("INSTANT_ZOOM_VISIBILITY_OK")

# 캐시 우선 정책: revision 변경 시 캐시를 먼저 삭제하지 않고,
# 새 BBOX 수신 성공 후 해당 범위만 원자적으로 교체해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "revision이 바뀌어도 현재 화면 캐시는 즉시 삭제하지 않는다." in online_source
assert "self._delete_cache_file()" not in online_source.split("def _apply_versions",1)[1].split("def _version_signature",1)[0]
assert "stale_keys = [" in online_source
assert "feature_store.pop(key, None)" in online_source
assert "function fiberDiagText()" in online_source
assert "fiberDiag.lineObjects=lineObjects;" in online_source
assert "fiberDiag.renderParts=rendered;" in online_source
print("CACHE_FIRST_ATOMIC_UPDATE_OK")

# 장시간 서버 업로드 중에는 로컬 idle logout을 중지하고 서버 heartbeat를 유지해야 한다.
server_client_source = (root / "server_client_windows.py").read_text(encoding="utf-8")
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert '"/admin/drawings/upload",' in server_client_source
assert "timeout=None" in server_client_source
assert "guard.pause()" in admin_upload_source
assert "guard.resume()" in admin_upload_source
assert "for _ in range(15):" in admin_upload_source
print("LONG_UPLOAD_SESSION_KEEPALIVE_OK")

# 동일 revision이라도 광 캐시 개수가 서버 object_count와 다르면 cache hit으로 인정하면 안 된다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "cached_count == expected_count" in online_source
assert "and cache_complete" in online_source
assert '"expected_count": expected_count' in online_source
print("FIBER_CACHE_COUNT_VALIDATION_OK")

# 구버전 COAX 기기 POINT도 _cmb_is_device=true이면 유지하고 기기는 케이블보다 위에 표시한다.
assert "const explicitDevice=(fields._cmb_is_device===true);" in online_source
assert "&& !explicitDevice" in online_source
assert "JSON.stringify(p.attributes" in online_source
assert "setZIndex(30)" in online_source
assert "setZIndex(31)" in online_source
print("LEGACY_COAX_DEVICE_LOD_OK")

# 정보/주석 POINT는 기기로 표시하지 않고 FIBER Point 기기는 상세 줌에서 캐시로 표시해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert "function isInfoPointFeature(f)" in online_source
assert "['TEXT','MTEXT','ATTRIB','ATTDEF','DIMENSION','LEADER','MLEADER']" in online_source
assert "if(isInfoPointFeature(f))return false;" in online_source
assert "fiberDeviceMap" in online_source
assert "drawDevice(new kakao.maps.LatLng" in online_source
assert "if(visible && kind)visible=(mapLevel<=3);" in online_source
assert "def _is_info_entity(e):" in admin_upload_source
assert "not _is_info_entity(e)" in admin_upload_source
print("FIBER_DEVICE_AND_INFO_FILTER_OK")

# 초대형 전주 데이터는 1시간을 넘길 수 있으므로 클라이언트 업로드에 고정 timeout을 두지 않는다.
server_client_source = (root / "server_client_windows.py").read_text(encoding="utf-8")
assert "def _raw_json_upload(self, path, payload, progress_callback=None, timeout=None):" in server_client_source
assert "timeout=None," in server_client_source
assert "timeout=3600" not in server_client_source
print("NO_FIXED_UPLOAD_TIMEOUT_OK")

# 장시간 업로드는 UI가 멈춘 것처럼 보이지 않도록 파일/객체수/용량/경과시간을 실시간 표시해야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert "self.upload_progress = ttk.Progressbar" in admin_upload_source
assert 'mode="indeterminate"' in admin_upload_source
assert "패키지 {package_mb:.1f} MB" in admin_upload_source
assert "경과 {elapsed} · 세션 유지중" in admin_upload_source
assert "def _run_background_task" in admin_upload_source
assert "self.update()" in admin_upload_source
print("LIVE_UPLOAD_PROGRESS_OK")

# 업로드 전송률은 실제 전송 바이트/전체 바이트 기준으로 표시해야 한다.
server_client_source = (root / "server_client_windows.py").read_text(encoding="utf-8")
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert "class _ProgressBody(io.BytesIO):" in server_client_source
assert "self._callback(self._sent, self._total)" in server_client_source
assert '"Content-Length": str(len(body_bytes))' in server_client_source
assert "progress_callback=progress_callback" in server_client_source
assert "pct = max(0.0, min(100.0, sent * 100.0 / total))" in admin_upload_source
assert "서버 DB 저장/검증 중" in admin_upload_source
print("EXACT_UPLOAD_BYTE_PROGRESS_OK")

# COAX/POLE/CONDUIT는 stale coverage라도 기존 캐시를 즉시 반환하고 백그라운드 갱신해야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "def _start_bbox_refresh" in online_source
assert '"cache": "stale"' in online_source
assert '"refresh_pending": True' in online_source
assert "threading.Thread(target=worker, daemon=True).start()" in online_source
assert "setTimeout(()=>loadObjects(true),900);" in online_source
print("STALE_CACHE_BACKGROUND_REFRESH_OK")

# 동일 종류의 근접 기기는 CAD handle/ID가 달라도 중복 심벌로 만들지 않는다.
assert "Number(a[0]).toFixed(5)" in online_source
assert "Number(a[1]).toFixed(5)" in online_source
assert "const hasTextPayload=" in online_source
assert "const dxfHasText=" in online_source
print("DEVICE_SPATIAL_DEDUPE_AND_TEXT_FILTER_OK")

# -Anno 등록정보는 광/동축 모두 업로드 및 Viewer에서 완전히 제외한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert 'or "ANNO" in layer' in admin_upload_source
assert 'or "ANNO" in block' in admin_upload_source
assert "function isAnnoFeature(f)" in online_source
assert "if(isAnnoFeature(f))return true;" in online_source
assert "layer.includes('ANNO')" in online_source

# 증폭기 입력 케이블은 연결 handle + 회전각 + 접속 방향으로 판정하고 입력 1개에만 화살표를 표시한다.
assert "function inferDirectionalInputFromFeature(feature,lineFeatures)" in online_source
assert "fields._cmb_connections" in online_source
assert "const last=clean[clean.length-1];" in online_source
assert "const prev=clean[clean.length-2];" in online_source
assert "const signalDeg=" in online_source
assert "function applyDirectionalInputArrows(devices,lineFeatures)" in online_source
assert "amp_input_arrow" in online_source
assert "입력화살표" in online_source
print("ANNO_EXCLUSION_AND_AMP_INPUT_ARROW_OK")

# 동축 케이블 좌표 순서의 끝점을 입력으로 사용하고, 증폭기 방향은 입력 반대 신호방향으로 맞춘다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "const last=clean[clean.length-1];" in online_source
assert "if(dist>32)return;" in online_source
assert "fields._cmb_rotation_deg=inferred.deg;" in online_source
assert "p._cmb_directional_input=inferred;" in online_source
assert "입력 케이블 끝에서 기기 쪽으로 향하는 V 화살표" in online_source
print("COAX_ENDPOINT_INPUT_DIRECTION_OK")

# AMP/TAP/분기기는 동일한 케이블 끝점 입력 판정과 입력 화살표 정책을 사용한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "if(!['amp','tap','splitter'].includes(kind))return null;" in online_source
assert "function applyDirectionalInputArrows(devices,lineFeatures)" in online_source
assert "['amp','tap','splitter'].includes(dev.kind)" in online_source
assert "tap_input_arrow" in online_source
assert "splitter_input_arrow" in online_source
assert "입력화살표" in online_source
print("TAP_SPLITTER_INPUT_ARROW_OK")

# 2/3분배기 및 DC는 원형 splitter, PI만 직사각형 중앙 I 심벌을 사용한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert 'layer.startswith("CN_C_DC")' in admin_upload_source
assert 'return "splitter"' in admin_upload_source
assert 'layer.startswith("CN_C_PI")' in admin_upload_source
assert 'return "pi"' in admin_upload_source
assert "splitter:{{shape:'circle'" in online_source
assert "pi:{{shape:'rect'" in online_source
assert "label:'I'" in online_source
assert "return 'DC';" in online_source
assert "return '3';" in online_source
assert "return '2';" in online_source
print("SPLITTER_PI_SYMBOL_MAPPING_OK")

# 실제 현장 블록 CN_C_Passive + 2SP-B/3SP-B는 저장된 generic/pi보다 우선해 원형 splitter로 렌더한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert 'block.startswith("2SP")' in admin_upload_source and 'block.startswith("3SP")' in admin_upload_source
assert "block.startsWith('2SP')" in online_source and "block.startsWith('3SP')" in online_source
assert "CMB 도면의 실제 layer/block code가 저장된 legacy symbol_kind보다 항상 우선한다." in online_source
assert "if(block.startsWith('3SP')" in online_source
assert "if(block.startsWith('2SP')" in online_source
print("SP_PASSIVE_SPLITTER_OVERRIDE_OK")

# 전체 심벌은 CMB 실제 layer/block code가 legacy 저장 kind보다 우선한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert 'layer.startswith("CN_C_ONU")' in admin_upload_source
assert 'layer.startswith("CN_C_AMP")' in admin_upload_source
assert 'layer.startswith("CN_C_TAP")' in admin_upload_source
assert 'block.startswith("2SP")' in admin_upload_source
assert 'block.startswith("3SP")' in admin_upload_source
assert 'layer.startswith("CN_C_DC")' in admin_upload_source
assert 'layer.startswith("CN_C_PI")' in admin_upload_source
assert 'layer.startswith("CN_C_POWER")' in admin_upload_source
assert "CMB 도면의 실제 layer/block code가 저장된 legacy symbol_kind보다 항상 우선한다." in online_source
assert "block.startsWith('2SP')" in online_source
assert "block.startsWith('3SP')" in online_source
assert "layer.startsWith('CN_C_DC')" in online_source
assert "layer.startsWith('CN_C_PI')" in online_source
assert "layer.startsWith('CN_C_POWER')" in online_source
print("CMB_CODE_FIRST_SYMBOL_MAPPING_OK")

# L3 동축은 주요기기 간 trunk만 표시하고 TAP 접속 케이블은 숨긴다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "function coaxCableOverlayKind(feature,devices)" in online_source
assert "if(connected.includes(cableHandle))return 'coax_tap_cable';" in online_source
assert "'coax_main_cable'" in online_source
assert "'coax_tap_cable'" in online_source
assert "if(mapLevel===3)" in online_source
assert "if(mapLevel===2)" in online_source

# Windows 온라인 Viewer 거리 측정: 새 구간, Esc 완료, 우클릭 개별삭제, 전체삭제.
assert "id='measureDistance'" in online_source
assert "id='clearDistance'" in online_source
assert "function addDistancePoint(latlng)" in online_source
assert "function finishDistanceMeasurement()" in online_source
assert "function clearAllDistanceMeasurements()" in online_source
assert "kakao.maps.event.addListener(session.line,'rightclick'" in online_source
assert "if(e.key==='Escape'&&distanceMode)" in online_source
assert "거리 측정 · 지도 클릭으로 점 추가 · Esc로 구간 완료" in online_source
print("L3_COAX_TRUNK_AND_DISTANCE_TOOL_OK")

# L3 TAP 구간은 거리 근접이 아니라 실제 _cmb_connections의 cable handle로만 숨긴다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "function coaxCableOverlayKind(feature,devices)" in online_source
assert "fields._cmb_connections" in online_source
assert "if(connected.includes(cableHandle))return 'coax_tap_cable';" in online_source
assert "coaxCableOverlayKind(f,devices)" in online_source

# L3에서는 TAP 기기와 TAP 입력화살표 모두 숨기고 주요기기 trunk만 남긴다.
l3_start = online_source.index("if(mapLevel===3)")
l3_end = online_source.index("if(mapLevel===2)", l3_start)
l3_block = online_source[l3_start:l3_end]
assert "'coax_main_cable'" in l3_block
assert "'tap_input_arrow'" not in l3_block
print("L3_TAP_HANDLE_FILTER_FIX_OK")

# 입력 화살표는 케이블 색상을 그대로 쓰고, 기기 주변의 작은 화살표만 표시한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "color:originalCableColor(lp,'COAX')" in online_source
assert "strokeColor:String(inferred.color||'#334155')" in online_source
assert "const base=[dev.cx-vx*12,dev.cy-vy*12];" in online_source
assert "const px=-vy,py=vx,wing=3;" in online_source
assert "strokeWeight:2" in online_source
print("INPUT_ARROW_COMPACT_CABLE_COLOR_OK")

# 상태 텍스트가 변해도 버튼 위치는 고정되어야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "id='toolButtons'" in online_source
assert "id='statusWrap'" in online_source
assert "flex:0 0 auto" in online_source
assert "flex:1 1 auto" in online_source
assert "text-overflow:ellipsis" in online_source
assert "white-space:nowrap" in online_source
print("FIXED_TOOLBAR_STATUS_LAYOUT_OK")

# Connector는 Windows Viewer에서 기기/선 표시 대상에서 제외한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "function isConnectorFeature(f)" in online_source
assert "layer.startsWith('CN_C_CONNECTOR')" in online_source
assert "block.startsWith('CONNECTOR')" in online_source
assert "block.startsWith('FO_VCONN')" in online_source
assert "block.startsWith('FO_VOCONN')" in online_source
assert "if(isConnectorFeature(f))return false;" in online_source
print("CONNECTOR_VIEWER_EXCLUSION_OK")

# 기기 심벌은 줌 레벨에 따라 크기가 변하고, 줌 변경은 API 없이 메모리 재렌더한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "function deviceScaleForLevel(level)" in online_source
assert "if(lv<=1)return 1.65;" in online_source
assert "if(lv===2)return 1.35;" in online_source
assert "if(lv===3)return 1.12;" in online_source
assert "return 0.90;" in online_source
assert "function fiberArrowScaleForLevel(level)" in online_source
assert "if(lv<=1)return 1.70;" in online_source
assert "if(lv===2)return 1.45;" in online_source
assert "if(lv===3)return 1.20;" in online_source
assert "return 1.00;" in online_source
assert "function redrawDevicesFromMemory()" in online_source
assert "function redrawFiberArrowsForZoom()" in online_source
assert "currentPointFeatures=pointFeatures.slice();" in online_source
assert "currentLineFeatures=lineFeatures.slice();" in online_source
assert "redrawDevicesFromMemory();" in online_source
assert "redrawFiberArrowsForZoom();" in online_source
assert "const edge=boundaryPoint(" in online_source
zoom_start = online_source.index("kakao.maps.event.addListener(map,'zoom_changed'")
zoom_end = online_source.index("centerMyLocation(false);", zoom_start)
zoom_block = online_source[zoom_start:zoom_end]
assert "apiCall('objects'" not in zoom_block
print("ZOOM_RESPONSIVE_DEVICE_SCALE_OK")

# 서버는 Point/LineString만 허용하므로 multipart CAD geometry는 업로드 시 개별 LineString으로 분리한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'geometries = [' in admin_upload_source
assert '{"type": "LineString", "coordinates": part}' in admin_upload_source
assert '"_cmb_geometry_part_index"' in admin_upload_source
assert '"_cmb_geometry_part_count"' in admin_upload_source
assert 'f"{base_object_id}_part{part_index:03d}"' in admin_upload_source
assert '"type": "MultiLineString"' not in admin_upload_source
print("SERVER_COMPATIBLE_SPLIT_LINESTRING_UPLOAD_OK")

# multipart 업로드는 서버 source_handle 유일성 제약을 만족하고 원본 CAD handle을 별도 보존한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'f"{original_handle}/part/{part_index:03d}"' in admin_upload_source
assert 'part_attrs["_cmb_original_handle"] = original_handle' in admin_upload_source
assert '"source_handle": source_handle' in admin_upload_source
print("UNIQUE_MULTIPART_SOURCE_HANDLE_OK")

# Windows 1.0 Rev1: 광은 전체 지역 완료를 기다리지 않고 현재 화면 bbox부터 스트리밍한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "FIBER_CACHE_SCHEMA = 2" in online_source
assert "def fiber_bbox(self, west, south, east, north, force=False):" in online_source
assert "def _fetch_fiber_bbox_network(self, west, south, east, north):" in online_source
assert "limit = 5000" in online_source
assert "max_depth = 14" in online_source
assert "layers=layer_filter" in online_source
assert "def _merge_fiber_bbox_cache(self, features):" in online_source
assert "function loadFiberViewport(force=false)" in online_source
assert "loadFiberViewport(false);" in online_source
assert "apiCall('polemap',query)" in online_source
assert "apiCall('fiber_cell'" in online_source
assert "cells.sort((a,b)" in online_source
assert "gridDiag.stage='GRID API';" in online_source
assert "gridDiag.progress='FIBER '+String(i+1)+'/'+String(cells.length)" in online_source
assert "refresh_pending" in online_source
assert "part_index = str(" in online_source
assert 'ident = f"{ident}|part={part_index}"' in online_source
print("FIBER_VIEWPORT_STREAMING_AND_PART_KEYS_OK")
assert 'polemap = self.polemap(west, south, east, north)' in online_source
assert 'polemap_cells": len(cells)' in online_source
assert 'self._read_object_cell_cache(grid_id)' in online_source
assert 'self._write_object_cell_cache(grid_id, version_signature, features)' in online_source
print("ALL_GROUP_POLEMAP_CELL_CACHE_OK")
assert "const visibleBounds=map.getBounds();" in online_source
assert "const latPad=(ne.getLat()-sw.getLat())*0.12;" in online_source
assert "gridDiag.stage='OBJECT 조회';" in online_source
assert "gridDiag.progress='COAX/CONDUIT/POLE';" in online_source
print("VISIBLE_VIEWPORT_OBJECT_QUERY_OK")

# 기존 광 캐시는 즉시 사용하고 현재 화면 새 수신분을 누적 병합한다.
assert "구버전 광 캐시도 즉시 화면에 사용한다." in online_source
assert "existing = {self._feature_key(f): f for f in self._fiber_features()}" in online_source
assert "existing[self._feature_key(feature)] = feature" in online_source
assert '"cache": "stale"' in online_source
print("FIBER_INCREMENTAL_CACHE_OK")

# 지역 선택 UI는 숨기고 지도 중심 bounds에 따라 권한 지역을 자동 전환한다.
assert "authorizedRegions=[]" in online_source
assert "function boundsContainsLatLng(bounds,latlng)" in online_source
assert "async function autoRegionForMapCenter()" in online_source
assert "async function activateRegion(region)" in online_source
assert "style='display:none'" in online_source
assert "지도 위치에 따라 자동 연결" in online_source
print("AUTO_REGION_BY_MAP_POSITION_OK")

# 케이블 선택 시 기기 위로 올려 강조하고 다른 선택/해제 시 원상복구한다.
assert "function selectCable(overlay,props,baseColor,baseWeight=4,baseZ=5)" in online_source
assert "function restoreSelectedCable()" in online_source
assert "overlay.setZIndex(60)" in online_source
assert "strokeWeight:Math.max(7,Number(baseWeight||4)+3)" in online_source
assert "bindCableClick(l,p,c,4,5)" in online_source
print("FIBER_SAFE_CACHE_AND_CABLE_SELECTION_OK")

# 전체 도면 업로드에서는 USER를 서버 전송 대상에서 제외한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'FULL_UPLOAD_ITEMS = ("FIBER", "COAX", "CONDUIT")' in admin_upload_source
full_line = [line for line in admin_upload_source.splitlines() if line.startswith("FULL_UPLOAD_ITEMS =")][0]
assert '"USER"' not in full_line
print("FULL_UPLOAD_EXCLUDES_USER_OK")

# 업로드 UI/POLE/Polemap 경량화 정책.
assert 'GROUPS = ("FIBER", "COAX", "CONDUIT", "POLE", "USER")' in admin_upload_source
assert 'MANAGED_ITEMS = GROUPS' in admin_upload_source
assert 'text="광 + 동축 + 관로 업로드"' in admin_upload_source
assert 'or layer.startswith("CN_L_POLEMAP_")' in admin_upload_source
assert 'entity_type == "INSERT" and (actual_pole_layer or actual_pole_block)' in admin_upload_source
assert "def build_polemap_payload(" in admin_upload_source
assert '"CN_L_POLEMAP_BOUND"' in admin_upload_source
assert '"CN_L_POLEMAP_IDXMAIN"' in admin_upload_source
assert "self.client.replace_polemap" in admin_upload_source
client_source = (root / "server_client_windows.py").read_text(encoding="utf-8")
assert "def replace_polemap(" in client_source
assert "def online_polemap(" in client_source
assert "def group_status_v2(" in client_source
print("POLEMAP_LIGHTWEIGHT_UPLOAD_OK")

# 모든 업로드 객체는 원본 CAD의 한전주 위치코드를 직접 보존해야 한다.
assert '_UPLOAD_POLE_CODE_RE = re.compile(' in admin_upload_source
assert r'\d{4}[A-Za-z]\d{3}' in admin_upload_source
assert 'def _upload_pole_refs(e):' in admin_upload_source
assert 'attrs["_cmb_pole_refs"] = pole_refs' in admin_upload_source
assert 'attrs["_cmb_pole_no"] = pole_refs[0]["pole_no"]' in admin_upload_source
assert 'attrs["_cmb_grid_id"] = pole_refs[0]["grid_id"]' in admin_upload_source
assert 'def _object_grid_ids(e):' in admin_upload_source
assert 'attrs["_cmb_grid_ids"] = object_grid_ids' in admin_upload_source
assert 'str(ref.get("grid_id") or "").upper()' in admin_upload_source
assert 'No nearest-pole/geometric inference is performed here.' in admin_upload_source
viewer_source = (root / "viewer.py").read_text(encoding="utf-8")
assert r'\d{4}[A-Za-z]\d{3}' in viewer_source
print("SOURCE_POLE_REFERENCE_PRESERVATION_OK")

# 업로드 단계에서 실제 POLE 좌표를 확정하고, 온라인 Viewer는 저장된 전주좌표를 직접 사용한다.
assert "def _build_pole_location_lookup(scene, transformer):" in admin_upload_source
assert "def _resolved_pole_refs(e, pole_lookup):" in admin_upload_source
assert 'attrs["_cmb_pole_position"] = {' in admin_upload_source
assert 'attrs["_cmb_position_source"] = "POLE"' in admin_upload_source
assert '"coordinates": [float(primary["lon"]), float(primary["lat"])]' in admin_upload_source
assert 'attrs["_cmb_original_point"] = list(original_point)' in admin_upload_source
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "function storedPolePosition(f)" in online_source
assert "const direct=fields._cmb_pole_position||{{}};" in online_source
assert "const refs=Array.isArray(fields._cmb_pole_refs)?fields._cmb_pole_refs:[];" in online_source
assert "const a=storedPolePosition(f);" in online_source
assert "Viewer에서는 최근접 전주/거리/공간연산을 하지 않는다." in online_source
print("DIRECT_STORED_POLE_POSITION_RENDER_OK")
assert "def _actual_pole_numbers(e):" in admin_upload_source
assert "pole_no = grid + str(local).zfill(3)" in admin_upload_source
assert "pole_numbers = _actual_pole_numbers(e)" in admin_upload_source
print("SPLIT_POLE_ID_COMBINATION_OK")
client_source = (root / "server_client_windows.py").read_text(encoding="utf-8")
assert "def online_grid_direct_objects(self, grid_id" in client_source
assert 'f"/online/grid/{g}/objects?limit={int(limit)}"' in client_source
assert "def online_grid_objects(self, region, grid_id" in client_source
assert 'f"/online/{q}/grid/{g}/objects?limit={int(limit)}"' in client_source
assert "return self.online_grid_direct_objects(" in client_source
assert "self.c.online_grid_objects(" in online_source
assert "grid_id," in online_source
print("DIRECT_GRID_ID_SERVER_LOOKUP_OK")

# 온라인 Viewer LOD: L5 셀경계, L4 셀번호, L3 광기기.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "kind==='cell_boundary'" in online_source
assert "mapLevel<=5" in online_source
assert "kind==='cell_number'" in online_source
assert "mapLevel<=4" in online_source
assert "function renderFiberPointFallback(features)" in online_source
assert "if(!map||map.getLevel()>3||!groupEnabled.FIBER)return 0;" in online_source
assert "광기기보강" in online_source
assert "셀번호" in online_source
print("FIBER_DEVICE_CELL_LOD_OK")
assert "strokeColor:isCellBoundary?'#f3a6bd':c" in online_source
assert "strokeStyle:isCellBoundary?'dash':'solid'" in online_source
viewer_source = (root / "viewer.py").read_text(encoding="utf-8")
assert 'optical_arrow_visible = lod >= layer_level("CN_F_CLOSURE")' in viewer_source
assert "primitive_index == arrow_primitive and optical_arrow_visible" in viewer_source
print("CELL_BOUNDARY_STYLE_AND_FIBER_ARROW_LOD_OK")

# 온라인 Viewer 초기 레이어는 광+동축을 동시에 활성화한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "const groupEnabled={{FIBER:true,COAX:true,POLE:false,CONDUIT:false,USER:false}};" in online_source
assert "<button class='layerBtn on' data-group='FIBER'>광</button>" in online_source
assert "<button class='layerBtn on' data-group='COAX'>동축</button>" in online_source
fiber_btn = online_source.index("data-group='FIBER'")
coax_btn = online_source.index("data-group='COAX'")
conduit_btn = online_source.index("data-group='CONDUIT'")
pole_btn = online_source.index("data-group='POLE'")
user_btn = online_source.index("data-group='USER'")
assert fiber_btn < coax_btn < conduit_btn < pole_btn < user_btn
print("DEFAULT_LAYER_ORDER_AND_USER_BUTTON_OK")


# 광기기는 Viewer 우회가 아니라 업로드 단계에서 실제 FIBER 그룹에 포함되어야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert 'fiber_device_block = (' in admin_upload_source
assert 'block.startswith("CLOSURE")' in admin_upload_source
assert 'block.startswith("TERMINAL")' in admin_upload_source
assert 'block.startswith("CENTER")' in admin_upload_source
assert 'block.startswith("FOSC")' in admin_upload_source
assert 'block.startswith("FDF")' in admin_upload_source
assert 'or fiber_device_block' in admin_upload_source
assert "function isFiberDeviceCode(p)" not in online_source
assert "if(String(p.group_id||'').toUpperCase()!=='FIBER')return;" in online_source
print("FIBER_DEVICE_UPLOAD_GROUP_OK")

# 광기기 Point는 줌 재렌더에서 삭제되지 않고 persistent 메모리로 다시 그려져야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "let currentFiberPointFeatures=[];" in online_source
assert "currentFiberPointFeatures=[...fiberDeviceMap.values()];" in online_source
assert "(currentFiberPointFeatures||[]).forEach" in online_source
assert "Fiber device redraw failed" in online_source
assert "광기기메모리" in online_source
print("FIBER_DEVICE_ZOOM_PERSISTENCE_OK")

# 추출/로컬 DXF Viewer는 온라인용 단순 심벌로 치환하지 않고 원본 CAD primitive를 표시한다.
viewer_source = (root / "viewer.py").read_text(encoding="utf-8")
assert "기기를 온라인용 단순 심벌로 치환하지 않는다" in viewer_source
assert "symbol_kind = _viewer_symbol_kind(ent)" not in viewer_source
assert "for primitive_index, (kind, data) in enumerate(ent.primitives):" in viewer_source
print("EXTRACTION_VIEWER_ORIGINAL_GEOMETRY_OK")

# 온라인 광기기 심벌은 block/layer 역할별로 구분하고, 셀번호/ONU 크기를 고정한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "fiber_terminal" in online_source
assert "fiber_rn" in online_source
assert "fiber_net" in online_source
assert "block.startsWith('NETOFD')" in online_source
assert "block.startsWith('NETFDF')" in online_source
assert "return 'OFD';" in online_source
assert "return 'FDF';" in online_source
assert "const baseFont=(kind==='fiber_net')?6.6" in online_source
assert "block.startsWith('RN-')" in online_source
assert "block.startsWith('SPL-')" in online_source
assert "font:700 22px Malgun Gothic;color:#d00000" in online_source
assert "onu:{{shape:'rect',w:38.4,h:19.2" in online_source
print("ONLINE_FIBER_SYMBOL_DIFFERENTIATION_OK")

# Closure는 짧은 함체 + 좌우 3개씩 총 6개 포트로 표시한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
assert "closure:{{shape:'closure_box',w:24,h:15" in online_source
assert "fill:'#DCEBFF',stroke:'#1F4E79'" in online_source
assert "portY=[-halfH*.46,0,halfH*.46]" in online_source
assert "portX=[-halfW+portInset,halfW-portInset]" in online_source
assert "leftA=rotatePoint" not in online_source
assert "rightB=rotatePoint" not in online_source
assert "fiber_terminal:{{shape:'rect',w:18,h:18" in online_source
assert "labelColor:'#ff1493'" in online_source
assert "return 'L2';" in online_source
assert "return 'L3';" in online_source
assert "kind!=='fiber_terminal' && kind!=='fiber_net'" in online_source
print("ONLINE_CLOSURE_INLINE_SHAPE_OK")

# 광케이블 입력방향 화살표, RN 라벨, 정보성 레이어 기본 OFF 정책을 고정한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
main_source = (root / "main.py").read_text(encoding="utf-8")
layer_defaults_source = (root / "layer_defaults.py").read_text(encoding="utf-8")
assert "function drawFiberInputArrow(path,color,cableOverlay,props)" in online_source
assert "registerOverlay(arrow,'FIBER','fiber_input_arrow')" in online_source
assert "if(kind==='fiber_rn')" in online_source
assert "block.startsWith('RN-8')" in online_source and "return '8RN'" in online_source
assert "block.startsWith('RN-4')" in online_source and "return '4RN'" in online_source
assert "shape:'text_only'" in online_source
assert "translate(-50%,-180%)" in online_source
assert "if not is_default_hidden(layer.name):" in main_source
assert "self.viewer.set_visible_layers(self.visible_layers)" in main_source
assert "_ID_SEGMENT_RE" in layer_defaults_source
assert "지번" in layer_defaults_source and "jibun" in layer_defaults_source
print("FIBER_ARROW_RN_AND_HIDDEN_INFO_OK")

# 하이브리드 지도, 강제 DXF 다시 읽기, 채워진 광 화살표+선택 연동을 고정한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
main_source = (root / "main.py").read_text(encoding="utf-8")
network_ui_source = (root / "network_extract_ui.py").read_text(encoding="utf-8")
drawing_cache_source = (root / "drawing_cache.py").read_text(encoding="utf-8")
assert "kakao.maps.MapTypeId.HYBRID" in online_source
assert "map.setMapTypeId" in online_source
assert "id='mapHybrid'" in online_source
assert "new kakao.maps.Polygon" in online_source
assert "fillColor:c" in online_source and "fiber_input_arrow" in online_source
assert "const cableArrows=new Map();" in online_source
assert "selectedCableArrows" in online_source
assert "selectCable(cableOverlay" in online_source
assert "def _force_reload_drawing(self):" in main_source
assert "force_refresh=True" in main_source
assert "text='도면 다시 읽기'" in network_ui_source
assert "force_refresh=False" in drawing_cache_source
assert "if not force_refresh:" in drawing_cache_source
print("HYBRID_FORCE_RELOAD_FILLED_ARROW_OK")
