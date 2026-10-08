# CMB DXF Viewer PC v3.29 — GPT용 버전 설명

2026-10-08에 보관한 최신 로컬 PC 시험용 설치본입니다. GitHub main의 개발 코드와 이 배포 스냅샷은 별개입니다. main에는 이후 작업(빠른 표시, 클릭 구간 좌표 추출 등)이 있으므로 그 기능을 이 설치본의 기능으로 설명하면 안 됩니다.

## 다운로드와 설치
- [Windows x64 설치본 다운로드](https://raw.githubusercontent.com/ysjus2/cmb_test/main/pc-releases/v3.29/CMB_DXF_Viewer_v3.29_Setup_TEST.exe)
- 파일 이름: CMB_DXF_Viewer_v3.29_Setup_TEST.exe
- 크기: 38,213,303 bytes
- SHA256: a89b9af9440df9e60e72c1d2b5b634757e6268dc9de2a17e3c9a3c1924a008a9
- Windows x64, 관리자 권한 필요. 실행 → 설치 경로 선택 → 설치 → 완료 후 실행.
- 로그인/설치 계정/서버 승인 없이 사용. VC++ x64 Runtime이 없을 경우 설치 중 Microsoft 다운로드에 인터넷이 필요할 수 있습니다.
- 시험용(TEST) 배포본이며 정식 승인 릴리스라는 의미는 아닙니다.

## 현재 기능
- DXF 읽기 전용 Viewer: 확대/축소, PAN, 전체보기, 레이어 ON/OFF, 객체 선택, 좌표 확인, 거리·면적 측정.
- 블록 내부 객체·속성, 사용자 정의 ESSENPOLY 및 ASDKESSENLINKER 관로 좌표 복구. 레이어/미표시 객체 점검.
- 광주간선: 시작과 끝 함체 또는 케이블 끝점을 선택하면 유일한 연결 경로만 추출. STUB 및 경로 밖 가지 제외. 단절/복수 경로는 안내하고 추출 거부.
- 광 Excel: `광주간선` 단일 시트. 케이블번호, 심수, 길이, 시작/끝 함체, 객체ID, 시작/끝 경위도. 전체 경로 양끝은 실제 케이블 끝점, 중간 함체는 삽입 좌표 사용. 별도 함체/굴곡점 시트 없음.
- 관로 Excel: `100mm_주관로` 단일 시트. 객체ID, 지름, 길이, 시작/끝 시설 유형, 맨홀명 또는 저장된 전주 코드, 경위도.
- 관로 끝점과 시설 삽입점이 0.1 CAD 단위 안에서 유일하게 대응될 때 해당 시설 사용. 시설이 없거나 겹치면 미확인/복수시설로 표시하고 원래 끝점 좌표 유지.
- 추출 모드에서도 건물·도로·지번 등 배경 표시 가능. 배경은 Excel 추출 대상에서 제외.
- 지번, CN_L_Pole_ID, CN_C_Tap_Window는 최초 기본 체크 해제. 사용자가 직접 켤 수 있음.
- 기존 전체 레이어 Excel 출력은 별도 메뉴로 유지.
- 좌표계: EPSG:5174, 2097, 5181, 5179, 5186.

## 해석 시 반드시 지킬 조건
- 100mm는 도면의 명시 관경 또는 사용자가 확인한 세션 지정값만 인정. 50mm와 미확인은 출력 제외. PL0/P0만으로 지름을 추정하지 않음. 사용자 지정은 현재 세션에만 적용.
- 광주간선이라는 출력명은 운영상 주간선 등급을 인증하는 의미가 아님.
- DWG 읽기/변환, 원본 DXF 수정·저장, 서버 업로드, AI 호출 없음. 도면 분석과 Excel 생성은 PC 로컬에서 실행.
- 미지원 사용자 정의 객체의 완전한 표시를 보장하지 않음. 도면 점검 결과 확인 필요.

## GPT가 읽을 소스
`source/`는 설치본 빌드 작업 폴더의 적용 완료 Python 소스 스냅샷입니다. 루트 `desktop/CadExcelConverter/` 개발 소스와 혼동하지 마세요.
- main.py: v3.29 앱 창·작업 흐름
- viewer.py: 표시·선택·측정·레이어
- network_extract_ui.py: 시작/끝 선택, 관경 확인, 추출 UI
- network_extract.py: 연결 경로·단일 시트 Excel
- pipe_endpoints.py: 맨홀/전주 끝점 대응
- converter.py / essenpoly_recovery.py / geometry_complete.py: DXF·좌표·사용자 정의 형상
- CMB_DXF_Viewer.spec: 실제 빌드 폴더의 PyInstaller 설정
- CMB_DXF_Viewer_Setup.nsi / build-installer.ps1: v3.29 설치 패키지 설정
- VERSION_HISTORY.md: 기존 기능 이력. 상단의 오래된 모든 레이어 기본 체크 설명보다 v3.27 이후 규칙을 우선.
- THIRD_PARTY_LICENSES.txt: 빌드 작업 폴더의 배포 고지

소스 실행은 Python과 ezdxf/openpyxl/pyproj가 필요합니다. `source/requirements.txt`는 기존 개발 의존성 선언(ezdxf 1.4.2)입니다. 이번 재검증에 사용한 로컬 runtime은 ezdxf 1.0.3, openpyxl 3.1.5, pyproj 3.7.2였습니다. 바이너리와 동일한 환경 재현 여부는 별도로 확인해야 합니다. 이미 적용된 소스이므로 apply_*.py를 다시 실행하지 마세요.

## 검증 기록
2026-10-08에 이 스냅샷에서 기존 7개 테스트 통과: ESSENPOLY, 관로 복구, 전체 레이어, 광망/관경 추출, 확대/PAN, 관로 끝점·단일 시트, 기본 selftest. 설치본 SHA256이 기존 v3.29 배포 기록과 일치함을 확인했습니다. 이번 저장 과정에서는 새 설치나 GUI 실행을 수행하지 않았습니다.

## GPT에 전달할 문장
“이 저장소의 pc-releases/v3.29/README.md와 source/를 먼저 읽고 PC v3.29 설치본을 분석해 줘. main 개발 코드와 구분하고, 광주간선/100mm 관로 단일 시트와 관경 미확인 제외 조건을 유지해 줘.”
