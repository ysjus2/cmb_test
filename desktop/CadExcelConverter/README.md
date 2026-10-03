# CMB DXF Viewer + Excel

회사 내부 사용을 전제로 한 Windows DXF 읽기 전용 Viewer + Excel 추출 프로그램입니다.

## 고정 보안/라이선스 정책
- 입력은 DXF만 지원
- DWG 읽기/변환 기능 없음
- ODA, LibreDWG 등 DWG 엔진 미포함
- 원본 DXF 수정/저장 기능 없음
- 서버 업로드 없음
- AI 호출 없음
- 인터넷 연결 불필요
- 모든 작업은 로컬 PC에서 수행

## Viewer 기능
- DXF 열기
- 마우스 휠 확대/축소
- 우클릭/중클릭 드래그 PAN
- 전체보기
- 레이어 개별 ON/OFF / 전체 보기 / 전체 숨김
- 객체 클릭 선택
- Shift + 클릭 다중 객체 선택/해제
- ESC 선택 해제
- 선택 객체 유형 / 레이어 / Handle / 블록 / 문자 정보 확인
- 현재 마우스 CAD X/Y 좌표 표시
- 좌표 확인 모드
- 두 점 거리 측정
- 다각형 면적/둘레 측정
- LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, POINT, TEXT, MTEXT, INSERT,
  SPLINE, ELLIPSE, SOLID, TRACE, 3DFACE, 일부 HATCH/RAY/XLINE 표시
- INSERT 블록은 virtual entities를 이용해 읽기 전용으로 화면 전개

## v2.2 기반 레이어 선택
- 처음 DXF를 열면 모든 레이어가 체크되어 Viewer에 표시됨
- 체크된 레이어 = Viewer에 표시되는 레이어 = Excel 추출 대상
- 체크 해제 즉시 Viewer에서 해당 레이어가 사라지고 Excel 추출 대상에서도 제외됨
- 다시 체크하면 Viewer에 다시 표시되고 Excel 추출 대상에도 포함됨
- 일반 행 클릭: 해당 행을 파란색 선택
- 다른 행 일반 클릭: 기존 선택 해제 후 새 행을 파란색 선택
- Shift + 행 클릭: 기준점부터 해당 행까지 연속 파란 범위 선택
- 파란 범위 안 체크박스 클릭:
  클릭 항목이 미체크면 범위 전체 체크,
  체크 상태면 범위 전체 체크 해제
- 체크 변경 후 파란 범위 유지

## Excel 추출
선택한 레이어를 각각 Excel 시트로 생성합니다.
- ENTITY_TYPE
- ENTITY_ID
- BLOCK_NAME
- SEQ
- CAD_X / CAD_Y
- 경도 / 위도
- 길이
- TEXT
- ATTRIBUTES
- XDATA
- LAYER_INDEX / INFO 시트

지원 좌표계:
- EPSG:5174
- EPSG:2097
- EPSG:5181
- EPSG:5179
- EPSG:5186

## 배포 파일
- CMB_DXF_Viewer.exe
- README.txt
- THIRD_PARTY_LICENSES.txt

이 프로그램은 DXF 원본을 저장하거나 변경하는 기능을 포함하지 않습니다.
