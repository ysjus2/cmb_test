# CMB Ubuntu server

현재 Windows 온라인 Viewer/관리자 업로드용 시험 서버입니다.

- HTTPS: `https://192.168.246.54:8443`
- 그룹 revision: `FIBER / COAX / POLE / CONDUIT / USER`
- COAX는 동축 케이블과 동축 기기를 같은 revision으로 원자적으로 교체합니다.
- `POST /admin/drawings/upload`: 그룹 패키지 업로드 후 해당 그룹의 새 revision을 활성화합니다.
- `GET /datasets/{region}/objects?bbox=...`: 온라인 지도 viewport 객체 조회.
- 시험 기간에는 `CMB_DEV_BYPASS_AUTH=1`과 정적 테스트 Bearer 토큰을 사용합니다.

Ubuntu에서:

```bash
cd ubuntu-server
sudo CMB_SERVER_IP=192.168.246.54 CMB_DEV_TOKEN='cmb-local-test' bash install.sh
```

기존 `/opt/cmb-server`는 설치 전에 `/opt/cmb-backups/`에 백업합니다.
DB는 `/var/lib/cmb-server/cmb.sqlite3`에 유지되어 재설치해도 삭제되지 않습니다.
