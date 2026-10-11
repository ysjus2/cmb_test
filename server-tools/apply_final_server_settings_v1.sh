#!/usr/bin/env bash
set -euo pipefail

# CMB FINAL server settings patch
# One FastAPI app + one main DB.
# Adds shared map display settings to the existing server only.

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-server}"
APP_DIR="${CMB_APP_DIR:-/opt/cmb-server}"
ENV_FILE="${CMB_ENV_FILE:-/etc/cmb-server.env}"
BACKUP_DIR="${CMB_BACKUP_DIR:-/opt/cmb-backups}"
PATCH_MODULE="cmb_final_settings.py"
MARK_BEGIN="# === CMB_FINAL_SETTINGS_V1_BEGIN ==="

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

DB_PATH="${CMB_DB_PATH:-/var/lib/cmb-server/cmb.sqlite3}"
mkdir -p "${BACKUP_DIR}" "$(dirname "${DB_PATH}")"

echo "[1/8] 현재 서버 진입점 확인"
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
  echo "ERROR: 현재 FastAPI 진입 파일을 찾지 못했습니다."
  echo "ExecStart=${EXEC_START}"
  exit 1
fi
ENTRY_FILE="${APP_DIR}/${ENTRY_MODULE}.py"
echo "ENTRY=${ENTRY_FILE}"
echo "DB=${DB_PATH}"

echo "[2/8] 현재 서버/DB 백업"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${BACKUP_DIR}/cmb-final-settings-${STAMP}.tgz"
FILES_TO_BACKUP=("$(basename "${ENTRY_FILE}")")
[[ -f "${APP_DIR}/${PATCH_MODULE}" ]] && FILES_TO_BACKUP+=("${PATCH_MODULE}")
tar -C "${APP_DIR}" -czf "${BACKUP}" "${FILES_TO_BACKUP[@]}"
if [[ -f "${DB_PATH}" ]]; then
  cp -a "${DB_PATH}" "${BACKUP_DIR}/cmb-main-db-${STAMP}.sqlite3"
fi

restore_backup() {
  echo "ROLLBACK: 서버 파일 복구"
  tar -C "${APP_DIR}" -xzf "${BACKUP}" || true
  systemctl restart "${SERVICE_NAME}" || true
}
trap 'echo "ERROR: 적용 실패"; restore_backup' ERR

echo "[3/8] 최종 공통 설정 모듈 설치"
cat > "${APP_DIR}/${PATCH_MODULE}" <<'PY'
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import ssl
import urllib.error
import urllib.request
import time
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("CMB_DB_PATH", "/var/lib/cmb-server/cmb.sqlite3"))
DEFAULT_RADIUS_M = 500
DEFAULT_REFRESH_M = 200


class MapDisplaySettings(BaseModel):
    radius_m: int = Field(DEFAULT_RADIUS_M, ge=100, le=3000)
    refresh_distance_m: int = Field(DEFAULT_REFRESH_M, ge=25, le=1500)


class SymbolPackage(BaseModel):
    region_code: str
    source_file: str = ""
    source_sha256: str = ""
    package_sha256: str = ""
    memo: str = ""
    symbol_count: int = 0
    symbols: list[dict] = Field(default_factory=list)


def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS symbol_revisions(
          id TEXT PRIMARY KEY,
          region_code TEXT NOT NULL,
          revision INTEGER NOT NULL,
          source_file TEXT,
          source_sha256 TEXT,
          package_sha256 TEXT,
          symbol_count INTEGER NOT NULL DEFAULT 0,
          memo TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          UNIQUE(region_code, revision)
        );
        CREATE INDEX IF NOT EXISTS idx_symbol_revisions_active
          ON symbol_revisions(region_code, active);

        CREATE TABLE IF NOT EXISTS symbol_defs(
          revision_id TEXT NOT NULL,
          symbol_key TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          PRIMARY KEY(revision_id, symbol_key)
        );
        CREATE INDEX IF NOT EXISTS idx_symbol_defs_revision
          ON symbol_defs(revision_id);
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
            "WHERE key IN ('map_radius_m','map_refresh_distance_m')"
        ).fetchall()
    for row in rows:
        try:
            if row["key"] == "map_radius_m":
                values["radius_m"] = int(row["value"])
            elif row["key"] == "map_refresh_distance_m":
                values["refresh_distance_m"] = int(row["value"])
        except Exception:
            pass

    radius = max(100, min(3000, int(values["radius_m"])))
    refresh = max(25, min(radius, 1500, int(values["refresh_distance_m"])))
    return {
        "radius_m": radius,
        "refresh_distance_m": refresh,
    }


def _write_settings(radius_m: int, refresh_distance_m: int):
    radius = max(100, min(3000, int(radius_m)))
    refresh = max(25, min(radius, 1500, int(refresh_distance_m)))
    with _db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('map_radius_m',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(radius),),
        )
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('map_refresh_distance_m',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(refresh),),
        )
    return {
        "radius_m": radius,
        "refresh_distance_m": refresh,
    }


def _has_route(app, path: str, method: str):
    method = method.upper()
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) != path:
            continue
        methods = set(getattr(route, "methods", set()) or set())
        if method in methods:
            return True
    return False


def _find_probe(app, candidates, method="GET"):
    for path in candidates:
        if _has_route(app, path, method):
            return path
    return None


def _forward_headers(request: Request):
    headers = {"Accept": "application/json"}
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
            return int(resp.status), resp.read(4096)
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
        detail = ""
        try:
            data = json.loads(body.decode("utf-8", "replace"))
            detail = str(data.get("detail") or data.get("error") or "")
        except Exception:
            pass
        raise HTTPException(status, detail or f"기존 인증 확인 실패 ({status})")


def install_final_settings(app):
    user_probe = _find_probe(app, ("/session/policy", "/regions"), "GET")
    admin_probe = _find_probe(
        app,
        (
            "/admin/settings/session-timeout",
            "/admin/settings/backup-retention",
        ),
        "GET",
    )
    if not user_probe:
        raise RuntimeError("기존 사용자 인증 확인 API를 찾지 못했습니다.")
    if not admin_probe:
        raise RuntimeError("기존 관리자 인증 확인 API를 찾지 못했습니다.")

    # Same main DB. No sidecar DB.
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

    if not _has_route(app, "/admin/drawings/{region}/symbols", "GET"):
        @app.get("/admin/drawings/{region}/symbols")
        async def cmb_get_symbols(region: str, request: Request):
            await _require_existing_auth(request, admin_probe)
            region = str(region or "").strip().upper()
            with _db() as conn:
                rev = conn.execute(
                    "SELECT * FROM symbol_revisions "
                    "WHERE region_code=? AND active=1 "
                    "ORDER BY revision DESC LIMIT 1",
                    (region,),
                ).fetchone()
                if not rev:
                    return {
                        "group_id": "SYMBOL",
                        "region_code": region,
                        "revision": None,
                        "symbol_count": 0,
                        "symbols": [],
                    }
                rows = conn.execute(
                    "SELECT payload_json FROM symbol_defs "
                    "WHERE revision_id=? ORDER BY symbol_key",
                    (rev["id"],),
                ).fetchall()
            return {
                "group_id": "SYMBOL",
                "region_code": region,
                "revision": int(rev["revision"]),
                "revision_id": rev["id"],
                "symbol_count": int(rev["symbol_count"]),
                "memo": rev["memo"],
                "symbols": [
                    json.loads(row["payload_json"])
                    for row in rows
                ],
            }

    if not _has_route(app, "/admin/drawings/{region}/symbols", "POST"):
        @app.post("/admin/drawings/{region}/symbols")
        async def cmb_upload_symbols(
            region: str,
            package: SymbolPackage,
            request: Request,
        ):
            await _require_existing_auth(request, admin_probe)
            region = str(region or "").strip().upper()
            payload_region = str(package.region_code or "").strip().upper()
            if region != payload_region:
                raise HTTPException(400, "지역코드가 일치하지 않습니다.")
            if package.symbol_count != len(package.symbols):
                raise HTTPException(400, "symbol_count와 symbols 길이가 다릅니다.")

            prepared = {}
            for item in package.symbols:
                key = str(item.get("key") or "").strip()
                if not key:
                    raise HTTPException(400, "key가 없는 심볼 정의가 있습니다.")
                prepared[key] = item

            with _db() as conn:
                last = conn.execute(
                    "SELECT COALESCE(MAX(revision),0) "
                    "FROM symbol_revisions WHERE region_code=?",
                    (region,),
                ).fetchone()[0]
                revision = int(last) + 1
                revision_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO symbol_revisions("
                    "id,region_code,revision,source_file,source_sha256,"
                    "package_sha256,symbol_count,memo,active,created_at"
                    ") VALUES(?,?,?,?,?,?,?,?,0,?)",
                    (
                        revision_id,
                        region,
                        revision,
                        package.source_file,
                        package.source_sha256,
                        package.package_sha256,
                        len(prepared),
                        package.memo,
                        int(time.time()),
                    ),
                )
                for key, item in prepared.items():
                    conn.execute(
                        "INSERT INTO symbol_defs("
                        "revision_id,symbol_key,payload_json"
                        ") VALUES(?,?,?)",
                        (
                            revision_id,
                            key,
                            json.dumps(item, ensure_ascii=False),
                        ),
                    )
                conn.execute(
                    "UPDATE symbol_revisions SET active=0 "
                    "WHERE region_code=?",
                    (region,),
                )
                conn.execute(
                    "UPDATE symbol_revisions SET active=1 WHERE id=?",
                    (revision_id,),
                )
            return {
                "ok": True,
                "group_id": "SYMBOL",
                "region_code": region,
                "revision": revision,
                "revision_id": revision_id,
                "symbol_count": len(prepared),
                "active": True,
            }

    if not _has_route(app, "/admin/drawings/{region}/symbol-revisions", "GET"):
        @app.get("/admin/drawings/{region}/symbol-revisions")
        async def cmb_symbol_revisions(region: str, request: Request):
            await _require_existing_auth(request, admin_probe)
            region = str(region or "").strip().upper()
            with _db() as conn:
                rows = conn.execute(
                    "SELECT id,revision,source_file,source_sha256,"
                    "package_sha256,symbol_count,memo,active,created_at "
                    "FROM symbol_revisions WHERE region_code=? "
                    "ORDER BY revision DESC",
                    (region,),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "group_id": "SYMBOL",
                    "revision": int(row["revision"]),
                    "source_file": row["source_file"],
                    "source_sha256": row["source_sha256"],
                    "package_sha256": row["package_sha256"],
                    "object_count": int(row["symbol_count"]),
                    "symbol_count": int(row["symbol_count"]),
                    "memo": row["memo"],
                    "active": bool(row["active"]),
                    "created_at": int(row["created_at"]),
                }
                for row in rows
            ]

    if not _has_route(
        app,
        "/admin/drawings/{region}/symbol-revisions/{revision_id}/restore",
        "POST",
    ):
        @app.post(
            "/admin/drawings/{region}/symbol-revisions/{revision_id}/restore"
        )
        async def cmb_restore_symbol_revision(
            region: str,
            revision_id: str,
            request: Request,
        ):
            await _require_existing_auth(request, admin_probe)
            region = str(region or "").strip().upper()
            with _db() as conn:
                row = conn.execute(
                    "SELECT id,revision FROM symbol_revisions "
                    "WHERE id=? AND region_code=?",
                    (revision_id, region),
                ).fetchone()
                if not row:
                    raise HTTPException(404, "심볼 백업을 찾을 수 없습니다.")
                conn.execute(
                    "UPDATE symbol_revisions SET active=0 "
                    "WHERE region_code=?",
                    (region,),
                )
                conn.execute(
                    "UPDATE symbol_revisions SET active=1 WHERE id=?",
                    (revision_id,),
                )
            return {
                "ok": True,
                "group_id": "SYMBOL",
                "region_code": region,
                "revision": int(row["revision"]),
                "revision_id": revision_id,
                "active": True,
            }

    return {
        "db_path": str(DB_PATH),
        "user_probe": user_probe,
        "admin_probe": admin_probe,
        "settings": _read_settings(),
    }
PY

echo "[4/8] 현재 ASGI 앱에 설정 라우트 병합"
if ! grep -Fq "${MARK_BEGIN}" "${ENTRY_FILE}"; then
cat >> "${ENTRY_FILE}" <<'PY'

# === CMB_FINAL_SETTINGS_V1_BEGIN ===
# Final shared Windows/Android settings on the same CMB main DB.
from cmb_final_settings import install_final_settings as _cmb_install_final_settings
_CMB_FINAL_SETTINGS_INFO = _cmb_install_final_settings(app)
# === CMB_FINAL_SETTINGS_V1_END ===
PY
else
  echo "기존 CMB_FINAL_SETTINGS_V1 병합 코드 유지"
fi

PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

echo "[5/8] 문법 검사"
"${PYTHON_BIN}" -m py_compile   "${ENTRY_FILE}"   "${APP_DIR}/${PATCH_MODULE}"
echo "PY_COMPILE_OK"

echo "[6/8] 실제 ASGI 라우트 + 메인 DB 확인"
(
  cd "${APP_DIR}"
  CMB_DB_PATH="${DB_PATH}" PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" - <<PY
import importlib
import sqlite3

m = importlib.import_module("${ENTRY_MODULE}")
app = getattr(m, "app")

required = {
    ("/settings/map-display", "GET"),
    ("/admin/settings/map-display", "GET"),
    ("/admin/settings/map-display", "POST"),
    ("/admin/drawings/{region}/symbols", "GET"),
    ("/admin/drawings/{region}/symbols", "POST"),
    ("/admin/drawings/{region}/symbol-revisions", "GET"),
    ("/admin/drawings/{region}/symbol-revisions/{revision_id}/restore", "POST"),
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

info = getattr(m, "_CMB_FINAL_SETTINGS_INFO", {})
print("FINAL_SETTINGS_INFO", info)
if str(info.get("db_path")) != "${DB_PATH}":
    raise SystemExit("WRONG_DB_PATH=" + repr(info))

with sqlite3.connect("${DB_PATH}") as conn:
    names = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if "settings" not in names:
        raise SystemExit("SETTINGS_TABLE_MISSING")

print("ONE_MAIN_DB_OK")
print("ASGI_FINAL_SETTINGS_OK")
PY
)

echo "[7/8] 서버 재시작"
systemctl restart "${SERVICE_NAME}"
for i in {1..15}; do
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  journalctl -u "${SERVICE_NAME}" -n 100 --no-pager || true
  false
fi

echo "[8/8] 최종 상태"
CMB_DB_PATH="${DB_PATH}" "${PYTHON_BIN}" - <<'PY'
import os
import sqlite3

db = os.environ["CMB_DB_PATH"]
with sqlite3.connect(db) as conn:
    rows = dict(
        conn.execute(
            "SELECT key,value FROM settings "
            "WHERE key IN ('map_radius_m','map_refresh_distance_m')"
        ).fetchall()
    )
print("MAIN_DB", db)
print("map_radius_m", rows.get("map_radius_m", "500"))
print("map_refresh_distance_m", rows.get("map_refresh_distance_m", "200"))
PY

trap - ERR

echo
echo "============================================================"
echo "CMB 최종 서버 설정 적용 완료"
echo "- 서버 앱: 1개"
echo "- 메인 DB: ${DB_PATH}"
echo "- 별도 지도 설정 DB: 없음"
echo "- 표시 반경 기본값: 500m"
echo "- 재조회 거리 기본값: 200m"
echo "- Windows / Android 공통 설정"
echo "- 지역별 6개 관리: FIBER / COAX / POLE / CONDUIT / USER / SYMBOL"
echo "- SYMBOL은 일반 도면 객체와 분리된 전용 Revision"
echo "- 기존 로그인/권한/도면/백업 API 유지"
echo "- 백업: ${BACKUP}"
echo "============================================================"
echo "CMB_FINAL_SERVER_SETTINGS_V1"
