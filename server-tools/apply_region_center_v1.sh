#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash 로 실행해주세요."
  exit 1
fi

MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE_NAME}")"
WORK_DIR="$(systemctl show -p WorkingDirectory --value "${SERVICE_NAME}")"
[[ -n "${WORK_DIR}" && "${WORK_DIR}" != "[not set]" ]] || WORK_DIR="/srv/CMB_Network/app"
APP_DIR="${CMB_APP_DIR:-${WORK_DIR}}"
ENTRY_FILE="${APP_DIR}/cmb_asgi.py"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

if [[ -z "${MAIN_PID}" || "${MAIN_PID}" == "0" || ! -r "/proc/${MAIN_PID}/environ" ]]; then
  echo "ERROR: 실행 중인 서버 환경을 읽을 수 없습니다."
  exit 2
fi

while IFS= read -r -d '' item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/srv/CMB_Network/app/backups"
[[ -d "/srv/CMB_Network/app" ]] || BACKUP_DIR="/home/ysjus/cmb-server-backups"
mkdir -p "${BACKUP_DIR}"
BACKUP="${BACKUP_DIR}/cmb-before-region-center-${STAMP}.tgz"

echo "[1/7] 서버 파일 백업"
tar -C "${APP_DIR}" -czf "${BACKUP}" "$(basename "${ENTRY_FILE}")" 2>/dev/null || true
echo "BACKUP=${BACKUP}"

echo "[2/7] regions 중심 좌표 컬럼 추가"
"${PYTHON_BIN}" - <<'PY'
import os

def connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception:
        import psycopg2
        return psycopg2.connect(dsn or "")

with connect() as conn:
    cur = conn.cursor()
    cur.execute("ALTER TABLE regions ADD COLUMN IF NOT EXISTS center_lat DOUBLE PRECISION")
    cur.execute("ALTER TABLE regions ADD COLUMN IF NOT EXISTS center_lon DOUBLE PRECISION")
    conn.commit()
print("REGION_CENTER_COLUMNS_OK")
PY

echo "[3/7] 지역 중심 저장/조회 패치 설치"
cat > "${APP_DIR}/cmb_region_center_patch.py" <<'PY'
from __future__ import annotations

import hashlib
import os
import re

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel


def _connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception:
        import psycopg2
        return psycopg2.connect(dsn or "")


def _token_user(request: Request):
    auth = str(request.headers.get("authorization") or "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id,u.username,u.level,u.active
            FROM auth_sessions s
            JOIN app_users u ON u.id=s.user_id
            WHERE s.access_hash=%s
              AND s.revoked=FALSE
              AND s.access_expires>NOW()
              AND u.active=TRUE
            ORDER BY s.id DESC
            LIMIT 1
        """, (token_hash,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다.")
    return {"id": row[0], "username": row[1], "level": int(row[2])}


def _admin_user(request: Request):
    user = _token_user(request)
    if user["level"] != 1:
        raise HTTPException(status_code=403, detail="1등급 관리자만 사용할 수 있습니다.")
    return user


def _safe_region_id(region_id: str) -> str:
    rid = str(region_id or "").strip()
    if not rid or len(rid) > 200 or not re.fullmatch(r"[A-Za-z0-9_.-]+", rid):
        raise HTTPException(status_code=400, detail="잘못된 지역코드입니다.")
    return rid


def _route_exists(app, path, method):
    method = method.upper()
    return any(
        getattr(r, "path", None) == path
        and method in (getattr(r, "methods", None) or set())
        for r in getattr(app, "routes", [])
    )


class RegionCenterBody(BaseModel):
    center_lat: float
    center_lon: float


def install(app):
    if not _route_exists(app, "/admin/regions/{region_id}/center", "POST"):
        @app.post("/admin/regions/{region_id}/center")
        async def update_region_center(region_id: str, body: RegionCenterBody, request: Request):
            _admin_user(request)
            rid = _safe_region_id(region_id)
            lat = float(body.center_lat)
            lon = float(body.center_lon)
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise HTTPException(status_code=400, detail="지역 중심 좌표가 올바르지 않습니다.")

            with _connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE regions SET center_lat=%s, center_lon=%s WHERE id=%s",
                    (lat, lon, rid),
                )
                if cur.rowcount != 1:
                    raise HTTPException(status_code=404, detail="지역을 찾을 수 없습니다.")
                conn.commit()

            return {
                "ok": True,
                "id": rid,
                "center_lat": lat,
                "center_lon": lon,
            }

    @app.middleware("http")
    async def cmb_region_center_config(request: Request, call_next):
        if (
            request.url.path == "/regions"
            and request.query_params.get("client_config") == "region_centers"
        ):
            # 기존 /regions 체인을 먼저 통과시켜 세션/기기/권한 검사를 그대로 유지한다.
            probe = await call_next(request)
            if probe.status_code != 200:
                return probe

            user = _token_user(request)
            with _connect() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT r.id,r.center_lat,r.center_lon
                    FROM user_regions ur
                    JOIN regions r ON r.id=ur.region_id
                    WHERE ur.user_id=%s
                    ORDER BY r.id
                """, (user["id"],))
                rows = cur.fetchall()

            centers = {}
            for rid, lat, lon in rows:
                if lat is None or lon is None:
                    continue
                centers[str(rid)] = {
                    "center_lat": float(lat),
                    "center_lon": float(lon),
                }
            return JSONResponse({"centers": centers})

        return await call_next(request)
PY

echo "[4/7] cmb_asgi.py 연결"
"${PYTHON_BIN}" - <<PY
from pathlib import Path
import re
p=Path(r"${ENTRY_FILE}")
text=p.read_text(encoding="utf-8")
block='''# === CMB_REGION_CENTER_PATCH_V1_BEGIN ===
try:
    import cmb_region_center_patch
    cmb_region_center_patch.install(app)
except Exception as exc:
    print("CMB_REGION_CENTER_PATCH_ERROR", repr(exc))
# === CMB_REGION_CENTER_PATCH_V1_END ===
'''
text=re.sub(
    r"\n?# === CMB_REGION_CENTER_PATCH_V1_BEGIN ===.*?# === CMB_REGION_CENTER_PATCH_V1_END ===\n?",
    "\n",
    text,
    flags=re.S,
)
p.write_text(text.rstrip()+"\n\n"+block, encoding="utf-8")
PY

echo "[5/7] 문법 검사"
"${PYTHON_BIN}" -m py_compile "${APP_DIR}/cmb_region_center_patch.py" "${ENTRY_FILE}"
echo "PY_COMPILE_OK"

echo "[6/7] 서비스 재시작 + health"
systemctl restart "${SERVICE_NAME}"
READY=0
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    READY=1
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done
if [[ "${READY}" != "1" ]]; then
  journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true
  exit 3
fi
curl -fsS http://127.0.0.1:8000/health

echo
echo "[7/7] DB/라우트 확인"
cd "${APP_DIR}"
PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" - <<'PY'
import os
import cmb_asgi

def connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception:
        import psycopg2
        return psycopg2.connect(dsn or "")

with connect() as conn:
    cur=conn.cursor()
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name='regions'
          AND column_name IN ('center_lat','center_lon')
        ORDER BY column_name
    """)
    cols=[r[0] for r in cur.fetchall()]
print("REGION_CENTER_COLUMNS", cols)
if cols != ["center_lat","center_lon"]:
    raise SystemExit("REGION_CENTER_COLUMNS_MISSING")

wanted=("POST","/admin/regions/{region_id}/center")
found=False
for route in cmb_asgi.app.routes:
    if getattr(route,"path","")==wanted[1] and wanted[0] in (getattr(route,"methods",None) or set()):
        found=True
print("REGION_CENTER_ROUTE", found)
if not found:
    raise SystemExit("REGION_CENTER_ROUTE_MISSING")

print("CMB_REGION_CENTER_PATCH_V1_OK")
PY

echo "============================================================"
echo " CMB_REGION_CENTER_V1_OK"
echo " - regions.center_lat / center_lon"
echo " - FIBER 업로드 후 중심 좌표 저장"
echo " - Viewer는 저장 중심만 사용"
echo " - 기존 bounds 중심 계산 제거"
echo " BACKUP=${BACKUP}"
echo "============================================================"
