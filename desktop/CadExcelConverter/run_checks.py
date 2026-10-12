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

def _e(layer, block=""):
    return SimpleNamespace(layer=layer, block_name=block)

assert classify_entity(_e("TS_BASEMAP")) is None
assert classify_entity(_e("TL_SCCO_SIG")) is None
assert classify_entity(_e("CN_F_CLOSURE")) == "FIBER"
assert classify_entity(_e("CN_C_ONU")) == "COAX"
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
print("MULTIPART_UPLOAD_GEOMETRY_OK")

# 온라인 Viewer는 광을 영구 캐시 레이어로 유지하고,
# L1~L3에서만 주변 기기/동축/전주/관로를 추가한다.
assert "FIBER:true,COAX:false,POLE:false,CONDUIT:false" in page
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
print("CROSS_PROCESS_SESSION_STATE_OK")


# 관로/맨홀/핸드홀은 CN_L_POLE 계열이어도 POLE보다 CONDUIT가 우선이어야 한다.
admin_upload_source = (root / "admin_upload.py").read_text(encoding="utf-8")
assert 'layer.startswith("CN_L_POLE_MANHOLE")' in admin_upload_source
assert 'layer.startswith("CN_L_POLE_HANDHOLE")' in admin_upload_source
assert 'layer.startswith("CN_L_POLE_LINE_")' in admin_upload_source
assert admin_upload_source.index('return "CONDUIT"') < admin_upload_source.index('return "POLE"')
print("CONDUIT_CLASSIFICATION_PRIORITY_OK")

# 지역 선택 자체는 서버를 기다리지 않고 로컬 캐시를 즉시 읽어야 한다.
online_source = (root / "online_viewer.py").read_text(encoding="utf-8")
select_block = online_source.split("    def select(self, region):", 1)[1].split("    def objects(", 1)[0]
assert "self._load_cache()" in select_block
assert "self._load_fiber_cache()" in select_block
assert "self.c.online_versions(self.region)" not in select_block
assert "def cached_fiber(self):" in online_source
assert 'name == "fiber_cached"' in online_source
print("FAST_CACHE_VERSION_CHECK_OK")


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
