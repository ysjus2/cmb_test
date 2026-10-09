# 현재 프로젝트 작업 기준

먼저 CURRENT_VERSION.json, CURRENT_BEHAVIOR.md, SERVER_INTEGRATION.md를 읽는다.
현재 PC 기준은 v3.36이며 desktop/CadExcelConverter의 main.py를 직접 빌드한다.
pc-releases/current만 활성 배포 폴더로 유지한다. 과거 apply_* 스크립트로 소스를 재생성하지 않는다.
서버는 다음 개발 단계다. 참고 코드의 존재를 서버 연결 완료로 설명하지 않는다.
도면·캐시·추출 데이터·토큰을 커밋하지 않는다. 서버 작업 전 데이터 계약과 주소·인증 방식을 확인한다.
지역객체ID와 순수 객체ID를 유지하며 절점별 행을 임의로 중복 제거하지 않는다.
추출 화면은 대상만 그리되 전체 100mm 관로와 전체 자가주 추출은 화면 범위·레이어 숨김에 영향받지 않아야 한다.
관경은 EXMAP_POLELINK의 관경×본수 표기에서 읽고 미기재·복수시설·형상 미확인을 추정해서 메우지 않는다.
회귀 테스트는 desktop/CadExcelConverter/run_checks.py로 실행한다. 실제 군 도면 시험은 로컬에서만 수행한다.
