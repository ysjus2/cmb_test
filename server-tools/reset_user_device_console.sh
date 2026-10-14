#!/usr/bin/env bash
set -euo pipefail

APP="/srv/CMB_Network/app"
ENV_FILE="${APP}/server.env"
PYTHON="${APP}/.venv/bin/python3"

[[ "${EUID}" -eq 0 ]] || { echo "ERROR: sudo 로 실행해주세요."; exit 1; }
[[ -x "${PYTHON}" ]] || { echo "ERROR: Python venv 없음: ${PYTHON}"; exit 1; }
[[ -f "${ENV_FILE}" ]] || { echo "ERROR: server.env 없음"; exit 1; }

USERNAME="${1:-}"
[[ -n "${USERNAME}" ]] || {
  echo "사용법: sudo $0 <아이디>"
  exit 1
}

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

TARGET_USER="${USERNAME}" "${PYTHON}" - <<'PY'
import os
from cmb_device_session_security import _connect

username=os.environ["TARGET_USER"].strip()
with _connect() as conn:
    cur=conn.cursor()
    cur.execute("SELECT id, username, level, active FROM app_users WHERE username=%s",(username,))
    row=cur.fetchone()
    if not row:
        raise SystemExit(f"USER_NOT_FOUND: {username}")
    user_id=row[0]

    cur.execute("DELETE FROM user_devices WHERE user_id=%s",(user_id,))
    devices=cur.rowcount

    cur.execute("UPDATE auth_sessions SET revoked=TRUE WHERE user_id=%s AND revoked=FALSE",(user_id,))
    sessions=cur.rowcount

    cur.execute("DELETE FROM user_security_activity WHERE user_id=%s",(user_id,))
    activity=cur.rowcount

    conn.commit()

print(f"USER={row[1]}")
print(f"LEVEL={row[2]}")
print(f"ACTIVE={row[3]}")
print(f"DELETED_DEVICES={devices}")
print(f"REVOKED_SESSIONS={sessions}")
print(f"CLEARED_ACTIVITY={activity}")
print("CMB_ADMIN_DEVICE_RECOVERY_OK")
print("다음 Windows/Android 로그인 기기가 새 등록 단말이 됩니다.")
PY
