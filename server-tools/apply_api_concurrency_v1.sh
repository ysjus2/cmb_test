#!/usr/bin/env bash
set -euo pipefail

SERVICE="${CMB_SERVICE_NAME:-cmb-cad-api}"
APP_DIR="${CMB_APP_DIR:-/home/ysjus/cmb-server}"
PYTHON="${APP_DIR}/.venv/bin/python"
OVERRIDE_DIR="/etc/systemd/system/${SERVICE}.service.d"
OVERRIDE_FILE="${OVERRIDE_DIR}/99-api-workers.conf"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/home/ysjus/cmb-server-backups"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash 로 실행해주세요."
  exit 1
fi

echo "============================================================"
echo " CMB API CONCURRENCY V1"
echo " - Uvicorn workers: 2"
echo " - health/session/layers blocking 완화"
echo " - grid API 실제 서비스 환경 검증"
echo "============================================================"

mkdir -p "${BACKUP_DIR}" "${OVERRIDE_DIR}"

if [[ -f "${OVERRIDE_FILE}" ]]; then
  cp -a "${OVERRIDE_FILE}" "${BACKUP_DIR}/99-api-workers.conf.${STAMP}.bak"
fi

MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE}")"
if [[ -z "${MAIN_PID}" || "${MAIN_PID}" == "0" || ! -r "/proc/${MAIN_PID}/environ" ]]; then
  echo "ERROR: 실행 중인 ${SERVICE} 환경을 읽을 수 없습니다."
  exit 2
fi

while IFS= read -r -d '' item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

cat > "${OVERRIDE_FILE}" <<EOF
[Service]
ExecStart=
ExecStart=${APP_DIR}/.venv/bin/python3 ${APP_DIR}/.venv/bin/uvicorn cmb_asgi:app --app-dir ${APP_DIR} --host 127.0.0.1 --port 8000 --workers 2
EOF

echo "[1/5] systemd override"
cat "${OVERRIDE_FILE}"

echo
echo "[2/5] daemon-reload + restart"
systemctl daemon-reload
systemctl restart "${SERVICE}"

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
  journalctl -u "${SERVICE}" -n 120 --no-pager || true
  exit 3
fi

echo
echo "[3/5] worker 확인"
ps -eo pid,ppid,cmd | grep -E '[u]vicorn cmb_asgi:app|[p]ython.*spawn' || true
CHILDREN="$(pgrep -P "$(systemctl show -p MainPID --value "${SERVICE}")" | wc -l | tr -d ' ')"
echo "WORKER_CHILDREN=${CHILDREN}"

echo
echo "[4/5] 서비스 환경으로 ASGI/grid route 검사"
(
  cd "${APP_DIR}"
  PYTHONPATH="${APP_DIR}" "${PYTHON}" - <<'PY'
import cmb_asgi

wanted="/online/{region}/grid/{grid_id}/objects"
routes=[]
for route in cmb_asgi.app.routes:
    if getattr(route,"path","")==wanted:
        routes.append(sorted(getattr(route,"methods",None) or []))

print("GRID_ROUTE =", routes)
if not any("GET" in methods for methods in routes):
    raise SystemExit("GRID_ROUTE_MISSING")

print("ASGI_GRID_ROUTE_OK")
PY
)

echo
echo "[5/5] 응답성 확인"
for n in 1 2 3 4 5; do
  curl -sS -m 5 -o /dev/null -w "health ${n}: HTTP=%{http_code} TIME=%{time_total}s\\n" \
    http://127.0.0.1:8000/health
done

echo
echo "============================================================"
echo " CMB_API_CONCURRENCY_V1_OK"
echo " - Uvicorn workers=2"
echo " - 새 grid API route 확인"
echo " - 경량 API가 무거운 조회 1건에 같이 막히는 현상 완화"
echo "============================================================"
