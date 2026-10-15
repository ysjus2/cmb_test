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
PATCH_FILE="${APP_DIR}/cmb_region_center_patch.py"
TRACE_FILE="${APP_DIR}/region_center_trace.log"
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
mkdir -p "${BACKUP_DIR}"
cp -a "${PATCH_FILE}" "${BACKUP_DIR}/cmb_region_center_patch.py.${STAMP}.bak" 2>/dev/null || true

cat > "${PATCH_FILE}" <<'PY'
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

TRACE_FILE = os.path.join(os.path.dirname(__file__), "region_center_trace.log")


def _trace(message: str):
    try:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        line = f"{stamp} {message}"
        print(line, flush=True)
        with open(TRACE_FILE, "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except Exception:
        pass


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


def _safe_region_id(region_id: str):
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
            _trace(f"[CENTER_SAVE] region={rid} lat={lat:.12f} lon={lon:.12f}")
            return {"ok": True, "id": rid, "center_lat": lat, "center_lon": lon}

    @app.middleware("http")
    async def cmb_region_center_config(request: Request, call_next):
        if (
            request.url.path == "/regions"
            and request.query_params.get("client_config") == "region_centers"
        ):
            _trace(
                "[3_SERVER_CENTER_REQUEST_RECEIVED] "
                f"client={request.client.host if request.client else '-'} "
                f"path={request.url.path}?client_config=region_centers"
            )
            try:
                user = _token_user(request)
                _trace(
                    "[3_SERVER_CENTER_AUTH_OK] "
                    f"user_id={user['id']} username={user['username']}"
                )

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
                    _trace(
                        "[3_SERVER_CENTER_DB_VALUE] "
                        f"region={rid} lat={float(lat):.12f} lon={float(lon):.12f}"
                    )

                _trace(
                    "[3_SERVER_CENTER_RESPONSE_SEND] "
                    f"count={len(centers)} regions={','.join(sorted(centers.keys()))}"
                )
                return JSONResponse({
                    "ok": True,
                    "centers": centers,
                    "count": len(centers),
                })

            except HTTPException as exc:
                _trace(
                    "[3_SERVER_CENTER_ERROR] "
                    f"status={exc.status_code} detail={exc.detail}"
                )
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"ok": False, "detail": exc.detail},
                )
            except Exception as exc:
                _trace(f"[3_SERVER_CENTER_ERROR] status=500 detail={exc!r}")
                return JSONResponse(
                    status_code=500,
                    content={"ok": False, "detail": str(exc)},
                )

        return await call_next(request)
PY

: > "${TRACE_FILE}"
chown --reference="${APP_DIR}" "${TRACE_FILE}" 2>/dev/null || true

"${PYTHON_BIN}" -m py_compile "${PATCH_FILE}" "${ENTRY_FILE}"
echo "PY_COMPILE_OK"

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
echo "============================================================"
echo " CMB_REGION_CENTER_TRACE_V3_OK"
echo " TRACE_FILE=${TRACE_FILE}"
echo " 테스트 중 실시간 확인:"
echo " sudo tail -f ${TRACE_FILE}"
echo "============================================================"
