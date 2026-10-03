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
            loadMarkers();
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
        map.destroy();
        super.onDestroy();
    }

    private void loadMarkers() {
        visibleRecords.clear();
        visiblePoints.clear();
        boundsPoints.clear();
        if (mapReady) {
            map.clearOnuMarkers();
            map.clearNetworkLines();
        }

        ArrayList<CadRecord> all = db.loadAll();
        LinkedHashMap<String,Integer> counts = new LinkedHashMap<>();
        for (String c : new String[]{"CELL","FACILITY","EQUIPMENT","FIBER","COAX"}) counts.put(c,0);

        int skipped = 0;
        LinkedHashMap<String,ArrayList<CadRecord>> fiberLines = new LinkedHashMap<>();
        LinkedHashMap<String,ArrayList<CadRecord>> coaxLines = new LinkedHashMap<>();

        for (CadRecord record : all) {
            counts.put(record.category, counts.getOrDefault(record.category,0)+1);
            if (!record.hasCoordinates()) { skipped++; continue; }

            MapPoint point = new MapPoint(record.latitude, record.longitude);
            boundsPoints.add(point);

            if ("FIBER".equals(record.category)) {
                fiberLines.computeIfAbsent(record.id, k -> new ArrayList<>()).add(record);
                continue;
            }
            if ("COAX".equals(record.category)) {
                coaxLines.computeIfAbsent(record.id, k -> new ArrayList<>()).add(record);
                continue;
            }

            visibleRecords.add(record);
            visiblePoints.add(point);
            if (mapReady) map.addOnuMarker(point, record.title(), () -> showDetails(record, point));
        }

        if (mapReady) {
            addLines(fiberLines, true);
            addLines(coaxLines, false);
        }

        String text = "시설 " + counts.get("FACILITY") + " · 장비 " + counts.get("EQUIPMENT")
                + " · CELL " + counts.get("CELL")
                + " · 광선로점 " + counts.get("FIBER")
                + " · 동축선로점 " + counts.get("COAX");
        if (skipped > 0) text += " · 좌표 오류 " + skipped + "건";
        status.setText(text);

        if (currentLocation != null) updateLocation(currentLocation);
        if (mapError != null) status.setText(mapError);
        if (mapReady && !boundsPoints.isEmpty()) {
            map.getView().post(() -> { if (!destroyed) showAll(); });
        }
    }

    private void addLines(LinkedHashMap<String,ArrayList<CadRecord>> grouped, boolean fiber) {
        for (ArrayList<CadRecord> records : grouped.values()) {
            Collections.sort(records, (a,b) -> Integer.compare(a.sequence,b.sequence));
            ArrayList<MapPoint> points = new ArrayList<>();
            for (CadRecord r : records) if (r.hasCoordinates()) points.add(new MapPoint(r.latitude,r.longitude));
            if (points.size() >= 2) map.addNetworkLine(points, fiber);
        }
    }

    private void showAll() {
        if (boundsPoints.isEmpty()) {
            status.setText("표시할 시설/장비 데이터가 없습니다. 관리 화면에서 CAD Excel을 불러오세요.");
            return;
        }
        if (mapReady) map.showAll(boundsPoints);
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
        for (int i=0; i<visiblePoints.size(); i++) order.add(i);
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
                if (cached != null && (newest == null || cached.getTime() > newest.getTime())) newest = cached;
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
