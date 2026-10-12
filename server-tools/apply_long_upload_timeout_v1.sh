#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="/root/cmb_nginx_backup_${STAMP}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash 로 실행해주세요."
  exit 1
fi

echo "============================================================"
echo " CMB LONG UPLOAD TIMEOUT V1"
echo " - Windows client: no fixed upload timeout"
echo " - Nginx upload/proxy timeout: 24h"
echo "============================================================"

mkdir -p "${BACKUP_DIR}"
cp -a /etc/nginx "${BACKUP_DIR}/nginx"
echo "BACKUP_OK ${BACKUP_DIR}"

mapfile -t CANDIDATES < <(
  grep -RIlE 'proxy_pass|8443|cmb-cad-api|127\.0\.0\.1:8000|localhost:8000'     /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null || true
)

if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo "ERROR: CMB reverse proxy nginx 설정 파일을 찾지 못했습니다."
  exit 2
fi

PATCHED=0
for conf in "${CANDIDATES[@]}"; do
  [[ -f "${conf}" ]] || continue
  python3 - "${conf}" <<'PY'
from pathlib import Path
import re, sys

path = Path(sys.argv[1])
src = path.read_text(encoding="utf-8")
if "proxy_pass" not in src:
    raise SystemExit(10)

marker = "# CMB_LONG_UPLOAD_TIMEOUT_V1"
block = """        # CMB_LONG_UPLOAD_TIMEOUT_V1
        client_body_timeout 86400s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 86400s;
        proxy_read_timeout 86400s;
        send_timeout 86400s;
"""

if marker in src:
    # idempotent: normalize values if block already exists
    src = re.sub(r'(?m)^\s*client_body_timeout\s+\S+;\s*$', '        client_body_timeout 86400s;', src)
    src = re.sub(r'(?m)^\s*proxy_connect_timeout\s+\S+;\s*$', '        proxy_connect_timeout 300s;', src)
    src = re.sub(r'(?m)^\s*proxy_send_timeout\s+\S+;\s*$', '        proxy_send_timeout 86400s;', src)
    src = re.sub(r'(?m)^\s*proxy_read_timeout\s+\S+;\s*$', '        proxy_read_timeout 86400s;', src)
    src = re.sub(r'(?m)^\s*send_timeout\s+\S+;\s*$', '        send_timeout 86400s;', src)
else:
    # Put timeout directives in the server block that contains proxy_pass.
    pos = src.find("proxy_pass")
    server_start = src.rfind("server {", 0, pos)
    if server_start < 0:
        raise SystemExit(11)
    brace = src.find("\n", server_start)
    if brace < 0:
        raise SystemExit(12)
    src = src[:brace+1] + block + src[brace+1:]

path.write_text(src, encoding="utf-8")
print(path)
PY
  rc=$?
  if [[ "$rc" -eq 0 ]]; then
    PATCHED=$((PATCHED+1))
  fi
done

if [[ "$PATCHED" -eq 0 ]]; then
  echo "ERROR: nginx 설정 패치 실패"
  exit 3
fi

nginx -t
systemctl reload nginx

echo
echo "[Nginx timeout 확인]"
nginx -T 2>/dev/null | grep -E 'CMB_LONG_UPLOAD_TIMEOUT_V1|client_body_timeout|proxy_connect_timeout|proxy_send_timeout|proxy_read_timeout|send_timeout' || true

echo
echo "[API 상태 확인]"
for i in $(seq 1 20); do
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "SERVER_READY"
    break
  fi
  sleep 1
done

echo "============================================================"
echo " CMB_LONG_UPLOAD_TIMEOUT_V1_OK"
echo " - 업로드 중 Windows idle logout 방지"
echo " - Windows 업로드 요청 고정 timeout 제거"
echo " - Nginx body/send/read timeout 86400s"
echo "============================================================"
