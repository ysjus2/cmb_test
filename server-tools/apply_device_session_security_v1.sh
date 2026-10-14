#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"
[[ "${EUID}" -eq 0 ]] || { echo "ERROR: sudo bash $0 로 실행해주세요."; exit 1; }
if ! systemctl cat "${SERVICE_NAME}" >/dev/null 2>&1; then SERVICE_NAME="cmb-server"; fi
WORK_DIR="$(systemctl show -p WorkingDirectory --value "${SERVICE_NAME}")"
[[ -n "${WORK_DIR}" && "${WORK_DIR}" != "[not set]" ]] || WORK_DIR="/home/ysjus/cmb-server"
APP_DIR="${CMB_APP_DIR:-${WORK_DIR}}"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"; [[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="${APP_DIR}/venv/bin/python"; [[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"
EXEC_START="$(systemctl show -p ExecStart --value "${SERVICE_NAME}")"
ENTRY_MODULE=""; [[ "${EXEC_START}" =~ ([A-Za-z_][A-Za-z0-9_]*):app ]] && ENTRY_MODULE="${BASH_REMATCH[1]}"
[[ -n "${ENTRY_MODULE}" ]] || ENTRY_MODULE="cmb_asgi"
ENTRY_FILE="${APP_DIR}/${ENTRY_MODULE}.py"
MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE_NAME}")"
while IFS= read -r -d '' item; do
  case "${item}" in DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*) export "${item}";; esac
done < "/proc/${MAIN_PID}/environ"

cat > "${APP_DIR}/cmb_device_session_security.py" <<'PY'
from __future__ import annotations
import hashlib, os
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

DEVICE_TYPES={"WINDOWS","ANDROID"}
SESSION_SECONDS={1:7200,2:7200,3:3600,4:1800,5:1800}

def _connect():
    dsn=next((os.getenv(k) for k in ("DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN") if os.getenv(k)),None)
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception:
        import psycopg2
        return psycopg2.connect(dsn or "")

def _schema():
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("""
          CREATE TABLE IF NOT EXISTS user_devices(
            user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            device_type TEXT NOT NULL,
            device_hash TEXT NOT NULL,
            registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY(user_id,device_type),
            CHECK(device_type IN ('WINDOWS','ANDROID'))
          )
        """)
        cur.execute("""
          CREATE TABLE IF NOT EXISTS user_security_activity(
            session_id BIGINT PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
          )
        """)
        conn.commit()

def _user(request):
    auth=str(request.headers.get("authorization") or "")
    if not auth.lower().startswith("bearer "): return None
    token=auth.split(" ",1)[1].strip()
    token_hash=hashlib.sha256(token.encode()).hexdigest()
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("""
          SELECT u.id,u.level,u.active,s.id,s.revoked
          FROM auth_sessions s JOIN app_users u ON u.id=s.user_id
          WHERE s.access_hash=%s ORDER BY s.id DESC LIMIT 1
        """,(token_hash,))
        row=cur.fetchone()
    if not row:return None
    return {"id":row[0],"level":int(row[1] or 5),"active":bool(row[2]),"session_id":row[3],"revoked":bool(row[4])}

def _admin(request):
    u=_user(request)
    if not u or not u["active"] or u["revoked"]: raise HTTPException(401,"로그인이 필요합니다.")
    if u["level"]!=1: raise HTTPException(403,"1등급 관리자만 사용할 수 있습니다.")
    return u

def _check_device(u,request):
    raw=str(request.headers.get("x-cmb-device-id") or "").strip()
    typ=str(request.headers.get("x-cmb-device-type") or "").strip().upper()
    if not raw or typ not in DEVICE_TYPES: raise HTTPException(403,"DEVICE_REQUIRED")
    digest=hashlib.sha256(raw.encode()).hexdigest()
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("SELECT device_hash FROM user_devices WHERE user_id=%s AND device_type=%s",(u["id"],typ))
        row=cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO user_devices(user_id,device_type,device_hash) VALUES(%s,%s,%s)",(u["id"],typ,digest))
        elif str(row[0])!=digest:
            raise HTTPException(403,"DEVICE_NOT_APPROVED")
        else:
            cur.execute("UPDATE user_devices SET last_seen_at=NOW() WHERE user_id=%s AND device_type=%s",(u["id"],typ))
        conn.commit()

def _check_idle(u):
    limit=SESSION_SECONDS.get(u["level"],1800)
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("SELECT EXTRACT(EPOCH FROM (NOW()-last_seen_at)) FROM user_security_activity WHERE session_id=%s",(u["session_id"],))
        row=cur.fetchone()
        if row and row[0] is not None and float(row[0])>limit:
            cur.execute("UPDATE auth_sessions SET revoked=TRUE WHERE id=%s",(u["session_id"],))
            cur.execute("DELETE FROM user_security_activity WHERE session_id=%s",(u["session_id"],))
            conn.commit()
            raise HTTPException(401,"SESSION_IDLE_EXPIRED")
        cur.execute("""
          INSERT INTO user_security_activity(session_id,user_id,last_seen_at) VALUES(%s,%s,NOW())
          ON CONFLICT(session_id) DO UPDATE SET last_seen_at=NOW()
        """,(u["session_id"],u["id"]))
        conn.commit()

class LevelBody(BaseModel):
    level:int=Field(ge=1,le=5)

def _has(app,path,method):
    return any(getattr(r,"path",None)==path and method in (getattr(r,"methods",None) or set()) for r in app.routes)

def install(app):
    _schema()
    @app.middleware("http")
    async def device_session_guard(request:Request,call_next):
        path=request.url.path
        if path.startswith(("/online/","/regions","/me","/session/","/admin/","/settings/")):
            u=_user(request)
            if u:
                if not u["active"] or u["revoked"]:
                    return JSONResponse(status_code=401,content={"detail":"ACCOUNT_DISABLED"})
                try:
                    _check_idle(u); _check_device(u,request)
                except HTTPException as exc:
                    return JSONResponse(status_code=exc.status_code,content={"detail":exc.detail})
        return await call_next(request)

    if not _has(app,"/admin/users/{user_id}/reset-device","POST"):
        @app.post("/admin/users/{user_id}/reset-device")
        async def reset_device(user_id:int,request:Request):
            _admin(request)
            with _connect() as conn:
                cur=conn.cursor(); cur.execute("DELETE FROM user_devices WHERE user_id=%s",(user_id,)); deleted=cur.rowcount; conn.commit()
            return {"ok":True,"deleted":deleted}

    if not _has(app,"/admin/users/{user_id}/level","POST"):
        @app.post("/admin/users/{user_id}/level")
        async def set_level(user_id:int,body:LevelBody,request:Request):
            admin=_admin(request)
            if user_id==admin["id"] and body.level!=1: raise HTTPException(400,"현재 관리자 자신의 권한은 해제할 수 없습니다.")
            with _connect() as conn:
                cur=conn.cursor(); cur.execute("UPDATE app_users SET level=%s WHERE id=%s",(body.level,user_id))
                if cur.rowcount!=1: raise HTTPException(404,"사용자를 찾을 수 없습니다.")
                conn.commit()
            return {"ok":True,"level":body.level}
    return {"device_policy":"1 WINDOWS + 1 ANDROID","session_seconds":SESSION_SECONDS}
PY

"${PYTHON_BIN}" - <<PY
from pathlib import Path
import re
p=Path(r"${ENTRY_FILE}")
text=p.read_text(encoding="utf-8")
text=re.sub(r"\n?# === CMB_DEVICE_SESSION_SECURITY_V1_BEGIN ===.*?# === CMB_DEVICE_SESSION_SECURITY_V1_END ===\n?","\n",text,flags=re.S)
text=text.rstrip()+'''\n\n# === CMB_DEVICE_SESSION_SECURITY_V1_BEGIN ===
from cmb_device_session_security import install as _cmb_device_session_install
_CMB_DEVICE_SESSION_SECURITY=_cmb_device_session_install(app)
# === CMB_DEVICE_SESSION_SECURITY_V1_END ===
'''
p.write_text(text,encoding="utf-8")
PY
"${PYTHON_BIN}" -m py_compile "${APP_DIR}/cmb_device_session_security.py" "${ENTRY_FILE}"
systemctl restart "${SERVICE_NAME}"
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break; sleep 1; done
curl -fsS http://127.0.0.1:8000/health >/dev/null
echo "CMB_DEVICE_SESSION_SECURITY_V1_OK"
