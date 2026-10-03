# CAD Network Android 앱

현재 버전은 CAD 변환 지역 Excel을 읽는 네트워크 관리 앱입니다.
설치 패키지는 `com.ysjus2.cadnetwork`이며 고정 서명 release APK를 빌드합니다.
지역 파일 선택, 지도 레이어 및 편집 방법은 [CAD_NETWORK_USAGE.md](CAD_NETWORK_USAGE.md),
서명 설정은 [SIGNING_SETUP.md](SIGNING_SETUP.md)를 참고하세요.
아래 ONU/CSV 안내는 초기 버전에 해당합니다.

이 저장소는 GitHub Actions에서 Android APK를 자동 생성하도록 구성되어 있습니다.

## 집과 회사에서 이어서 개발하기

처음 사용하는 PC에서는 GitHub 저장소를 `git clone <저장소 URL>`로 내려받습니다.
각 PC에서 Git 작성자 이름과 이메일, GitHub 인증을 설정해야 합니다.

작업 시작 전에 실행합니다.

```powershell
git status
git pull --ff-only
```

작업을 마치면 변경 내용을 확인하고 저장합니다.

```powershell
git diff
git add .
git commit -m "변경 내용 요약"
git push
```

다른 PC로 이동하기 전에 푸시가 성공했는지 확인합니다. 로컬에 미커밋 변경이
있거나 `pull --ff-only`가 실패하면 변경 내용을 확인하고 정리한 뒤 진행합니다.
`main` 또는 `master`에 푸시하면 APK 빌드가 자동 실행됩니다.

빌드 결과물, PC별 Android SDK 경로(`local.properties`), 서명 키는 Git에서 제외됩니다.
휴대폰에 저장한 셀 정보와 CSV 데이터는 소스 코드 동기화와 별도로 백업합니다.

## 앱 기능
- 앱 실행 시 저장된 ONU 위치 지도 표시
- 빨간 ONU 마커 선택 시 저장한 구성정보 확인
- 파란 현재 위치 표시 및 가까운 ONU 최대 5건 직선거리 조회
- 전체 ONU 보기 / 내 위치로 이동
- ONU 정보 등록·수정·CSV 관리 화면 이동
- 지도 배경: 카카오맵 또는 OpenStreetMap (인터넷 연결 필요), 저장 정보는 휴대폰 내부 유지
- 앱 실행 시 위치 권한 요청
- 현재 GPS 좌표 자동 입력
- 셀명
- 셀번호
- 상위국사
- 상향포트
- 하향포트
- 주소
- 전주번호
- 경도
- 위도
- 셀구분(일반/아파트)
- 비고
- 휴대폰 내부 저장
- 수정 / 삭제
- CSV 내보내기
- CSV 불러오기

## 카카오맵 연결

카카오 네이티브 앱 키가 설정된 빌드는 카카오맵을 사용합니다. 키가 없는 빌드는
기존 OpenStreetMap을 사용합니다. 지도 렌더링은 `MapRenderer`로 분리되어 ONU
데이터 및 GPS 계산과 독립적입니다.

1. 카카오디벨로퍼스에서 앱을 만들고 카카오맵 사용 설정을 켭니다.
2. 네이티브 앱 키의 Android 앱 정보에 패키지명 `com.example.celldb`를 등록합니다.
3. GitHub 저장소 Settings → Secrets and variables → Actions에서
   `KAKAO_NATIVE_APP_KEY`라는 Repository secret에 네이티브 앱 키를 저장합니다.
4. Actions에서 Build APK를 실행합니다. 다운로드한 아티팩트의
   `kakao-key-hash.txt` 내용을 카카오 Android 키 해시로 등록합니다.
5. 같은 아티팩트의 `app-debug.apk`를 설치하고 지도 인증을 확인합니다.

로컬 빌드는 `kakao.properties.example`을 `kakao.properties`로 복사해 키를 입력하거나
`KAKAO_NATIVE_APP_KEY` 환경변수를 사용합니다. 키 파일은 Git에서 제외됩니다.
어드민 키나 REST API 키를 사용하지 않습니다.

현재 Actions의 개발 서명은 빌드마다 달라질 수 있습니다. 새 빌드를 설치할 때는
해당 빌드의 공개 키 해시를 등록해야 합니다. 앱 업데이트가 서명 불일치로 거부될
수 있으므로 재설치 전 반드시 ONU 데이터를 백업해야 합니다. 지속적인 배포를 위한
고정 서명은 별도로 설정해야 하며, 서명 키를 Git이나 Actions 캐시에 보관하지 않습니다.

---

## GitHub에서 APK 만드는 방법

### 1. GitHub 새 저장소 만들기
GitHub에 로그인한 뒤 새 Repository를 만듭니다.

예시 이름:
`CellLocationDB`

Public 또는 Private 어느 쪽도 가능합니다.

### 2. 이 ZIP 압축을 PC에서 풀기
압축을 풀면 아래 파일이 보입니다.

- `.github`
- `app`
- `build.gradle`
- `settings.gradle`
- `README.md`

### 3. GitHub 저장소에 파일 업로드
저장소 화면에서:

`Add file` → `Upload files`

압축 해제된 폴더 안의 파일/폴더를 모두 업로드합니다.

중요:
`.github` 폴더도 반드시 같이 올라가야 합니다.

### 4. Commit
아래쪽의:

`Commit changes`

버튼을 눌러 업로드를 완료합니다.

### 5. Actions 실행
상단 메뉴에서:

`Actions`

를 누릅니다.

`Build APK` 작업이 자동 실행됩니다.

자동 실행되지 않으면:

`Build APK` → `Run workflow`

를 눌러 직접 실행합니다.

### 6. APK 다운로드
빌드가 완료되면 실행된 작업을 클릭합니다.

화면 아래:

`Artifacts`

에서

`CellLocationDB-debug-apk`

를 다운로드합니다.

압축을 풀면:

`app-debug.apk`

파일이 있습니다.

### 7. Android 휴대폰에 설치
`app-debug.apk`를 휴대폰으로 옮기고 실행합니다.

Android가 외부 앱 설치 권한을 물으면 해당 파일관리자/브라우저에 대해
`이 출처의 앱 허용`
을 켜면 설치할 수 있습니다.

---

## APK 첫 실행
앱을 실행하면 위치 권한을 요청합니다.

`앱 사용 중에만 허용`

을 선택하면 현재 위치를 자동으로 읽습니다.

GPS가 꺼져 있으면 Android 위치 설정을 켜야 합니다.

---

## CSV 백업
앱 내부 DB는 휴대폰 내부에 저장됩니다.

CSV 추출 버튼을 이용해 정기적으로 백업하는 것을 권장합니다.

CSV 열 순서:

셀명, 셀번호, 상위국사, 상향포트, 하향포트, 주소, 전주번호, 경도, 위도, 셀구분, 비고
