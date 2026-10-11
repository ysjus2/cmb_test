#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash 로 실행해주세요."
  exit 1
fi

MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE_NAME}")"
WORK_DIR="$(systemctl show -p WorkingDirectory --value "${SERVICE_NAME}")"
[[ -n "${WORK_DIR}" && "${WORK_DIR}" != "[not set]" ]] || WORK_DIR="/home/ysjus/cmb-server"
APP_DIR="${CMB_APP_DIR:-${WORK_DIR}}"
ENTRY_FILE="${APP_DIR}/cmb_asgi.py"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

if [[ -z "${MAIN_PID}" || "${MAIN_PID}" == "0" || ! -r "/proc/${MAIN_PID}/environ" ]]; then
  echo "ERROR: 실행 중인 서버 환경을 읽을 수 없습니다."
  exit 1
fi

while IFS= read -r -d '' item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/home/ysjus/cmb-server-backups"
mkdir -p "${BACKUP_DIR}"
BACKUP="${BACKUP_DIR}/cmb-before-region-admin-${STAMP}.tgz"
tar -C "${APP_DIR}" -czf "${BACKUP}" "$(basename "${ENTRY_FILE}")" 2>/dev/null || true

cat > "${APP_DIR}/cmb_region_admin_patch.py" <<'PY'
from __future__ import annotations

import hashlib
import os
import re
from fastapi import HTTPException, Request
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

def _admin_user(request: Request):
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
    if int(row[2]) != 1:
        raise HTTPException(status_code=403, detail="1등급 관리자만 사용할 수 있습니다.")
    return {"id": row[0], "username": row[1], "level": row[2]}

class RegionUpdateBody(BaseModel):
    name: str

def _safe_region_id(region_id: str) -> str:
    rid = str(region_id or "").strip()
    if not rid:
        raise HTTPException(status_code=400, detail="지역코드가 비어 있습니다.")
    if len(rid) > 200 or not re.fullmatch(r"[A-Za-z0-9_.-]+", rid):
        raise HTTPException(status_code=400, detail="잘못된 지역코드입니다.")
    return rid

def _route_exists(app, path, method):
    method = method.upper()
    for r in getattr(app, "routes", []):
        if getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or set()):
            return True
    return False

def install(app):
    if not _route_exists(app, "/admin/regions/{region_id}", "PUT"):
        @app.put("/admin/regions/{region_id}")
        async def update_region(region_id: str, body: RegionUpdateBody, request: Request):
            _admin_user(request)
            rid = _safe_region_id(region_id)
            name = str(body.name or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="지역명을 입력해주세요.")
            with _connect() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE regions SET name=%s WHERE id=%s", (name, rid))
                if cur.rowcount != 1:
                    raise HTTPException(status_code=404, detail="지역을 찾을 수 없습니다.")
                conn.commit()
            return {"ok": True, "id": rid, "name": name}

    if not _route_exists(app, "/admin/regions/{region_id}", "DELETE"):
        @app.delete("/admin/regions/{region_id}")
        async def delete_region(region_id: str, request: Request):
            _admin_user(request)
            rid = _safe_region_id(region_id)
            with _connect() as conn:
                cur = conn.cursor()

                cur.execute("SELECT name FROM regions WHERE id=%s", (rid,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="지역을 찾을 수 없습니다.")
                name = row[0]

                cur.execute(
                    "SELECT COUNT(*) FROM drawing_group_revisions WHERE region_code=%s",
                    (rid,),
                )
                drawing_revisions = int(cur.fetchone()[0])

                symbol_revisions = 0
                cur.execute("""
                    SELECT EXISTS(
                      SELECT 1 FROM information_schema.tables
                      WHERE table_schema='public' AND table_name='symbol_revisions'
                    )
                """)
                if bool(cur.fetchone()[0]):
                    cur.execute(
                        "SELECT COUNT(*) FROM symbol_revisions WHERE region_code=%s",
                        (rid,),
                    )
                    symbol_revisions = int(cur.fetchone()[0])

                if drawing_revisions or symbol_revisions:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"도면 데이터가 존재하여 지역을 삭제할 수 없습니다. "
                            f"도면 Revision {drawing_revisions}개 / SYMBOL Revision {symbol_revisions}개"
                        ),
                    )

                cur.execute("SELECT COUNT(*) FROM user_regions WHERE region_id=%s", (rid,))
                user_links = int(cur.fetchone()[0])

                cur.execute("DELETE FROM user_regions WHERE region_id=%s", (rid,))
                cur.execute("DELETE FROM regions WHERE id=%s", (rid,))
                if cur.rowcount != 1:
                    raise HTTPException(status_code=404, detail="지역을 찾을 수 없습니다.")
                conn.commit()

            return {
                "ok": True,
                "id": rid,
                "name": name,
                "removed_user_links": user_links,
            }
PY

python - <<PY
from pathlib import Path
p=Path(r"${ENTRY_FILE}")
text=p.read_text(encoding="utf-8")
begin="# === CMB_REGION_ADMIN_PATCH_V1_BEGIN ==="
end="# === CMB_REGION_ADMIN_PATCH_V1_END ==="
block='''# === CMB_REGION_ADMIN_PATCH_V1_BEGIN ===
try:
    import cmb_region_admin_patch
    cmb_region_admin_patch.install(app)
except Exception as exc:
    print("CMB_REGION_ADMIN_PATCH_ERROR", repr(exc))
# === CMB_REGION_ADMIN_PATCH_V1_END ===
'''
import re
text=re.sub(r"\n?# === CMB_REGION_ADMIN_PATCH_V1_BEGIN ===.*?# === CMB_REGION_ADMIN_PATCH_V1_END ===\n?", "\n", text, flags=re.S)
p.write_text(text.rstrip()+"\n\n"+block, encoding="utf-8")
PY

"${PYTHON_BIN}" -m py_compile "${APP_DIR}/cmb_region_admin_patch.py" "${ENTRY_FILE}"

systemctl restart "${SERVICE_NAME}"

for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "ERROR: health 실패. 백업: ${BACKUP}"
  exit 1
fi

cd "${APP_DIR}"
PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" - <<'PY'
import cmb_asgi
wanted = {
    ("PUT", "/admin/regions/{region_id}"),
    ("DELETE", "/admin/regions/{region_id}"),
}
found=set()
for r in cmb_asgi.app.routes:
    for m in (getattr(r,"methods",None) or []):
        key=(m,getattr(r,"path",""))
        if key in wanted:
            found.add(key)
print("REGION_ADMIN_ROUTES", sorted(found))
if found != wanted:
    raise SystemExit("REGION_ADMIN_ROUTE_CHECK_FAILED")
PY

echo "============================================================"
echo "CMB_REGION_ADMIN_PATCH_V1_OK"
echo "PUT    /admin/regions/{region_id}"
echo "DELETE /admin/regions/{region_id}"
echo "BACKUP=${BACKUP}"
echo "============================================================"
