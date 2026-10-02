# 셀 위치 DB Android 앱

이 저장소는 GitHub Actions에서 Android APK를 자동 생성하도록 구성되어 있습니다.

## 앱 기능
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
