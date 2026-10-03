# 현재 Codex 카카오맵 프로젝트에 붙이는 방법

이 패키지는 "카카오맵이 이미 정상 표시되는 현재 앱"에 Excel 지역 DB 연결부만 추가하는 용도입니다.

## 1. 복사할 파일

`app/src/main/java/com/example/celldb/network/`
- NetworkModels.java
- SimpleXlsxReader.java
- NetworkExcelRepository.java
- RegionExcelLoader.java
- KakaoNetworkRenderer.java

`app/src/main/res/drawable/`
- map_cell.png
- map_facility.png
- map_equipment.png

현재 프로젝트의 package가 `com.example.celldb`가 아니라면
Codex가 package/import를 현재 프로젝트 namespace에 맞게 바꾸면 됩니다.

## 2. Gradle

추가 Excel 라이브러리는 필요 없습니다.
SimpleXlsxReader가 Android 기본 ZIP/XML 기능으로 .xlsx를 읽습니다.

카카오맵 SDK는 현재 프로젝트에서 이미 연동되어 있으므로 기존 설정을 유지합니다.
공식 SDK v2 기준 Maven dependency 예시는 현재 `com.kakao.maps.open:android:2.15.2`입니다.
기존 카카오맵 버전이 정상 동작하면 굳이 변경하지 마세요.

## 3. 지역 Excel 선택

Activity/Fragment에서 Android 파일 선택기를 사용합니다.

```java
private KakaoNetworkRenderer networkRenderer;
private RegionExcelLoader excelLoader;

private final ActivityResultLauncher<String[]> openRegionExcel =
    registerForActivityResult(new ActivityResultContracts.OpenDocument(), uri -> {
        if (uri == null) return;

        excelLoader.load(uri, new RegionExcelLoader.Callback() {
            @Override public void onLoaded(NetworkData data) {
                runOnUiThread(() -> {
                    networkRenderer.render(data);
                    Toast.makeText(CurrentActivity.this,
                        "CELL " + data.cells.size()
                        + " / 시설 " + data.facilities.size()
                        + " / 장비 " + data.equipment.size()
                        + " / 광 " + data.fiber.size()
                        + " / 동축 " + data.coax.size(),
                        Toast.LENGTH_LONG).show();
                });
            }

            @Override public void onError(Exception e) {
                runOnUiThread(() ->
                    Toast.makeText(CurrentActivity.this,
                        "Excel 읽기 실패: " + e.getMessage(),
                        Toast.LENGTH_LONG).show());
            }
        });
    });
```

필요 import:
```java
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import com.example.celldb.network.*;
import com.example.celldb.network.NetworkModels.NetworkData;
```

초기화:
```java
excelLoader = new RegionExcelLoader(getContentResolver());
```

카카오맵의 기존 `onMapReady(KakaoMap kakaoMap)` 안:
```java
networkRenderer = new KakaoNetworkRenderer(kakaoMap);
```

"지역 DB 불러오기" 버튼:
```java
openRegionExcel.launch(new String[] {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
});
```

onDestroy:
```java
if (excelLoader != null) excelLoader.close();
```

## 4. 레이어 스위치

```java
networkRenderer.setCellVisible(true);
networkRenderer.setFacilityVisible(true);
networkRenderer.setEquipmentVisible(true);
networkRenderer.setFiberVisible(true);
networkRenderer.setCoaxVisible(true);
```

UI에 체크박스/스위치를 붙여 각각 호출하면 됩니다.

## 5. Excel 구조

지역 파일 하나에 아래 시트가 있어야 합니다.

- CELL
- FACILITY
- EQUIPMENT
- FIBER
- COAX

현재 함께 제공한 `CMB_GN_HP_모바일앱용_지역DB.xlsx`가 기준 포맷입니다.

FIBER/COAX는 한 선로가 여러 행을 사용합니다.
`선로ID + 순번`으로 좌표를 묶어 카카오맵 RouteLine으로 표시합니다.

## 6. 성능 방향

- 전주/맨홀/장비는 `LodLabelLayer`를 사용하여 다량 마커 렌더링
- 광/동축은 `RouteLine`을 사용하여 다량 선로 렌더링
- 지역별 Excel 하나만 읽으므로 개발단계에서 전체 데이터 일괄 로딩을 피함
- 서버/DB 없음

## 7. 현재 GPS와 연결

현재 Codex 앱에서 이미 카카오맵 GPS 현재위치를 표시하고 있다면 그 코드는 유지합니다.
Excel 레이어는 그 지도 위에 별도로 올라갑니다.

즉:
GPS 현재위치 + CELL/FACILITY/EQUIPMENT 마커 + FIBER/COAX 선로
를 한 지도에서 동시에 봅니다.
