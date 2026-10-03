# CAD → Excel 변환기

Windows에서 독립 실행되는 오프라인 CAD 변환 프로그램입니다.

## 보안 구조
- AI 호출 없음
- 서버 업로드 없음
- 인터넷 연결 불필요
- 선택한 CAD 파일과 출력 Excel은 로컬 PC에서만 처리

## 입력
- DXF: 프로그램이 직접 읽음
- DWG: 로컬 PC에 설치된 ODA File Converter를 호출하여 임시 DXF로 변환한 뒤 처리

## 출력 Excel
현재 모바일 앱과 동일한 구조입니다.
- CELL
- FACILITY
- EQUIPMENT
- FIBER
- COAX
- INFO

기본 좌표계는 현재 샘플과 정확히 일치하는 EPSG:5174이며 WGS84(EPSG:4326) 경위도로 변환합니다.

## 자동 분류
CAD 레이어/블록명을 기반으로 분류합니다.
- 전주/맨홀 → FACILITY
- ONU/TAP/AMP/광클로저/광센터/수동소자 → EQUIPMENT
- 광케이블 → FIBER
- 동축케이블 → COAX

CAD entity handle을 시설ID/장비ID/선로ID로 사용하므로 현재 추출 DB의 ID 체계와 호환됩니다.

## Windows 실행 파일
GitHub Actions의 Build CAD Excel Converter workflow가 Windows x64 단일 EXE를 생성합니다.

## 빌드 산출물
- CAD_Excel_Converter.exe
- README.txt
