#!/usr/bin/env bash
set -euo pipefail

export SYSTEMD_PAGER=cat
export PAGER=cat
export SYSTEMD_LESS=

SERVICE="${CMB_SERVICE_NAME:-cmb-cad-api}"
APP="/srv/CMB_Network/app"
ENTRY="${APP}/cmb_asgi.py"
MODULE="${APP}/cmb_kakao_key_patch.py"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${APP}/backup_kakao_key_v1_${STAMP}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: sudo bash 로 실행해주세요."; exit 1; }
[[ -f "${ENTRY}" ]] || { echo "ERROR: ${ENTRY} 없음"; exit 1; }

echo "============================================================"
echo " CMB Kakao JS Key Server Endpoint V1"
echo "============================================================"

echo "[1/7] 백업"
mkdir -p "${BACKUP}"
cp -a "${ENTRY}" "${BACKUP}/"
[[ -f "${MODULE}" ]] && cp -a "${MODULE}" "${BACKUP}/" || true
echo "BACKUP=${BACKUP}"

rollback() {
  echo "ROLLBACK"
  cp -a "${BACKUP}/cmb_asgi.py" "${ENTRY}" || true
  if [[ -f "${BACKUP}/cmb_kakao_key_patch.py" ]]; then
    cp -a "${BACKUP}/cmb_kakao_key_patch.py" "${MODULE}" || true
  else
    rm -f "${MODULE}"
  fi
  systemctl restart "${SERVICE}" || true
}
trap 'rollback' ERR

echo "[2/7] 서버 라우트 모듈 설치"
cat > "${MODULE}" <<'PY'
from __future__ import annotations

import os
from fastapi import HTTPException, Request


def _has_route(app, path, method):
    method = method.upper()
    for route in getattr(app, "routes", []):
        if getattr(route, "path", None) == path and method in set(getattr(route, "methods", set()) or set()):
            return True
    return False


def install(app):
    if not _has_route(app, "/settings/kakao-js-key", "GET"):
        @app.get("/settings/kakao-js-key")
        async def kakao_js_key(request: Request):
            # /settings/* is already protected by the CMB session/device middleware.
            # Keep an explicit Authorization presence check as a second guard.
            auth = str(request.headers.get("authorization") or "").strip()
            if not auth.lower().startswith("bearer "):
                raise HTTPException(401, "로그인이 필요합니다.")
            key = str(os.getenv("KAKAO_JS_APP_KEY") or "").strip()
            if not key:
                raise HTTPException(503, "KAKAO_JS_APP_KEY_NOT_CONFIGURED")
            return {"kakao_js_key": key}

    return {"route": "/settings/kakao-js-key", "configured": bool(str(os.getenv("KAKAO_JS_APP_KEY") or "").strip())}
PY

echo "[3/7] ASGI 엔트리 연결"
python3 - <<'PY'
from pathlib import Path
p=Path("/srv/CMB_Network/app/cmb_asgi.py")
text=p.read_text(encoding="utf-8")
begin="# === CMB_KAKAO_KEY_PATCH_V1_BEGIN ==="
end="# === CMB_KAKAO_KEY_PATCH_V1_END ==="
block=f'''\n{begin}\nfrom cmb_kakao_key_patch import install as _cmb_install_kakao_key_patch\n_CMB_KAKAO_KEY_INFO = _cmb_install_kakao_key_patch(app)\n{end}\n'''
import re
text=re.sub(r"\n?# === CMB_KAKAO_KEY_PATCH_V1_BEGIN ===.*?# === CMB_KAKAO_KEY_PATCH_V1_END ===\n?","\n",text,flags=re.S)
p.write_text(text.rstrip()+block,encoding="utf-8")
print("ASGI_PATCH_OK")
PY

echo "[4/7] 문법/패치 연결 검사"
"${APP}/.venv/bin/python3" -m py_compile "${ENTRY}" "${MODULE}"
grep -q 'CMB_KAKAO_KEY_PATCH_V1_BEGIN' "${ENTRY}"
grep -q '_cmb_install_kakao_key_patch(app)' "${ENTRY}"
echo "PY_COMPILE_OK"
echo "ASGI_PATCH_LINK_OK"

echo "[5/7] 서비스 재시작"
systemctl restart "${SERVICE}"
READY=0
for i in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    READY=1
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done
[[ "${READY}" == "1" ]] || { echo "ERROR: 서버 시작 실패"; false; }

echo "[6/7] 실행 서버 라우트/환경키 확인"
if grep -q '^KAKAO_JS_APP_KEY=.' "${APP}/server.env"; then
  echo "KAKAO_JS_APP_KEY_PRESENT_IN_SERVER_ENV"
else
  echo "KAKAO_JS_APP_KEY_MISSING_IN_SERVER_ENV"
  false
fi

"${APP}/.venv/bin/python3" - <<'PY'
import json, urllib.request
with urllib.request.urlopen("http://127.0.0.1:8000/openapi.json", timeout=5) as r:
    spec=json.load(r)
paths=spec.get("paths") or {}
if "/settings/kakao-js-key" not in paths:
    raise SystemExit("KAKAO_KEY_ROUTE_MISSING")
print("KAKAO_KEY_ROUTE_OK")
PY

echo "[7/7] HEALTH"
curl -fsS http://127.0.0.1:8000/health
echo

trap - ERR

echo "============================================================"
echo "CMB_KAKAO_JS_KEY_ENDPOINT_V1_OK"
echo "- GET /settings/kakao-js-key"
echo "- Windows new PC can fetch Kakao JS key from server"
echo "- server.env must contain KAKAO_JS_APP_KEY=<JavaScript key>"
echo "============================================================"
