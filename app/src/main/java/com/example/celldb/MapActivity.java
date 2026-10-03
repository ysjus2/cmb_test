package com.example.celldb;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.drawable.BitmapDrawable;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.osmdroid.config.Configuration;
import org.osmdroid.config.IConfigurationProvider;
import org.osmdroid.tileprovider.tilesource.TileSourceFactory;
import org.osmdroid.util.BoundingBox;
import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;
import org.osmdroid.views.overlay.Marker;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Locale;

public class MapActivity extends Activity {
    private final ArrayList<MainActivity.CellRecord> records = new ArrayList<>();
    private final ArrayList<GeoPoint> points = new ArrayList<>();
    private MapView map;
    private TextView status;
    private LocationManager locationManager;
    private Location currentLocation;
    private Marker currentMarker;
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
        IConfigurationProvider config = Configuration.getInstance();
        config.setUserAgentValue("ONUPositionDB/1.1 (com.example.celldb; https://github.com/ysjus2/cmb_test)");
        config.setOsmdroidBasePath(new File(getFilesDir(), "maps"));
        config.setOsmdroidTileCache(new File(getCacheDir(), "map-tiles"));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        // Android 15 edge-to-edge: keep buttons clear of system bars.
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        TextView title = new TextView(this);
        title.setText("ONU 위치 지도");
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
        addButton(actions, "전체 ONU", this::showAll);
        addButton(actions, "가까운 ONU", this::showNearest);
        root.addView(actions);
        map = new MapView(this);
        map.setTileSource(TileSourceFactory.MAPNIK);
        map.setMultiTouchControls(true);
        map.getController().setZoom(16.0);
        map.getController().setCenter(new GeoPoint(36.5, 127.5));
        root.addView(map, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        TextView attribution = new TextView(this);
        attribution.setText("© OpenStreetMap contributors · 지도 배경은 인터넷 연결 필요");
        attribution.setTextSize(11);
        attribution.setGravity(Gravity.CENTER);
        attribution.setPadding(dp(4), dp(6), dp(4), dp(6));
        attribution.setOnClickListener(v -> startActivity(new Intent(Intent.ACTION_VIEW,
                android.net.Uri.parse("https://www.openstreetmap.org/copyright"))));
        root.addView(attribution);
        Button manage = new Button(this);
        manage.setText("ONU 정보 등록 / 수정 / CSV 관리");
        manage.setOnClickListener(v -> startActivity(new Intent(this, MainActivity.class)));
        root.addView(manage);
        setContentView(root);
        locationManager = (LocationManager) getSystemService(LOCATION_SERVICE);
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
        map.onResume();
        loadMarkers();
        requestLocation();
    }

    @Override protected void onPause() {
        stopLocation();
        map.onPause();
        super.onPause();
    }

    @Override protected void onDestroy() { map.onDetach(); super.onDestroy(); }

    private void loadMarkers() {
        records.clear();
        points.clear();
        map.getOverlays().clear();
        currentMarker = null;
        int skipped = 0;
        try {
            JSONArray data = new JSONArray(getSharedPreferences("cell_db_prefs", MODE_PRIVATE)
                    .getString("db_json", "[]"));
            for (int i = 0; i < data.length(); i++) {
                MainActivity.CellRecord record = MainActivity.CellRecord.fromJson(data.getJSONObject(i));
                try {
                    double lat = Double.parseDouble(record.latitude);
                    double lon = Double.parseDouble(record.longitude);
                    if (!validCoordinates(lat, lon)) { skipped++; continue; }
                    GeoPoint point = new GeoPoint(lat, lon);
                    records.add(record);
                    points.add(point);
                    Marker marker = new Marker(map);
                    marker.setPosition(point);
                    marker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM);
                    marker.setIcon(markerIcon(Color.rgb(220, 65, 45), "ONU"));
                    marker.setTitle(record.cellName + " / " + record.cellNumber);
                    marker.setOnMarkerClickListener((selected, view) -> { showDetails(record, point); return true; });
                    map.getOverlays().add(marker);
                } catch (NumberFormatException invalid) { skipped++; }
            }
        } catch (Exception error) {
            status.setText("저장 정보를 읽지 못했습니다. CSV 관리에서 데이터를 확인하세요.");
            return;
        }
        status.setText("ONU " + records.size() + "건" + (skipped > 0 ? " · 좌표 오류 " + skipped + "건 제외" : "")
                + " · 빨강: ONU / 파랑: 내 위치");
        if (currentLocation != null) updateLocation(currentLocation);
        if (!points.isEmpty()) map.post(this::showAll);
        map.invalidate();
    }

    static boolean validCoordinates(double lat, double lon) {
        return !Double.isNaN(lat) && !Double.isInfinite(lat) && !Double.isNaN(lon) && !Double.isInfinite(lon)
                && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    }

    private BitmapDrawable markerIcon(int color, String label) {
        Bitmap bitmap = Bitmap.createBitmap(dp(48), dp(56), Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(color);
        canvas.drawCircle(dp(24), dp(24), dp(22), paint);
        android.graphics.Path tail = new android.graphics.Path();
        tail.moveTo(dp(14), dp(39)); tail.lineTo(dp(24), dp(55)); tail.lineTo(dp(34), dp(39)); tail.close();
        canvas.drawPath(tail, paint);
        paint.setColor(Color.WHITE);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(dp(12));
        paint.setFakeBoldText(true);
        canvas.drawText(label, dp(24), dp(28), paint);
        return new BitmapDrawable(getResources(), bitmap);
    }

    private void showAll() {
        if (points.isEmpty()) { status.setText("저장된 ONU가 없습니다. 아래 버튼에서 정보를 등록하세요."); return; }
        if (points.size() == 1) {
            map.getController().setZoom(17.0);
            map.getController().setCenter(points.get(0));
        } else {
            map.zoomToBoundingBox(BoundingBox.fromGeoPoints(points), true, dp(60), 18.0, null);
        }
    }

    private String distance(GeoPoint point) {
        if (currentLocation == null) return "현재 위치 확인 전";
        float[] result = new float[1];
        Location.distanceBetween(currentLocation.getLatitude(), currentLocation.getLongitude(),
                point.getLatitude(), point.getLongitude(), result);
        return result[0] < 1000 ? Math.round(result[0]) + "m" : String.format(Locale.KOREA, "%.2fkm", result[0] / 1000);
    }

    private void showDetails(MainActivity.CellRecord r, GeoPoint point) {
        map.getController().animateTo(point);
        new AlertDialog.Builder(this).setTitle(r.cellName + " / " + r.cellNumber)
                .setMessage("거리: " + distance(point) + " (직선거리)\n상위국사: " + r.upperOffice
                        + "\n상향포트: " + r.upPort + "\n하향포트: " + r.downPort
                        + "\n주소: " + r.address + "\n전주번호: " + r.poleNumber
                        + "\n경도: " + r.longitude + "\n위도: " + r.latitude
                        + "\n셀구분: " + r.cellType + "\n비고: " + r.note)
                .setPositiveButton("확인", null).show();
    }

    private void showNearest() {
        if (currentLocation == null) { centerOnFix = false; requestLocation(); status.setText("현재 위치를 확인한 후 가까운 ONU를 다시 눌러주세요."); return; }
        if (records.isEmpty()) { showAll(); return; }
        ArrayList<Integer> order = new ArrayList<>();
        for (int i = 0; i < points.size(); i++) order.add(i);
        Collections.sort(order, (a, b) -> Double.compare(points.get(a).distanceToAsDouble(
                new GeoPoint(currentLocation)), points.get(b).distanceToAsDouble(new GeoPoint(currentLocation))));
        int count = Math.min(5, order.size());
        String[] names = new String[count];
        for (int i = 0; i < count; i++) {
            int index = order.get(i);
            names[i] = records.get(index).cellName + " / " + records.get(index).cellNumber + " · " + distance(points.get(index));
        }
        new AlertDialog.Builder(this).setTitle("가까운 ONU · 직선거리")
                .setItems(names, (dialog, which) -> {
                    int index = order.get(which);
                    showDetails(records.get(index), points.get(index));
                }).setNegativeButton("닫기", null).show();
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
                if (cached != null && android.os.SystemClock.elapsedRealtimeNanos() - cached.getElapsedRealtimeNanos()
                        < 120_000_000_000L && (newest == null || cached.getTime() > newest.getTime())) newest = cached;
                locationManager.requestLocationUpdates(provider, 3000, 3, listener);
                requestingLocation = true;
            }
            if (newest != null) updateLocation(newest);
            if (!requestingLocation) status.setText("ONU " + records.size() + "건 · 휴대폰 위치 기능을 켜주세요.");
        } catch (SecurityException error) { status.setText("위치 권한을 확인해주세요."); }
    }

    private void stopLocation() {
        if (locationManager != null && requestingLocation) {
            locationManager.removeUpdates(listener);
            requestingLocation = false;
        }
    }

    private void updateLocation(Location location) {
        currentLocation = location;
        GeoPoint point = new GeoPoint(location);
        if (currentMarker == null) {
            currentMarker = new Marker(map);
            currentMarker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER);
            currentMarker.setIcon(markerIcon(Color.rgb(37, 99, 235), "내 위치"));
            currentMarker.setTitle("현재 위치");
            map.getOverlays().add(currentMarker);
        }
        currentMarker.setPosition(point);
        currentMarker.setSnippet("정확도 약 ±" + Math.round(location.getAccuracy()) + "m");
        status.setText("ONU " + records.size() + "건 · 내 위치 정확도 ±" + Math.round(location.getAccuracy()) + "m");
        if (centerOnFix) { map.getController().animateTo(point); centerOnFix = false; }
        map.invalidate();
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 2001) {
            if (hasLocationPermission()) requestLocation();
            else status.setText("위치 권한 없이 저장된 ONU 지도를 표시합니다.");
        }
    }
}
