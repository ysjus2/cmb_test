#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"
APP_DIR="${CMB_APP_DIR:-/srv/CMB_Network/app}"
PATCH_FILE="${APP_DIR}/cmb_region_center_patch.py"
TRACE_FILE="${APP_DIR}/region_center_trace.log"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash 로 실행해주세요."
  exit 1
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "${APP_DIR}/backups"
cp -a "${PATCH_FILE}" "${APP_DIR}/backups/cmb_region_center_patch.py.${STAMP}.bak"

echo "[1/5] 상세 trace 코드 제거"

"${PYTHON_BIN}" - <<'PY'
from pathlib import Path

p = Path("/srv/CMB_Network/app/cmb_region_center_patch.py")
lines = p.read_text(encoding="utf-8").splitlines(True)
out = []
i = 0

while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    if stripped == "from datetime import datetime":
        i += 1
        continue

    if stripped.startswith("TRACE_FILE ="):
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith("def "):
            i += 1
        continue

    if line.startswith("def _trace("):
        i += 1
        while i < len(lines) and not lines[i].startswith("def _connect("):
            i += 1
        continue

    if stripped.startswith("_trace("):
        balance = line.count("(") - line.count(")")
        i += 1
        while i < len(lines) and balance > 0:
            balance += lines[i].count("(") - lines[i].count(")")
            i += 1
        continue

    out.append(line)
    i += 1

text = "".join(out)
p.write_text(text, encoding="utf-8")

check = p.read_text(encoding="utf-8")
for forbidden in (
    "TRACE_FILE",
    "def _trace(",
    "_trace(",
    "3_SERVER_CENTER_",
    "[CENTER_SAVE]",
):
    if forbidden in check:
        raise SystemExit(f"TRACE_REMOVE_FAILED: {forbidden}")

if 'if int(user["level"]) == 1:' not in check:
    raise SystemExit("ADMIN_REGION_CENTER_RULE_MISSING")

print("TRACE_CODE_REMOVED")
print("ADMIN_REGION_CENTER_RULE_OK")
PY

echo "[2/5] 문법 검사"
"${PYTHON_BIN}" -m py_compile "${PATCH_FILE}" "${APP_DIR}/cmb_asgi.py"
echo "PY_COMPILE_OK"

echo "[3/5] 기존 trace 파일 삭제"
rm -f "${TRACE_FILE}"
echo "TRACE_FILE_REMOVED"

echo "[4/5] 서비스 재시작"
systemctl restart "${SERVICE_NAME}"
READY=0
for i in $(seq 1 40); do
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

echo "[5/5] health"
curl -fsS http://127.0.0.1:8000/health
echo
echo "============================================================"
echo " CMB_REGION_CENTER_LIGHT_V7_OK"
echo " - 지역 중심점 기능 유지"
echo " - 1등급 전체 지역 / 일반 사용자 배정 지역 유지"
echo " - 상세 파일 trace 제거"
echo " - 런타임 print trace 제거"
echo "============================================================"
