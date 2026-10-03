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
    private final boolean[] layers = {true,true,true,true,true};
    private final String[] categories = {"CELL","FACILITY","EQUIPMENT","FIBER","COAX"};
    private final Map<String,CadRecord> networkRecords = new HashMap<>();
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private Button importButton;
    private TextView regionStatus;

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
        String[] names = {"셀","시설","장비","광","동축"};
        for (int i=0;i<names.length;i++) {
            final int index=i;
            CheckBox check = new CheckBox(this);
            check.setText(names[i]); check.setTextSize(12);
            layers[i]=getSharedPreferences("network_prefs",MODE_PRIVATE).getBoolean("layer_"+i,true);
            check.setChecked(layers[i]);
            check.setOnCheckedChangeListener((button,checked) -> {
                layers[index]=checked;
                getSharedPreferences("network_prefs",MODE_PRIVATE).edit().putBoolean("layer_"+index,checked).apply();
                if (networkRenderer != null) applyVisibility(); else loadMarkers();
            });
            toggles.addView(check);
        }
        scroll.addView(toggles); root.addView(scroll);

        map = BuildConfig.KAKAO_NATIVE_APP_KEY.isEmpty() ? new OsmMapRenderer(this)
                : new KakaoMapRenderer(this, BuildConfig.KAKAO_NATIVE_APP_KEY);
        root.addView(map.getView(), new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        TextView attribution = new TextView(this);
        attribution.setText((map instanceof OsmMapRenderer ? "© OpenStreetMap contributors" : "카카오맵")
                + " · CAD 좌표 변환 데이터");
        attribution.setTextSize(11);
        attribution.setGravity(Gravity.CENTER);
        attribution.setPadding(dp(4), dp(6), dp(4), dp(6));
        root.addView(attribution);

        Button manage = new Button(this);
        manage.setText("CAD Excel / 시설·장비·선로 등록·수정");
        manage.setOnClickListener(v -> startActivity(new Intent(this, MainActivity.class)));
        root.addView(manage);

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
                        if (!destroyed && record!=null) showDetails(record,new MapPoint(p.lat,p.lon));
                    }));
            }
            loadMarkers();
            if (!boundsPoints.isEmpty()) map.getView().post(() -> { if (!destroyed) showAll(); });
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
                    loadMarkers(); showAll();
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

    private boolean categoryVisible(String category) {
        for(int i=0;i<categories.length;i++) if(categories[i].equals(category)) return layers[i];
        return false;
    }

    private void applyVisibility() {
        if(networkRenderer==null) return;
        networkRenderer.setCellVisible(layers[0]); networkRenderer.setFacilityVisible(layers[1]);
        networkRenderer.setEquipmentVisible(layers[2]); networkRenderer.setFiberVisible(layers[3]);
        networkRenderer.setCoaxVisible(layers[4]);
    }

    private void loadMarkers() {
        visibleRecords.clear(); visiblePoints.clear(); boundsPoints.clear(); networkRecords.clear();
        if(mapReady) { map.clearOnuMarkers(); map.clearNetworkLines(); }
        networkData=new NetworkData();
        LinkedHashMap<String,ArrayList<CadRecord>> fiber=new LinkedHashMap<>(), coax=new LinkedHashMap<>();
        for(CadRecord r:db.loadAll()) {
            if(!r.hasCoordinates()) { networkData.skippedRows++; continue; }
            MapPoint point=new MapPoint(r.latitude,r.longitude);
            if(categoryVisible(r.category)) boundsPoints.add(point);
            if("FIBER".equals(r.category) || "COAX".equals(r.category)) {
                LinkedHashMap<String,ArrayList<CadRecord>> lines="FIBER".equals(r.category)?fiber:coax;
                if(!lines.containsKey(r.id)) lines.put(r.id,new ArrayList<>());
                lines.get(r.id).add(r); continue;
            }
            visibleRecords.add(r); visiblePoints.add(point); networkRecords.put(r.stableKey(),r);
            PointItem item=new PointItem(r.category,r.stableKey(),r.title(),r.latitude,r.longitude,"");
            if("CELL".equals(r.category)) networkData.cells.add(item);
            else if("FACILITY".equals(r.category)) networkData.facilities.add(item);
            else if("EQUIPMENT".equals(r.category)) networkData.equipment.add(item);
            if(mapReady && networkRenderer==null && categoryVisible(r.category)) map.addOnuMarker(point,r.title(),()->showDetails(r,point));
        }
        addLines(fiber,true); addLines(coax,false);
        if(networkRenderer!=null) { networkRenderer.render(networkData); applyVisibility(); }
        status.setText("셀 "+networkData.cells.size()+" · 시설 "+networkData.facilities.size()+" · 장비 "+networkData.equipment.size()
            +" · 광 "+networkData.fiber.size()+" · 동축 "+networkData.coax.size()
            +(networkData.skippedRows>0?" · 좌표 오류 "+networkData.skippedRows+"행":""));
        android.util.Log.i("OnuNetwork","Loaded cells="+networkData.cells.size()+" facilities="+networkData.facilities.size()
            +" equipment="+networkData.equipment.size()+" fiber="+networkData.fiber.size()+" coax="+networkData.coax.size());
        if(currentLocation!=null) updateLocation(currentLocation);
        if(mapError!=null) status.setText(mapError);
    }

    private void addLines(LinkedHashMap<String,ArrayList<CadRecord>> grouped,boolean isFiber) {
        for(ArrayList<CadRecord> records:grouped.values()) {
            Collections.sort(records,(a,b)->Integer.compare(a.sequence,b.sequence));
            if(records.size()<2) continue;
            CadRecord first=records.get(0);
            LineItem line=new LineItem(first.id,first.name,first.subtype,first.fields.get("연결정보"),first.fields.get("길이"));
            ArrayList<MapPoint> points=new ArrayList<>();
            for(CadRecord r:records) { line.points.add(new GeoPoint(r.latitude,r.longitude)); points.add(new MapPoint(r.latitude,r.longitude)); }
            (isFiber?networkData.fiber:networkData.coax).add(line);
            if(mapReady && networkRenderer==null && layers[isFiber?3:4]) map.addNetworkLine(points,isFiber);
        }
    }

    private void showAll() {
        ArrayList<MapPoint> points=new ArrayList<>();
        for(CadRecord r:db.loadAll()) if(r.hasCoordinates() && categoryVisible(r.category)) points.add(new MapPoint(r.latitude,r.longitude));
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
        details.append("분류: ").append(r.category)
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
                .setNeutralButton("수정", (d,w) -> startActivity(new Intent(this, MainActivity.class)))
                .show();
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
        for (int i=0; i<visiblePoints.size(); i++) if(categoryVisible(visibleRecords.get(i).category)) order.add(i);
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
