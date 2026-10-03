package com.example.celldb;

import android.content.Context;
import android.graphics.Color;
import android.view.View;
import com.kakao.vectormap.KakaoMap;
import com.kakao.vectormap.KakaoMapReadyCallback;
import com.kakao.vectormap.KakaoMapSdk;
import com.kakao.vectormap.LatLng;
import com.kakao.vectormap.MapLifeCycleCallback;
import com.kakao.vectormap.MapView;
import com.kakao.vectormap.camera.CameraUpdateFactory;
import com.kakao.vectormap.label.CompetitionType;
import com.kakao.vectormap.label.Label;
import com.kakao.vectormap.label.LabelLayer;
import com.kakao.vectormap.label.LabelLayerOptions;
import com.kakao.vectormap.label.LabelOptions;
import com.kakao.vectormap.label.LabelStyle;
import com.kakao.vectormap.label.LabelStyles;
import com.kakao.vectormap.label.LabelTextBuilder;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

final class KakaoMapRenderer implements MapRenderer {
    private final MapView view;
    private final Map<String, Runnable> clickActions = new HashMap<>();
    private KakaoMap map;
    private LabelLayer onuLayer;
    private LabelLayer locationLayer;
    private LabelStyles onuStyle;
    private LabelStyles locationStyle;
    private Label current;
    private boolean destroyed;
    private int nextId;

    KakaoMapRenderer(Context context, String key) {
        KakaoMapSdk.init(context.getApplicationContext(), key);
        view = new MapView(context);
    }

    public View getView() { return view; }
    public String getName() { return "카카오맵"; }
    private LatLng point(MapPoint p) { return LatLng.from(p.getLatitude(), p.getLongitude()); }

    public void start(Runnable onReady, ErrorCallback onError) {
        view.start(new MapLifeCycleCallback() {
            @Override public void onMapDestroy() { map = null; }
            @Override public void onMapError(Exception error) {
                if (!destroyed) view.post(() -> {
                    if (!destroyed) onError.accept("카카오 지도를 불러오지 못했습니다. 인터넷 연결 또는 앱 인증 설정을 확인해주세요.");
                });
                android.util.Log.e("OnuMap", "Kakao map initialization failed", error);
            }
        }, new KakaoMapReadyCallback() {
            @Override public void onMapReady(KakaoMap readyMap) {
                view.post(() -> {
                    if (destroyed) return;
                    map = readyMap;
                    onuLayer = map.getLabelManager().addLayer(LabelLayerOptions.from("onu")
                            .setZOrder(5000).setCompetitionType(CompetitionType.None));
                    locationLayer = map.getLabelManager().addLayer(LabelLayerOptions.from("location")
                            .setZOrder(5001).setCompetitionType(CompetitionType.None));
                    onuStyle = map.getLabelManager().addLabelStyles(LabelStyles.from("onu-icon",
                            LabelStyle.from(MarkerIcons.create(Color.rgb(220, 65, 45), "ONU", false))
                                    .setAnchorPoint(0.5f, 1.0f).setTextStyles(13, Color.BLACK)));
                    locationStyle = map.getLabelManager().addLabelStyles(LabelStyles.from("location-icon",
                            LabelStyle.from(MarkerIcons.create(Color.rgb(37, 99, 235), "내 위치", true))
                                    .setAnchorPoint(0.5f, 0.5f)));
                    map.setOnLabelClickListener((clickedMap, layer, label) -> {
                        Runnable action = clickActions.get(label.getLabelId());
                        if (action != null) view.post(action);
                        return action != null;
                    });
                    onReady.run();
                });
            }
            @Override public LatLng getPosition() { return LatLng.from(36.5, 127.5); }
            @Override public int getZoomLevel() { return 16; }
        });
    }

    public void clearOnuMarkers() {
        clickActions.clear(); nextId = 0;
        if (onuLayer != null) onuLayer.removeAll();
    }

    public void addOnuMarker(MapPoint p, String title, Runnable onClick) {
        if (map == null) return;
        String id = "onu-" + nextId++;
        onuLayer.addLabel(LabelOptions.from(id, point(p)).setStyles(onuStyle)
                .setTexts(new LabelTextBuilder().setTexts(title)).setClickable(true));
        clickActions.put(id, onClick);
    }

    public void setCurrentLocation(MapPoint p, String accuracy) {
        if (map == null) return;
        if (current == null) current = locationLayer.addLabel(LabelOptions.from("my-location", point(p))
                .setStyles(locationStyle).setClickable(false));
        else current.moveTo(point(p));
    }

    public void center(MapPoint p, boolean zoomIn) {
        if (map == null) return;
        map.moveCamera(zoomIn ? CameraUpdateFactory.newCenterPosition(point(p), 17)
                : CameraUpdateFactory.newCenterPosition(point(p)));
    }

    public void showAll(List<MapPoint> points) {
        if (map == null || points.isEmpty()) return;
        if (points.size() == 1) { center(points.get(0), true); return; }
        LatLng[] converted = new LatLng[points.size()];
        for (int i = 0; i < points.size(); i++) converted[i] = point(points.get(i));
        int padding = Math.round(60 * view.getResources().getDisplayMetrics().density);
        map.moveCamera(CameraUpdateFactory.fitMapPoints(converted, padding, 18));
    }
    public void resume() { view.resume(); }
    public void pause() { view.pause(); }
    public void destroy() { destroyed = true; clickActions.clear(); view.finish(); map = null; }
}
