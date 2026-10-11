#!/usr/bin/env bash
set -euo pipefail

# CMB map-display settings hot patch
# - preserves current server/auth/drawing code
# - adds shared radius/refresh settings for Windows + Android
# - auto backup / syntax check / route check / service restart / rollback

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-server}"
APP_DIR="${CMB_APP_DIR:-/opt/cmb-server}"
DATA_DIR="${CMB_DATA_DIR:-/var/lib/cmb-server}"
ENV_FILE="${CMB_ENV_FILE:-/etc/cmb-server.env}"
BACKUP_DIR="${CMB_BACKUP_DIR:-/opt/cmb-backups}"
PATCH_MODULE="cmb_map_display_patch.py"
MARK_BEGIN="# === CMB_MAP_DISPLAY_PATCH_V1_BEGIN ==="
MARK_END="# === CMB_MAP_DISPLAY_PATCH_V1_END ==="

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash $0 로 실행해주세요."
  exit 1
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}" || true
  set +a
fi

mkdir -p "${APP_DIR}" "${DATA_DIR}" "${BACKUP_DIR}"

echo "[1/8] 실행 중인 CMB 서버 진입점 확인"
EXEC_START="$(systemctl show -p ExecStart --value "${SERVICE_NAME}" 2>/dev/null || true)"
WORK_DIR="$(systemctl show -p WorkingDirectory --value "${SERVICE_NAME}" 2>/dev/null || true)"
[[ -n "${WORK_DIR}" && "${WORK_DIR}" != "[not set]" ]] && APP_DIR="${WORK_DIR}"

ENTRY_MODULE=""
if [[ "${EXEC_START}" =~ ([A-Za-z_][A-Za-z0-9_]*):app ]]; then
  ENTRY_MODULE="${BASH_REMATCH[1]}"
fi
if [[ -z "${ENTRY_MODULE}" ]]; then
  for candidate in cmb_asgi app main; do
    if [[ -f "${APP_DIR}/${candidate}.py" ]]; then
      ENTRY_MODULE="${candidate}"
      break
    fi
  done
fi
if [[ -z "${ENTRY_MODULE}" || ! -f "${APP_DIR}/${ENTRY_MODULE}.py" ]]; then
  echo "ERROR: FastAPI 진입 파일을 찾지 못했습니다."
  echo "ExecStart=${EXEC_START}"
  echo "APP_DIR=${APP_DIR}"
  exit 1
fi
ENTRY_FILE="${APP_DIR}/${ENTRY_MODULE}.py"
echo "ENTRY=${ENTRY_FILE}"

echo "[2/8] 기존 서버 백업"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${BACKUP_DIR}/cmb-map-display-${STAMP}.tgz"
tar -C "${APP_DIR}" -czf "${BACKUP}"   "$(basename "${ENTRY_FILE}")"   "${PATCH_MODULE}" 2>/dev/null || tar -C "${APP_DIR}" -czf "${BACKUP}" "$(basename "${ENTRY_FILE}")"
echo "BACKUP=${BACKUP}"

restore_backup() {
  echo "ROLLBACK: 서버 파일 복구"
  tar -C "${APP_DIR}" -xzf "${BACKUP}" || true
  systemctl restart "${SERVICE_NAME}" || true
}
trap 'echo "ERROR: 적용 실패"; restore_backup' ERR

echo "[3/8] 지도 표시 설정 라우터 설치"
cat > "${APP_DIR}/${PATCH_MODULE}" <<'PY'
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import ssl
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

DB_PATH = Path(
    os.environ.get(
        "CMB_MAP_DISPLAY_DB",
        "/var/lib/cmb-server/map_display.sqlite3",
    )
)
DEFAULT_RADIUS_M = 500
DEFAULT_REFRESH_M = 200


class MapDisplaySettings(BaseModel):
    radius_m: int = Field(DEFAULT_RADIUS_M, ge=100, le=3000)
    refresh_distance_m: int = Field(DEFAULT_REFRESH_M, ge=25, le=1500)


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
        """
    )
    return conn


def _read_settings():
    values = {
        "radius_m": DEFAULT_RADIUS_M,
        "refresh_distance_m": DEFAULT_REFRESH_M,
    }
    with _db() as conn:
        rows = conn.execute(
            "SELECT key,value FROM settings "
            "WHERE key IN ('radius_m','refresh_distance_m')"
        ).fetchall()
    for row in rows:
        try:
            values[row["key"]] = int(row["value"])
        except Exception:
            pass
    radius = max(100, min(3000, int(values["radius_m"])))
    refresh = max(
        25,
        min(radius, 1500, int(values["refresh_distance_m"])),
    )
    return {
        "radius_m": radius,
        "refresh_distance_m": refresh,
    }


def _write_settings(radius_m: int, refresh_distance_m: int):
    radius = max(100, min(3000, int(radius_m)))
    refresh = max(25, min(radius, 1500, int(refresh_distance_m)))
    with _db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('radius_m',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(radius),),
        )
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('refresh_distance_m',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(refresh),),
        )
    return {
        "radius_m": radius,
        "refresh_distance_m": refresh,
    }


def _route_methods(app, path: str):
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) == path:
            return set(getattr(route, "methods", set()) or set())
    return set()


def _has_route(app, path: str, method: str):
    return method.upper() in _route_methods(app, path)


def _find_probe(app, candidates, method="GET"):
    for path in candidates:
        if _has_route(app, path, method):
            return path
    return None


def _forward_headers(request: Request):
    headers = {
        "Accept": "application/json",
        "User-Agent": "cmb-map-display-auth-probe/1",
    }
    auth = request.headers.get("authorization")
    if auth:
        headers["Authorization"] = auth
    cookie = request.headers.get("cookie")
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _probe_sync(url: str, headers: dict):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            status = int(resp.status)
            body = resp.read(4096)
            return status, body
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(4096)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"기존 서버 인증 확인 실패: {exc}",
        ) from exc


async def _require_existing_auth(request: Request, probe_path: str):
    base = str(request.base_url).rstrip("/")
    status, body = await asyncio.to_thread(
        _probe_sync,
        base + probe_path,
        _forward_headers(request),
    )
    if status == 401:
        raise HTTPException(401, "로그인이 만료됐습니다. 다시 로그인해주세요.")
    if status == 403:
        raise HTTPException(403, "권한이 없습니다.")
    if status < 200 or status >= 300:
        message = ""
        try:
            data = json.loads(body.decode("utf-8", "replace"))
            message = str(data.get("detail") or data.get("error") or "")
        except Exception:
            pass
        raise HTTPException(
            status,
            message or f"기존 인증 확인 실패 ({status})",
        )


def install_map_display_routes(app):
    user_probe = _find_probe(
        app,
        ("/session/policy", "/regions"),
        "GET",
    )
    admin_probe = _find_probe(
        app,
        (
            "/admin/settings/session-timeout",
            "/admin/settings/backup-retention",
        ),
        "GET",
    )

    if not user_probe:
        raise RuntimeError(
            "일반 사용자 인증 확인용 기존 API(/session/policy 또는 /regions)가 없습니다."
        )
    if not admin_probe:
        raise RuntimeError(
            "관리자 인증 확인용 기존 설정 API가 없습니다."
        )

    # DB와 기본값을 먼저 검증/초기화한다.
    _write_settings(**_read_settings())

    if not _has_route(app, "/settings/map-display", "GET"):
        @app.get("/settings/map-display")
        async def cmb_map_display_settings(request: Request):
            await _require_existing_auth(request, user_probe)
            return _read_settings()

    if not _has_route(app, "/admin/settings/map-display", "GET"):
        @app.get("/admin/settings/map-display")
        async def cmb_admin_map_display_settings(request: Request):
            await _require_existing_auth(request, admin_probe)
            return _read_settings()

    if not _has_route(app, "/admin/settings/map-display", "POST"):
        @app.post("/admin/settings/map-display")
        async def cmb_set_admin_map_display_settings(
            settings: MapDisplaySettings,
            request: Request,
        ):
            await _require_existing_auth(request, admin_probe)
            return _write_settings(
                settings.radius_m,
                settings.refresh_distance_m,
            )

    return {
        "user_probe": user_probe,
        "admin_probe": admin_probe,
        "settings": _read_settings(),
    }
PY

echo "[4/8] ASGI 진입 파일에 안전 병합 코드 적용"
if ! grep -Fq "${MARK_BEGIN}" "${ENTRY_FILE}"; then
  cat >> "${ENTRY_FILE}" <<'PY'

# === CMB_MAP_DISPLAY_PATCH_V1_BEGIN ===
# Shared Windows/Android map-display settings.
from cmb_map_display_patch import install_map_display_routes as _cmb_install_map_display_routes
_CMB_MAP_DISPLAY_PATCH_INFO = _cmb_install_map_display_routes(app)
# === CMB_MAP_DISPLAY_PATCH_V1_END ===
PY
else
  echo "기존 CMB_MAP_DISPLAY_PATCH_V1 병합 코드를 유지합니다."
fi

echo "[5/8] Python 문법 검사"
PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"
"${PYTHON_BIN}" -m py_compile   "${ENTRY_FILE}"   "${APP_DIR}/${PATCH_MODULE}"
echo "PY_COMPILE_OK"

echo "[6/8] 실제 ASGI 라우트 검사"
(
  cd "${APP_DIR}"
  PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" - <<PY
import importlib
m = importlib.import_module("${ENTRY_MODULE}")
app = getattr(m, "app")
required = {
    ("/settings/map-display", "GET"),
    ("/admin/settings/map-display", "GET"),
    ("/admin/settings/map-display", "POST"),
}
actual = set()
for route in app.routes:
    path = getattr(route, "path", "")
    for method in (getattr(route, "methods", None) or []):
        actual.add((path, method))
missing = sorted(required - actual)
print("MAP_DISPLAY_ROUTES", sorted(x for x in actual if "map-display" in x[0]))
if missing:
    raise SystemExit("MISSING_ROUTES=" + repr(missing))
info = getattr(m, "_CMB_MAP_DISPLAY_PATCH_INFO", {})
print("AUTH_PROBES", info)
print("ASGI_MAP_DISPLAY_ROUTE_OK")
PY
)

echo "[7/8] 서비스 재시작 및 상태 확인"
systemctl restart "${SERVICE_NAME}"
for i in {1..15}; do
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
  false
fi

echo "[8/8] 보호 상태 확인"
# 인증 없이 접근했을 때 200이면 보안 문제이므로 실패 처리한다.
SERVER_IP="${CMB_SERVER_IP:-192.168.246.54}"
HTTP_CODE="$(curl -k -s -o /tmp/cmb_map_display_probe.out -w '%{http_code}'   "https://${SERVER_IP}:8443/settings/map-display" || true)"
echo "UNAUTH_GET_STATUS=${HTTP_CODE}"
if [[ "${HTTP_CODE}" == "200" ]]; then
  echo "ERROR: 인증 없이 지도 설정 API가 열렸습니다."
  false
fi

trap - ERR

echo
echo "============================================================"
echo "적용 완료"
echo "- 기존 서버/인증/도면 API 유지"
echo "- GET  /settings/map-display"
echo "- GET  /admin/settings/map-display"
echo "- POST /admin/settings/map-display"
echo "- 기본 표시 반경: 500m"
echo "- 기본 재조회 거리: 200m"
echo "- 설정 DB: /var/lib/cmb-server/map_display.sqlite3"
echo "- 백업: ${BACKUP}"
echo "============================================================"
echo "CMB_MAP_DISPLAY_PATCH_V1"
