# CMB DXF Viewer + Excel v3.36

현재 PC 배포본은 **v3.36**입니다. 과거 배포 폴더와 버전별 패치 스크립트를 정리하고 이 버전의 실행 파일과 소스를 기준으로 유지합니다.

- [Windows x64 실행 파일 다운로드](https://raw.githubusercontent.com/ysjus2/cmb_test/main/pc-releases/current/CMB_DXF_Viewer_v3.36.exe)
- [다운로드·실행 안내](PC_DOWNLOAD.md)
- **[현재 동작과 특징 — GPT/Codex 먼저 읽기](CURRENT_BEHAVIOR.md)**
- **[서버 연동 준비·데이터 계약](SERVER_INTEGRATION.md)**
- [버전과 실행 파일/소스 SHA256](CURRENT_VERSION.json)
- [현재 PC 소스·빌드 방법](desktop/CadExcelConverter/README.md)

DXF 캐시, 확대 단계별 표시, 광주간선 추출, 전체 100mm 관로와 맨홀·전주 위치 추출, 자가주 좌표 추출을 제공합니다. 추출 화면은 대상 도형만 표시하고 지형·명칭을 숨깁니다. Excel에는 순수 객체ID와 지역객체ID를 함께 출력합니다.

현재 PC 실행본은 로컬 방식입니다. 서버 로그인·업로드가 연결된 상태는 아니며, 다음 작업은 이 기준 버전에 서버 연동을 추가하는 것입니다.

`app/`의 Android 소스는 별도 구성입니다. [Android 사용 안내](CAD_NETWORK_USAGE.md), [서명 설정](SIGNING_SETUP.md)을 참고하세요. Android 기능을 현재 PC 배포본 기능과 혼동하지 마세요.

실제 군 도면, 캐시, 추출 파일과 인증 정보는 저장소에 포함하지 않습니다. 기존 Git 커밋 이력은 변경 추적용으로 보존하며 활성 배포는 `pc-releases/current` 하나입니다.
