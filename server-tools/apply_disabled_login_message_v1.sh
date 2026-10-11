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
BACKUP="${BACKUP_DIR}/cmb-before-disabled-login-${STAMP}.tgz"
tar -C "${APP_DIR}" -czf "${BACKUP}" "$(basename "${ENTRY_FILE}")" 2>/dev/null || true

cat > "${APP_DIR}/cmb_disabled_login_patch.py" <<'PY'
from __future__ import annotations

import json
import os

from fastapi import Request
from fastapi.responses import JSONResponse

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

def _is_disabled(username: str) -> bool:
    username = str(username or "").strip()
    if not username:
        return False
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT active FROM app_users WHERE username=%s LIMIT 1",
            (username,),
        )
        row = cur.fetchone()
    return bool(row is not None and row[0] is False)

def install(app):
    @app.middleware("http")
    async def disabled_account_login_message(request: Request, call_next):
        if request.method.upper() != "POST" or request.url.path != "/auth/login":
            return await call_next(request)

        body = await request.body()

        async def receive():
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        request._receive = receive
        response = await call_next(request)

        if response.status_code != 401:
            return response

        try:
            payload = json.loads(body.decode("utf-8"))
            username = payload.get("username")
        except Exception:
            username = None

        try:
            if _is_disabled(username):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "ACCOUNT_DISABLED"},
                )
        except Exception:
            pass

        return response
PY

"${PYTHON_BIN}" - <<PY
from pathlib import Path
import re

p=Path(r"${ENTRY_FILE}")
text=p.read_text(encoding="utf-8")
block='''# === CMB_DISABLED_LOGIN_PATCH_V1_BEGIN ===
try:
    import cmb_disabled_login_patch
    cmb_disabled_login_patch.install(app)
except Exception as exc:
    print("CMB_DISABLED_LOGIN_PATCH_ERROR", repr(exc))
# === CMB_DISABLED_LOGIN_PATCH_V1_END ===
'''
text=re.sub(
    r"\n?# === CMB_DISABLED_LOGIN_PATCH_V1_BEGIN ===.*?# === CMB_DISABLED_LOGIN_PATCH_V1_END ===\n?",
    "\n",
    text,
    flags=re.S,
)
p.write_text(text.rstrip()+"\n\n"+block, encoding="utf-8")
PY

"${PYTHON_BIN}" -m py_compile "${APP_DIR}/cmb_disabled_login_patch.py" "${ENTRY_FILE}"

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

echo "============================================================"
echo "CMB_DISABLED_LOGIN_PATCH_V1_OK"
echo "정지 계정 로그인 -> HTTP 401 detail=ACCOUNT_DISABLED"
echo "정상/비밀번호 오류 흐름은 기존 /auth/login 유지"
echo "BACKUP=${BACKUP}"
echo "============================================================"
