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
import com.kakao.vectormap.route.RouteLineLayer;
import com.kakao.vectormap.route.RouteLineOptions;
import com.kakao.vectormap.route.RouteLineSegment;
import com.kakao.vectormap.route.RouteLineStyle;
import com.kakao.vectormap.route.RouteLineStyles;
import com.kakao.vectormap.route.RouteLineStylesSet;
import java.util.ArrayList;
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
    private RouteLineLayer fiberLayer;
    private RouteLineLayer coaxLayer;
    private RouteLineStylesSet fiberStyles;
    private RouteLineStylesSet coaxStyles;
    private boolean destroyed;
    private int nextId;
    private int nextLineId;
    private PointClick mapClick;
    private RouteLineLayer measurementLayer;
    private RouteLineStylesSet measurementStyles;

    KakaoMapRenderer(Context context, String key) {
        KakaoMapSdk.init(context.getApplicationContext(), key);
        view = new MapView(context);
    }

    public View getView() { return view; }
    KakaoMap getKakaoMap() { return map; }
    public String getName() { return "카카오맵"; }
    private LatLng point(MapPoint p) { return LatLng.from(p.getLatitude(), p.getLongitude()); }

    public void start(Runnable onReady, ErrorCallback onError) {
        view.start(new MapLifeCycleCallback() {
            @Override public void onMapDestroy() { map = null; }
            @Override public void onMapError(Exception error) {
                if (!destroyed) view.post(() -> {
                    if (!destroyed) onError.accept("카카오 지도를 불러오지 못했습니다. 인터넷 연결 또는 앱 인증 설정을 확인해주세요.");
                });
                android.util.Log.e("CadMap", "Kakao map initialization failed", error);
            }
        }, new KakaoMapReadyCallback() {
            @Override public void onMapReady(KakaoMap readyMap) {
                view.post(() -> {
                    if (destroyed) return;
                    map = readyMap;
                    onuLayer = map.getLabelManager().addLayer(LabelLayerOptions.from("cad-points")
                            .setZOrder(5000).setCompetitionType(CompetitionType.None));
                    locationLayer = map.getLabelManager().addLayer(LabelLayerOptions.from("location")
                            .setZOrder(5002).setCompetitionType(CompetitionType.None));
                    onuStyle = map.getLabelManager().addLabelStyles(LabelStyles.from("cad-icon",
                            LabelStyle.from(MarkerIcons.create(Color.rgb(220, 65, 45), "CAD", false))
                                    .setAnchorPoint(0.5f, 1.0f).setTextStyles(13, Color.BLACK)));
                    locationStyle = map.getLabelManager().addLabelStyles(LabelStyles.from("location-icon",
                            LabelStyle.from(MarkerIcons.create(Color.rgb(37, 99, 235), "내 위치", true))
                                    .setAnchorPoint(0.5f, 0.5f)));

                    fiberLayer = map.getRouteLineManager().addLayer("fiber-lines", 3000);
                    coaxLayer = map.getRouteLineManager().addLayer("coax-lines", 2999);
                    fiberStyles = map.getRouteLineManager().addStylesSet(RouteLineStylesSet.from(
                            RouteLineStyles.from(RouteLineStyle.from(5f, Color.rgb(30, 136, 229)))));
                    coaxStyles = map.getRouteLineManager().addStylesSet(RouteLineStylesSet.from(
                            RouteLineStyles.from(RouteLineStyle.from(5f, Color.rgb(245, 124, 0)))));
                    measurementLayer=map.getRouteLineManager().addLayer("user-measurements",6000);
                    measurementStyles=map.getRouteLineManager().addStylesSet(RouteLineStylesSet.from(
                            RouteLineStyles.from(RouteLineStyle.from(7f,Color.rgb(170,40,210)))));
                    map.setOnMapClickListener((clickedMap,position,screenPoint,poi)->{
                        if(mapClick!=null)view.post(()->mapClick.accept(new MapPoint(position.latitude,position.longitude)));
                    });

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
        clickActions.clear();
        nextId = 0;
        if (onuLayer != null) onuLayer.removeAll();
    }

    public void clearNetworkLines() {
        nextLineId = 0;
        if (fiberLayer != null) fiberLayer.removeAll();
        if (coaxLayer != null) coaxLayer.removeAll();
    }

    public void addOnuMarker(MapPoint p, String title, Runnable onClick) {
        if (map == null) return;
        String id = "cad-" + nextId++;
        onuLayer.addLabel(LabelOptions.from(id, point(p)).setStyles(onuStyle)
                .setTexts(new LabelTextBuilder().setTexts(title)).setClickable(true));
        clickActions.put(id, onClick);
    }

    public void addNetworkLine(List<MapPoint> points, boolean fiber) {
        if (map == null || points == null || points.size() < 2) return;
        ArrayList<LatLng> converted = new ArrayList<>();
        for (MapPoint p : points) converted.add(point(p));
        RouteLineStylesSet styles = fiber ? fiberStyles : coaxStyles;
        RouteLineLayer layer = fiber ? fiberLayer : coaxLayer;
        RouteLineSegment segment = RouteLineSegment.from(converted, styles.getStyles(0));
        RouteLineOptions options = RouteLineOptions.from((fiber ? "fiber-" : "coax-") + nextLineId++, segment)
                .setStylesSet(styles);
        layer.addRouteLine(options);
    }

    public void setCurrentLocation(MapPoint p, String accuracy) {
        if (map == null) return;
        if (current == null) current = locationLayer.addLabel(LabelOptions.from("my-location", point(p))
                .setStyles(locationStyle).setClickable(false));
        else current.moveTo(point(p));
    }

    public void setMapClick(PointClick click){mapClick=click;}
    public android.graphics.Point screenPoint(MapPoint p){return map==null?null:map.toScreenPoint(point(p));}
    public void showMeasurements(List<DistanceMeasurement.Line> lines,List<DistanceMeasurement.Point> current){
        if(measurementLayer==null)return;
        measurementLayer.removeAll();
        for(DistanceMeasurement.Line line:lines)addMeasurement("measurement-"+line.id,line.points);
        addMeasurement("measurement-current",current);
    }
    private void addMeasurement(String id,List<DistanceMeasurement.Point> points){
        if(points.size()<2)return;
        ArrayList<LatLng> converted=new ArrayList<>();
        for(DistanceMeasurement.Point point:points)converted.add(LatLng.from(point.lat,point.lon));
        measurementLayer.addRouteLine(RouteLineOptions.from(id,RouteLineSegment.from(converted,measurementStyles.getStyles(0)))
                .setStylesSet(measurementStyles));
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
    public void destroy() {
        destroyed = true;
        clickActions.clear();
        view.finish();
        map = null;
    }
}
