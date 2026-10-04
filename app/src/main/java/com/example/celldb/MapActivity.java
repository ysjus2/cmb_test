package com.example.celldb;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.*;
import android.net.Uri;
import android.widget.CheckBox;
import android.widget.HorizontalScrollView;
import android.widget.Toast;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import com.example.celldb.network.KakaoNetworkRenderer;
import com.example.celldb.network.NetworkModels.*;

public class MapActivity extends Activity {
    private final ArrayList<CadRecord> visibleRecords = new ArrayList<>();
    private final ArrayList<MapPoint> visiblePoints = new ArrayList<>();
    private final ArrayList<MapPoint> boundsPoints = new ArrayList<>();
    private MapRenderer map;
    private CadDatabase db;
    private boolean mapReady;
    private boolean destroyed;
    private String mapError;
    private TextView status;
    private LocationManager locationManager;
    private Location currentLocation;
    private boolean requestingLocation;
    private boolean centerOnFix;
    private KakaoNetworkRenderer networkRenderer;
    private NetworkData networkData;
    private final boolean[] layers = {true,true,true};
    private ArrayList<CadRecord> allRecords = new ArrayList<>();
    private int loadGeneration;
    private boolean pendingShowAll;
    private final String[] categories = LayerGroups.IDS;
    private final Map<String,CadRecord> networkRecords = new HashMap<>();
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private Button importButton;
    private TextView regionStatus;
    private TextView selectionStatus;
    private Button measureButton;
    private final DistanceMeasurement measurements=new DistanceMeasurement();
    private CadRecord selectedRecord;
    private DistanceMeasurement.Line selectedMeasurement;
    private final ArrayList<ArrayList<CadRecord>> displayedLines=new ArrayList<>();
    private long ignoreTapUntil;
    private boolean escapeConsumed;


    private final LocationListener listener = new LocationListener() {
        @Override public void onLocationChanged(Location location) { updateLocation(location); }
        @Override public void onProviderEnabled(String provider) { }
        @Override public void onProviderDisabled(String provider) {
            status.setText("위치 제공 기능이 꺼졌습니다. 휴대폰 위치 설정을 확인하세요.");
        }
        @Override public void onStatusChanged(String provider, int state, Bundle extras) { }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        db = new CadDatabase(this);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });

        TextView title = new TextView(this);
        title.setText("CAD 네트워크 지도");
        title.setTextSize(21);
        title.setTextColor(Color.WHITE);
        title.setBackgroundColor(Color.rgb(15, 23, 42));
        title.setPadding(dp(16), dp(12), dp(16), dp(12));
        root.addView(title);

        status = new TextView(this);
        status.setPadding(dp(12), dp(8), dp(12), dp(8));
        root.addView(status);

        LinearLayout actions = new LinearLayout(this);
        addButton(actions, "내 위치", () -> { centerOnFix = true; requestLocation(); });
        addButton(actions, "전체 보기", this::showAll);
        addButton(actions, "가까운 시설", this::showNearest);
        root.addView(actions);
        LinearLayout tools=new LinearLayout(this);
        measureButton=new Button(this);measureButton.setText("거리 측정");measureButton.setTextSize(13);
        measureButton.setOnClickListener(v->{
            if(measurements.active())finishMeasurement();
            else {measurements.start();selectedRecord=null;selectedMeasurement=null;measureButton.setText("측정 종료");
                selectionStatus.setText("지도를 눌러 측정점을 추가하세요 · Esc 또는 측정 종료로 완료");drawMeasurements();}
        });
        tools.addView(measureButton,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
        addButton(tools,"선택 메뉴",this::showSelectionMenu);root.addView(tools);
        selectionStatus=new TextView(this);selectionStatus.setText("객체 선택 후 길게 누르기 / 우클릭 → 속성");
        selectionStatus.setPadding(dp(12),dp(4),dp(12),dp(4));root.addView(selectionStatus);
        importButton = new Button(this);
        importButton.setText("지역 DB 불러오기 (.xlsx)");
        importButton.setTextSize(13);
        importButton.setOnClickListener(v -> {
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.setType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            startActivityForResult(intent,3001);
        });
        root.addView(importButton);
        regionStatus = new TextView(this);
        regionStatus.setText(getSharedPreferences("network_prefs",MODE_PRIVATE).getString("region_name","지역 Excel을 선택하세요 · 광: 파랑 / 동축: 주황"));
        regionStatus.setTextSize(11);
        regionStatus.setPadding(dp(12),dp(2),dp(12),dp(2));
        root.addView(regionStatus);
        HorizontalScrollView scroll = new HorizontalScrollView(this);
        LinearLayout toggles = new LinearLayout(this);
        String[] names = LayerGroups.NAMES;
        for (int i=0;i<names.length;i++) {
            final int index=i;
            CheckBox check = new CheckBox(this);
            check.setText(names[i]); check.setTextSize(12);
            layers[i]=getSharedPreferences("network_prefs",MODE_PRIVATE).getBoolean("group_"+categories[i],true);
            check.setChecked(layers[i]);
            check.setOnCheckedChangeListener((button,checked) -> {
                layers[index]=checked;
                getSharedPreferences("network_prefs",MODE_PRIVATE).edit().putBoolean("group_"+categories[index],checked).apply();
                loadMarkers();
            });
            toggles.addView(check);
        }
        scroll.addView(toggles); root.addView(scroll);
        Button settings = new Button(this);
        settings.setText("설정 · 레이어 편집");
        settings.setOnClickListener(v -> showLayerSettings());
        root.addView(settings);

        map = BuildConfig.KAKAO_NATIVE_APP_KEY.isEmpty() ? new OsmMapRenderer(this)
                : new KakaoMapRenderer(this, BuildConfig.KAKAO_NATIVE_APP_KEY);
        map.setMapClick(this::onMapTap);
        MapInteractionView interaction=new MapInteractionView(this,()->{ignoreTapUntil=android.os.SystemClock.uptimeMillis()+600;showSelectionMenu();});
        interaction.addView(map.getView(),new android.widget.FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(interaction,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1f));

        TextView attribution = new TextView(this);
        attribution.setText((map instanceof OsmMapRenderer ? "© OpenStreetMap contributors" : "카카오맵")
                + " · CAD 좌표 변환 데이터");
        attribution.setTextSize(11);
        attribution.setGravity(Gravity.CENTER);
        attribution.setPadding(dp(4), dp(6), dp(4), dp(6));
        root.addView(attribution);

        setContentView(root);
        locationManager = (LocationManager) getSystemService(LOCATION_SERVICE);

        map.start(() -> {
            if (destroyed) return;
            mapReady = true;
            mapError = null;
            if (map instanceof KakaoMapRenderer) {
                networkRenderer = new KakaoNetworkRenderer(((KakaoMapRenderer)map).getKakaoMap(), p ->
                    runOnUiThread(() -> {
                        CadRecord record=networkRecords.get(p.id);
                        if (!destroyed && record!=null) selectRecord(record,new MapPoint(p.lat,p.lon));
                    }));
            }
            pendingShowAll=true;loadMarkers();
        }, message -> {
            mapError = message;
            status.setText(message);
        });
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private void addButton(LinearLayout parent, String text, Runnable action) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextSize(13);
        button.setOnClickListener(v -> action.run());
        parent.addView(button, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
    }

    @Override protected void onResume() {
        super.onResume();
        map.resume();
        loadMarkers();
        requestLocation();
    }

    @Override protected void onPause() {
        stopLocation();
        map.pause();
        super.onPause();
    }

    @Override protected void onDestroy() {
        destroyed = true;
        worker.shutdownNow();
        map.destroy();
        super.onDestroy();
    }

    @Override protected void onActivityResult(int requestCode,int resultCode,Intent result) {
        super.onActivityResult(requestCode,resultCode,result);
        if (requestCode!=3001 || resultCode!=RESULT_OK || result==null || result.getData()==null) return;
        Uri uri=result.getData();
        importButton.setEnabled(false);
        regionStatus.setText("지역 Excel을 읽는 중…");
        worker.execute(() -> {
            try {
                ArrayList<CadRecord> imported=XlsxCadImporter.read(this,uri);
                if (destroyed) return;
                db.replaceCadRows(imported);
                String name="지역 DB";
                try (android.database.Cursor c=getContentResolver().query(uri,new String[]{android.provider.OpenableColumns.DISPLAY_NAME},null,null,null)) {
                    if(c!=null && c.moveToFirst()) name=c.getString(0);
                }
                final String displayName=name;
                getSharedPreferences("network_prefs",MODE_PRIVATE).edit().putString("region_name",name).apply();
                runOnUiThread(() -> {
                    if(destroyed) return;
                    importButton.setEnabled(true); regionStatus.setText(displayName);
                    pendingShowAll=true;
                    loadMarkers();
                    Toast.makeText(this,"지역 DB "+imported.size()+"행 저장 완료",Toast.LENGTH_LONG).show();
                });
            } catch(Exception error) {
                runOnUiThread(() -> {
                    if(destroyed) return;
                    importButton.setEnabled(true);
                    regionStatus.setText("Excel 읽기 실패: "+error.getMessage());
                });
            }
        });
    }

    private android.content.SharedPreferences layerPrefs() {
        return getSharedPreferences("network_prefs",MODE_PRIVATE);
    }

    private String group(CadRecord r) {
        if(LayerGroups.excluded(r.layer)) return "";
        return layerPrefs().getString("assignment_"+LayerGroups.key(r),LayerGroups.defaultGroup(r.layer,r.category));
    }

    private boolean recordVisible(CadRecord r) {
        String group=group(r);
        for(int i=0;i<categories.length;i++) if(categories[i].equals(group))
            return layers[i] && layerPrefs().getBoolean("sublayer_"+LayerGroups.key(r),true);
        return false;
    }

    private void showLayerSettings() {
        new AlertDialog.Builder(this).setTitle("설정 · 레이어 편집")
            .setItems(LayerGroups.NAMES,(dialog,which)->editGroupLayers(categories[which],LayerGroups.NAMES[which]))
            .setNegativeButton("닫기",null).show();
    }

    private void editGroupLayers(String selectedGroup,String title) {
        TreeMap<String,CadRecord> representatives=new TreeMap<>();
        Map<String,Integer> counts=new HashMap<>();
        for(CadRecord r:allRecords) {
            if(!selectedGroup.equals(group(r)))continue;
            String key=LayerGroups.key(r); representatives.put(key,r);
            counts.put(key,counts.containsKey(key)?counts.get(key)+1:1);
        }
        android.widget.ScrollView scroll=new android.widget.ScrollView(this);
        LinearLayout body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(12),dp(8),dp(12),dp(8));scroll.addView(body);
        TextView help=new TextView(this);
        help.setText("체크한 레이어만 표시합니다. 그룹을 껐다 켜도 선택 상태가 유지됩니다. 아래 목록에서 소속 그룹을 변경할 수 있습니다.");
        body.addView(help);
        if(representatives.isEmpty()){TextView empty=new TextView(this);empty.setText("불러온 레이어가 없습니다.");body.addView(empty);}
        for(Map.Entry<String,CadRecord> entry:representatives.entrySet()) {
            String key=entry.getKey();
            CheckBox check=new CheckBox(this);check.setText(key+" · "+counts.get(key)+"행");
            check.setChecked(layerPrefs().getBoolean("sublayer_"+key,true));
            check.setOnCheckedChangeListener((button,checked)->layerPrefs().edit().putBoolean("sublayer_"+key,checked).apply());
            body.addView(check);
            android.widget.Spinner assignment=new android.widget.Spinner(this);
            assignment.setAdapter(new android.widget.ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,LayerGroups.NAMES));
            int initial=Arrays.asList(categories).indexOf(selectedGroup);assignment.setSelection(initial);
            assignment.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
                public void onItemSelected(android.widget.AdapterView<?> parent,android.view.View view,int position,long id){
                    layerPrefs().edit().putString("assignment_"+key,categories[position]).apply();
                }
                public void onNothingSelected(android.widget.AdapterView<?> parent){}
            });
            body.addView(assignment);
        }
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(title+" · 레이어 편집").setView(scroll)
            .setPositiveButton("완료",null).create();
        dialog.setOnDismissListener(d->loadMarkers());dialog.show();
    }

    private void applyVisibility() {
        // Data is filtered by group AND sublayer before either renderer receives it.
        if(networkRenderer==null)return;
        networkRenderer.setCellVisible(true);networkRenderer.setFacilityVisible(true);
        networkRenderer.setEquipmentVisible(true);networkRenderer.setFiberVisible(true);networkRenderer.setCoaxVisible(true);
    }

    private void loadMarkers() {
        final int generation=++loadGeneration;
        worker.execute(()->{
            ArrayList<CadRecord> loaded=db.loadAll();
            runOnUiThread(()->{
                if(destroyed || generation!=loadGeneration)return;
                allRecords=loaded;renderMarkers();
                if(pendingShowAll){pendingShowAll=false;showAll();}
            });
        });
    }

    private void renderMarkers() {
        if(selectedRecord!=null){
            String key=selectedRecord.stableKey();selectedRecord=null;
            for(CadRecord r:allRecords)if(r.stableKey().equals(key)){selectedRecord=r;break;}
            if(selectedRecord==null)selectionStatus.setText("객체를 선택하세요.");
        }
        visibleRecords.clear(); visiblePoints.clear(); boundsPoints.clear(); networkRecords.clear();
        if(mapReady) { map.clearOnuMarkers(); map.clearNetworkLines(); }
        networkData=new NetworkData();displayedLines.clear();
        if(selectedRecord!=null && !recordVisible(selectedRecord)){selectedRecord=null;selectionStatus.setText("선택한 객체가 숨겨졌습니다.");}
        LinkedHashMap<String,ArrayList<CadRecord>> fiber=new LinkedHashMap<>(), coax=new LinkedHashMap<>();
        for(CadRecord r:allRecords) {
            if(!recordVisible(r))continue;
            if(!r.hasCoordinates()) { networkData.skippedRows++; continue; }
            MapPoint point=new MapPoint(r.latitude,r.longitude);
            boundsPoints.add(point);
            if("FIBER".equals(r.category) || "COAX".equals(r.category)) {
                LinkedHashMap<String,ArrayList<CadRecord>> lines="FIBER".equals(r.category)?fiber:coax;
                if(!lines.containsKey(r.layer+"|"+r.id)) lines.put(r.layer+"|"+r.id,new ArrayList<>());
                lines.get(r.layer+"|"+r.id).add(r); continue;
            }
            visibleRecords.add(r); visiblePoints.add(point); networkRecords.put(r.stableKey(),r);
            PointItem item=new PointItem(r.category,r.stableKey(),r.title(),r.latitude,r.longitude,"");
            if("CELL".equals(r.category)) networkData.cells.add(item);
            else if("FACILITY".equals(r.category)) networkData.facilities.add(item);
            else if("EQUIPMENT".equals(r.category)) networkData.equipment.add(item);
            if(mapReady && networkRenderer==null && recordVisible(r)) map.addOnuMarker(point,r.title(),()->selectRecord(r,point));
        }
        addLines(fiber,true); addLines(coax,false);
        if(networkRenderer!=null) { networkRenderer.render(networkData); applyVisibility(); }
        status.setText("표시 중: 시설 "+networkData.facilities.size()+" · 장비/주석 "+(networkData.cells.size()+networkData.equipment.size())
            +" · 광 선형 "+networkData.fiber.size()+" · 동축 선형 "+networkData.coax.size()
            +(networkData.skippedRows>0?" · 좌표 오류 "+networkData.skippedRows+"행":""));
        android.util.Log.i("OnuNetwork","Loaded cells="+networkData.cells.size()+" facilities="+networkData.facilities.size()
            +" equipment="+networkData.equipment.size()+" fiber="+networkData.fiber.size()+" coax="+networkData.coax.size());
        drawMeasurements();
        if(currentLocation!=null) updateLocation(currentLocation);
        if(mapError!=null) status.setText(mapError);
    }

    private void addLines(LinkedHashMap<String,ArrayList<CadRecord>> grouped,boolean isFiber) {
        for(ArrayList<CadRecord> records:grouped.values()) {
            Collections.sort(records,(a,b)->Integer.compare(a.sequence,b.sequence));
            if(records.size()<2) continue;
            displayedLines.add(records);
            CadRecord first=records.get(0);
            LineItem line=new LineItem(first.id,first.name,first.subtype,first.fields.get("연결정보"),first.fields.get("길이"));
            ArrayList<MapPoint> points=new ArrayList<>();
            for(CadRecord r:records) { line.points.add(new GeoPoint(r.latitude,r.longitude)); points.add(new MapPoint(r.latitude,r.longitude)); }
            (isFiber?networkData.fiber:networkData.coax).add(line);
            if(mapReady && networkRenderer==null) map.addNetworkLine(points,isFiber);
        }
    }

    private void showAll() {
        ArrayList<MapPoint> points=new ArrayList<>();
        for(CadRecord r:allRecords) if(r.hasCoordinates() && recordVisible(r)) points.add(new MapPoint(r.latitude,r.longitude));
        if(points.isEmpty()) { Toast.makeText(this,"표시할 데이터가 없습니다. 지역 DB와 레이어 설정을 확인해주세요.",Toast.LENGTH_LONG).show(); return; }
        double south=90,north=-90,west=180,east=-180;
        for(MapPoint p:points) { south=Math.min(south,p.getLatitude()); north=Math.max(north,p.getLatitude()); west=Math.min(west,p.getLongitude()); east=Math.max(east,p.getLongitude()); }
        ArrayList<MapPoint> corners=new ArrayList<>(); corners.add(new MapPoint(south,west)); corners.add(new MapPoint(north,east));
        if(mapReady) map.showAll(corners);
    }

    private String distance(MapPoint point) {
        if (currentLocation == null) return "현재 위치 확인 전";
        float[] result = new float[1];
        Location.distanceBetween(currentLocation.getLatitude(), currentLocation.getLongitude(),
                point.getLatitude(), point.getLongitude(), result);
        return result[0] < 1000 ? Math.round(result[0]) + "m"
                : String.format(Locale.KOREA, "%.2fkm", result[0] / 1000);
    }

    private void showDetails(CadRecord r, MapPoint point) {
        if (mapReady) map.center(point, false);
        StringBuilder details = new StringBuilder();
        String pole=CadObjectInfo.pole(r),address=CadObjectInfo.address(r);
        details.append("속성\n레이어: ").append(r.layer.isEmpty()?r.category:r.layer)
                .append("\n전주정보: ").append(pole.isEmpty()?"자료 없음":pole)
                .append("\n주소: ").append(address.isEmpty()?"자료 없음":address)
                .append("\n\n상세 정보\n분류: ").append(r.category)
                .append("\nID: ").append(r.id)
                .append("\n구분/이름: ").append(r.name)
                .append("\n세부유형: ").append(r.subtype)
                .append("\n거리: ").append(distance(point))
                .append("\n경도: ").append(r.longitude)
                .append("\n위도: ").append(r.latitude)
                .append("\n출처: ").append(r.source);
        for (Map.Entry<String,String> e : r.fields.entrySet()) {
            String v = e.getValue();
            if (v != null && !v.trim().isEmpty()
                    && !"경도".equals(e.getKey()) && !"위도".equals(e.getKey())) {
                details.append("\n").append(e.getKey()).append(": ").append(v);
            }
        }

        new AlertDialog.Builder(this)
                .setTitle(r.title())
                .setMessage(details.toString())
                .setPositiveButton("확인", null)
                .show();
    }

    private void selectRecord(CadRecord record,MapPoint point) {
        if(android.os.SystemClock.uptimeMillis()<ignoreTapUntil)return;
        if(measurements.active()){addMeasurementPoint(point);return;}
        selectedRecord=record;selectedMeasurement=null;
        String pole=CadObjectInfo.pole(record);
        selectionStatus.setText("선택: "+record.title()+(pole.isEmpty()?"":" · 전주 "+pole)+" · 길게 누르기/우클릭으로 속성");
    }

    private void addMeasurementPoint(MapPoint point){
        measurements.add(point.getLatitude(),point.getLongitude());drawMeasurements();
        List<DistanceMeasurement.Point> points=measurements.current();double meters=0;
        for(int i=1;i<points.size();i++)meters+=DistanceMeasurement.distance(points.get(i-1),points.get(i));
        selectionStatus.setText("측정 중 · "+points.size()+"점 · "+formatMeters(meters));
    }

    private String formatMeters(double meters){return meters<1000?String.format(Locale.KOREA,"%.1f m",meters):String.format(Locale.KOREA,"%.3f km",meters/1000);}

    private void finishMeasurement(){
        DistanceMeasurement.Line line=measurements.finish();measureButton.setText("거리 측정");drawMeasurements();
        selectedRecord=null;selectedMeasurement=line;
        selectionStatus.setText(line==null?"측정 종료 · 두 점 이상을 선택해야 선이 생성됩니다.":"측정 완료 · "+formatMeters(line.meters)+" · 선 선택 후 메뉴에서 삭제");
    }

    private void drawMeasurements(){if(mapReady)map.showMeasurements(measurements.lines(),measurements.current());}

    private double segmentDistance(android.graphics.Point tap,android.graphics.Point a,android.graphics.Point b){
        if(tap==null||a==null||b==null)return Double.POSITIVE_INFINITY;
        double dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy;
        double t=length==0?0:Math.max(0,Math.min(1,((tap.x-a.x)*dx+(tap.y-a.y)*dy)/length));
        return Math.hypot(tap.x-a.x-t*dx,tap.y-a.y-t*dy);
    }

    private void onMapTap(MapPoint point){
        if(android.os.SystemClock.uptimeMillis()<ignoreTapUntil)return;
        if(measurements.active()){addMeasurementPoint(point);return;}
        android.graphics.Point tap=map.screenPoint(point);
        double best=dp(20);DistanceMeasurement.Line chosen=null;
        for(DistanceMeasurement.Line line:measurements.lines())for(int i=1;i<line.points.size();i++){
            DistanceMeasurement.Point a=line.points.get(i-1),b=line.points.get(i);
            double distance=segmentDistance(tap,map.screenPoint(new MapPoint(a.lat,a.lon)),map.screenPoint(new MapPoint(b.lat,b.lon)));
            if(distance<best){best=distance;chosen=line;}
        }
        if(chosen!=null){selectedMeasurement=chosen;selectedRecord=null;selectionStatus.setText("측정선 선택 · "+formatMeters(chosen.meters)+" · 길게 누르기/우클릭으로 삭제");return;}
        CadRecord candidate=null;best=dp(18);
        for(ArrayList<CadRecord> line:displayedLines)for(int i=1;i<line.size();i++){
            CadRecord a=line.get(i-1),b=line.get(i);
            double distance=segmentDistance(tap,map.screenPoint(new MapPoint(a.latitude,a.longitude)),map.screenPoint(new MapPoint(b.latitude,b.longitude)));
            if(distance<best){best=distance;candidate=line.get(0);}
        }
        if(candidate!=null)selectRecord(candidate,point);
        else {selectedRecord=null;selectedMeasurement=null;selectionStatus.setText("객체를 선택하세요.");}
    }

    private void showSelectionMenu(){
        if(measurements.active()){Toast.makeText(this,"Esc 또는 측정 종료로 먼저 측정을 완료하세요.",Toast.LENGTH_SHORT).show();return;}
        if(selectedMeasurement!=null){
            final long id=selectedMeasurement.id;
            new AlertDialog.Builder(this).setTitle("거리 측정선 · "+formatMeters(selectedMeasurement.meters))
                .setItems(new String[]{"삭제"},(dialog,which)->{
                    measurements.delete(id);selectedMeasurement=null;drawMeasurements();selectionStatus.setText("측정선을 삭제했습니다.");
                }).setNegativeButton("닫기",null).show();return;
        }
        if(selectedRecord!=null){showDetails(selectedRecord,new MapPoint(selectedRecord.latitude,selectedRecord.longitude));return;}
        Toast.makeText(this,"먼저 객체 또는 측정선을 선택하세요.",Toast.LENGTH_SHORT).show();
    }

    @Override public boolean dispatchKeyEvent(android.view.KeyEvent event){
        if(event.getKeyCode()==android.view.KeyEvent.KEYCODE_ESCAPE){
            if(event.getAction()==android.view.KeyEvent.ACTION_DOWN && measurements.active()){
                escapeConsumed=true;finishMeasurement();return true;
            }
            if(escapeConsumed){if(event.getAction()==android.view.KeyEvent.ACTION_UP)escapeConsumed=false;return true;}
        }
        return super.dispatchKeyEvent(event);
    }

    private void showNearest() {
        if (currentLocation == null) {
            centerOnFix = false;
            requestLocation();
            status.setText("현재 위치를 확인한 후 가까운 시설을 다시 눌러주세요.");
            return;
        }
        if (visibleRecords.isEmpty()) { showAll(); return; }

        ArrayList<Integer> order = new ArrayList<>();
        MapPoint current = new MapPoint(currentLocation);
        for (int i=0; i<visiblePoints.size(); i++) if(recordVisible(visibleRecords.get(i))) order.add(i);
        Collections.sort(order, (a,b) -> Double.compare(
                visiblePoints.get(a).distanceToAsDouble(current),
                visiblePoints.get(b).distanceToAsDouble(current)));

        int count = Math.min(8, order.size());
        String[] names = new String[count];
        for (int i=0; i<count; i++) {
            int idx = order.get(i);
            CadRecord r = visibleRecords.get(idx);
            names[i] = r.category + " · " + r.title() + " · " + distance(visiblePoints.get(idx));
        }

        new AlertDialog.Builder(this)
                .setTitle("가까운 시설/장비")
                .setItems(names, (dialog, which) -> {
                    int idx = order.get(which);
                    showDetails(visibleRecords.get(idx), visiblePoints.get(idx));
                })
                .setNegativeButton("닫기", null)
                .show();
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private void requestLocation() {
        if (!hasLocationPermission()) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION}, 2001);
            return;
        }
        stopLocation();
        try {
            boolean fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
            Location newest = null;
            for (String provider : new String[]{LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER}) {
                if (LocationManager.GPS_PROVIDER.equals(provider) && !fine) continue;
                if (!locationManager.getAllProviders().contains(provider) || !locationManager.isProviderEnabled(provider)) continue;
                Location cached = locationManager.getLastKnownLocation(provider);
                if (cached != null && android.os.SystemClock.elapsedRealtimeNanos()-cached.getElapsedRealtimeNanos()<120_000_000_000L && (newest == null || cached.getTime() > newest.getTime())) newest = cached;
                locationManager.requestLocationUpdates(provider, 3000, 3, listener);
                requestingLocation = true;
            }
            if (newest != null) updateLocation(newest);
        } catch (SecurityException error) {
            status.setText("위치 권한을 확인해주세요.");
        }
    }

    private void stopLocation() {
        if (locationManager != null && requestingLocation) {
            try { locationManager.removeUpdates(listener); } catch (SecurityException ignored) {}
            requestingLocation = false;
        }
    }

    private void updateLocation(Location location) {
        currentLocation = location;
        MapPoint point = new MapPoint(location);
        if (mapReady) map.setCurrentLocation(point, "정확도 약 ±" + Math.round(location.getAccuracy()) + "m");
        if (centerOnFix && mapReady) {
            map.center(point, true);
            centerOnFix = false;
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 2001) {
            if (hasLocationPermission()) requestLocation();
            else status.setText("위치 권한 없이 CAD 네트워크 지도를 표시합니다.");
        }
    }
}
