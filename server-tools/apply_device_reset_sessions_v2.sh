#!/usr/bin/env bash
set -euo pipefail

export SYSTEMD_PAGER=cat
export PAGER=cat
export SYSTEMD_LESS=

SERVICE="${CMB_SERVICE_NAME:-cmb-cad-api}"
APP="/srv/CMB_Network/app"
TARGET="${APP}/cmb_device_session_security.py"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${APP}/backup_device_reset_v2_${STAMP}"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: sudo bash 로 실행해주세요."; exit 1; }
[[ -f "${TARGET}" ]] || { echo "ERROR: ${TARGET} 없음"; exit 1; }

echo "============================================================"
echo " CMB 단말초기화 + 세션폐기 V2"
echo "============================================================"

echo "[1/6] 백업"
mkdir -p "${BACKUP}"
cp -a "${TARGET}" "${BACKUP}/"
echo "BACKUP=${BACKUP}"

echo "[2/6] reset-device 로직 패치"
python3 - <<'PY'
from pathlib import Path
import re

path=Path("/srv/CMB_Network/app/cmb_device_session_security.py")
text=path.read_text(encoding="utf-8")

pattern=r'''(?ms)^(\s*)@app\.post\("/admin/users/\{user_id\}/reset-device"\)\n\s*async def reset_device\(user_id:int,request:Request\):\n.*?^\s*return \{"ok":True,"deleted":deleted\}\s*$'''

replacement='''        @app.post("/admin/users/{user_id}/reset-device")
        async def reset_device(user_id:int,request:Request):
            _admin(request)
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute("SELECT id FROM app_users WHERE id=%s",(user_id,))
                if cur.fetchone() is None:
                    raise HTTPException(404,"사용자를 찾을 수 없습니다.")
                cur.execute("DELETE FROM user_devices WHERE user_id=%s",(user_id,))
                deleted_devices=cur.rowcount
                cur.execute("UPDATE auth_sessions SET revoked=TRUE WHERE user_id=%s AND revoked=FALSE",(user_id,))
                revoked_sessions=cur.rowcount
                cur.execute("DELETE FROM user_security_activity WHERE user_id=%s",(user_id,))
                cleared_activity=cur.rowcount
                conn.commit()
            return {
                "ok":True,
                "deleted_devices":deleted_devices,
                "revoked_sessions":revoked_sessions,
                "cleared_activity":cleared_activity,
                "relogin_required":True,
            }'''

new_text,count=re.subn(pattern,replacement,text)
if count!=1:
    raise SystemExit(f"RESET_DEVICE_PATCH_COUNT={count}")

path.write_text(new_text,encoding="utf-8")
print("RESET_DEVICE_PATCH_OK")
PY

echo "[3/6] 문법 검사"
"${APP}/.venv/bin/python3" -m py_compile "${TARGET}"
echo "PY_COMPILE_OK"

echo "[4/6] 서비스 재시작"
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

if [[ "${READY}" != "1" ]]; then
    echo "ERROR: 서버 시작 실패 - 자동 롤백"
    cp -a "${BACKUP}/cmb_device_session_security.py" "${TARGET}"
    systemctl restart "${SERVICE}"
    exit 1
fi

echo "[5/6] 패치 확인"
grep -nE 'deleted_devices|revoked_sessions|cleared_activity|relogin_required' "${TARGET}"

echo "[6/6] HEALTH"
curl -fsS http://127.0.0.1:8000/health
echo

echo "============================================================"
echo "CMB_DEVICE_RESET_SESSIONS_V2_OK"
echo "- 단말 초기화: WINDOWS + ANDROID 등록 제거"
echo "- 기존 access/refresh 세션 전체 revoked"
echo "- security activity 제거"
echo "- 다음 로그인 단말 자동 등록"
echo "============================================================"
