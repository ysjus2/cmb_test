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

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/srv/CMB_Network/app/backups"
mkdir -p "${BACKUP_DIR}"
cp -a "${PATCH_FILE}" "${BACKUP_DIR}/cmb_region_center_patch.py.${STAMP}.bak" 2>/dev/null || true

"${PYTHON_BIN}" - <<'PY'
from pathlib import Path
p=Path("/srv/CMB_Network/app/cmb_region_center_patch.py")
text=p.read_text(encoding="utf-8")

old='''                with _connect() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT r.id,r.center_lat,r.center_lon
                        FROM user_regions ur
                        JOIN regions r ON r.id=ur.region_id
                        WHERE ur.user_id=%s
                        ORDER BY r.id
                    """, (user["id"],))
                    rows = cur.fetchall()
'''

new='''                with _connect() as conn:
                    cur = conn.cursor()

                    # /regions 권한 기준과 동일하게 처리한다.
                    # 1등급 관리자는 전체 지역을 조회할 수 있으므로 중심점도 전체 지역을 반환한다.
                    # 일반 사용자는 user_regions에 배정된 지역만 반환한다.
                    if int(user["level"]) == 1:
                        cur.execute("""
                            SELECT r.id,r.center_lat,r.center_lon
                            FROM regions r
                            ORDER BY r.id
                        """)
                    else:
                        cur.execute("""
                            SELECT r.id,r.center_lat,r.center_lon
                            FROM user_regions ur
                            JOIN regions r ON r.id=ur.region_id
                            WHERE ur.user_id=%s
                            ORDER BY r.id
                        """, (user["id"],))

                    rows = cur.fetchall()
'''

if old not in text:
    raise SystemExit("TARGET_QUERY_BLOCK_NOT_FOUND")

text=text.replace(old,new)

text=text.replace(
    'f"user_id={user[\'id\']} username={user[\'username\']}"',
    'f"user_id={user[\'id\']} username={user[\'username\']} level={user[\'level\']}"'
)

p.write_text(text,encoding="utf-8")
print("REGION_CENTER_PERMISSION_PATCHED")
PY

"${PYTHON_BIN}" -m py_compile "${PATCH_FILE}" "${ENTRY_FILE}"
echo "PY_COMPILE_OK"

: > "${TRACE_FILE}" || true

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
echo " CMB_REGION_CENTER_PERMISSION_V4_OK"
echo " - level 1: all regions"
echo " - level 2~5: assigned user_regions only"
echo " - Windows Rev9 unchanged"
echo "============================================================"
