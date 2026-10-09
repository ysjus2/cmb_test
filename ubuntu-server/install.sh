#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/cmb-server
DATA_DIR=/var/lib/cmb-server
SERVICE=/etc/systemd/system/cmb-server.service
ENV_FILE=/etc/cmb-server.env
CERT_DIR=/etc/cmb-server/tls
SERVER_IP="${CMB_SERVER_IP:-192.168.246.54}"
DEV_TOKEN="${CMB_DEV_TOKEN:-cmb-local-test}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "sudo bash install.sh 로 실행해주세요."
  exit 1
fi

echo "[1/8] 패키지 설치"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv openssl curl rsync

echo "[2/8] 기존 설치 백업"
mkdir -p /opt/cmb-backups
if [[ -d "${APP_DIR}" ]]; then
  stamp=$(date +%Y%m%d_%H%M%S)
  tar -C /opt -czf "/opt/cmb-backups/cmb-server-${stamp}.tgz" cmb-server || true
fi

echo "[3/8] 서버 파일 설치"
mkdir -p "${APP_DIR}" "${DATA_DIR}" "${CERT_DIR}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
rsync -a --delete --exclude __pycache__ "${SRC_DIR}/" "${APP_DIR}/"
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install --upgrade pip
"${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "[4/8] HTTPS 인증서 준비"
if [[ ! -f "${CERT_DIR}/server.crt" || ! -f "${CERT_DIR}/server.key" ]]; then
cat > "${CERT_DIR}/openssl.cnf" <<EOF
[req]
distinguished_name=req_dn
x509_extensions=v3
prompt=no
[req_dn]
CN=${SERVER_IP}
[v3]
subjectAltName=IP:${SERVER_IP}
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF
  openssl req -x509 -newkey rsa:3072 -nodes -days 3650     -keyout "${CERT_DIR}/server.key" -out "${CERT_DIR}/server.crt"     -config "${CERT_DIR}/openssl.cnf"
  chmod 600 "${CERT_DIR}/server.key"
fi

echo "[5/8] 환경 설정"
cat > "${ENV_FILE}" <<EOF
CMB_DB_PATH=${DATA_DIR}/cmb.sqlite3
CMB_DEV_BYPASS_AUTH=1
CMB_DEV_TOKEN=${DEV_TOKEN}
EOF
chmod 600 "${ENV_FILE}"

echo "[6/8] systemd 서비스 설치"
cat > "${SERVICE}" <<EOF
[Unit]
Description=CMB Network FastAPI Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8443 --ssl-keyfile ${CERT_DIR}/server.key --ssl-certfile ${CERT_DIR}/server.crt
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "[7/8] 서비스 시작"
systemctl daemon-reload
systemctl enable cmb-server
systemctl restart cmb-server

echo "[8/8] 확인"
sleep 2
systemctl --no-pager --full status cmb-server || true
curl -k "https://${SERVER_IP}:8443/health" || true

echo
echo "완료"
echo "SERVER = https://${SERVER_IP}:8443"
echo "TEST TOKEN = ${DEV_TOKEN}"
echo "CA 배포용 인증서 = ${CERT_DIR}/server.crt"
echo
echo "Windows 테스트 환경변수 예:"
echo "  set CMB_ACCESS_TOKEN=${DEV_TOKEN}"
echo "운영 전에는 /etc/cmb-server.env 의 CMB_DEV_BYPASS_AUTH=0 으로 바꾸고 실제 인증을 연결하세요."
