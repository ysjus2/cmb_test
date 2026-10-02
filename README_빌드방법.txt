셀 위치 DB Android 앱 프로젝트

앱 기능
- 앱 실행 시 위치 권한 요청
- 허용 후 현재 GPS 좌표 자동 입력
- 현재 위치 다시 가져오기
- 셀명 / 셀번호 / 상위국사 / 상향포트 / 하향포트 / 주소 / 전주번호
  / 경도 / 위도 / 셀구분(일반/아파트) / 비고
- 휴대폰 내부 저장
- 저장 데이터 수정 / 삭제
- CSV 추출
- CSV 불러오기
- HTTPS / 브라우저 / Termux 불필요

Android Studio 빌드
1. Android Studio에서 이 폴더를 Open
2. Gradle Sync
3. Build > Build APK(s)
4. app/build/outputs/apk/debug/app-debug.apk 생성
5. APK를 Android 휴대폰으로 복사 후 설치

GitHub 자동 APK 빌드
- 프로젝트 전체를 GitHub 저장소에 올리면 .github/workflows/build-apk.yml이 자동 실행됩니다.
- Actions 결과의 Artifact에서 CellLocationDB-debug-apk를 내려받으면 됩니다.

주의
- 최초 실행 시 Android 위치 권한을 허용해야 합니다.
- CSV는 Android 시스템 파일 선택창으로 저장/불러오므로 저장소 권한은 별도로 필요하지 않습니다.
