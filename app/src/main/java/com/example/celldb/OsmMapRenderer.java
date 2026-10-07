package com.example.celldb;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.drawable.BitmapDrawable;
import android.view.View;
import org.osmdroid.config.Configuration;
import org.osmdroid.config.IConfigurationProvider;
import org.osmdroid.tileprovider.tilesource.TileSourceFactory;
import org.osmdroid.util.BoundingBox;
import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;
import org.osmdroid.views.overlay.Marker;
import org.osmdroid.views.overlay.Polyline;
import java.io.File;
import java.util.ArrayList;
import java.util.List;

final class OsmMapRenderer implements MapRenderer {
    private final Context context;
    private final MapView map;
    private final ArrayList<Polyline> networkLines = new ArrayList<>();
    private final ArrayList<CmbGeoSymbolOverlay> cadSymbols = new ArrayList<>();
    private Marker current;
    private final ArrayList<Polyline> measurementLines=new ArrayList<>();
    private PointClick mapClick;

    OsmMapRenderer(Context context) {
        this.context = context;
        IConfigurationProvider config = Configuration.getInstance();
        config.setUserAgentValue("CADNetworkDB/2.0 (com.example.celldb; https://github.com/ysjus2/cmb_test)");
        config.setOsmdroidBasePath(new File(context.getFilesDir(), "maps"));
        config.setOsmdroidTileCache(new File(context.getCacheDir(), "map-tiles"));
        map = new MapView(context);
        // Rotation reparents this view. Release map resources only in destroy(),
        // not during the temporary detach from its portrait/landscape container.
        map.setDestroyMode(false);
        map.setTileSource(TileSourceFactory.MAPNIK);
        map.setMultiTouchControls(true);
        map.getController().setZoom(16.0);
        map.getController().setCenter(new GeoPoint(36.5, 127.5));
        map.getOverlays().add(new org.osmdroid.views.overlay.MapEventsOverlay(new org.osmdroid.events.MapEventsReceiver(){
            public boolean singleTapConfirmedHelper(GeoPoint p){
                if(mapClick==null)return false;mapClick.accept(new MapPoint(p.getLatitude(),p.getLongitude()));return true;
            }
            public boolean longPressHelper(GeoPoint p){return false;}
        }));
    }

    public View getView() { return map; }
    public String getName() { return "OpenStreetMap"; }
    public void start(Runnable onReady, ErrorCallback onError) { onReady.run(); }

    public void clearOnuMarkers() {
        map.getOverlays().removeAll(cadSymbols);cadSymbols.clear();
        map.getOverlays().removeIf(o -> o instanceof Marker && o != current);
        map.invalidate();
    }

    public void clearNetworkLines() {
        for (Polyline line : networkLines) map.getOverlays().remove(line);
        networkLines.clear();
        map.invalidate();
    }

    private GeoPoint point(MapPoint p) { return new GeoPoint(p.getLatitude(), p.getLongitude()); }

    private BitmapDrawable icon(int color, String text, boolean current) {
        Bitmap original = MarkerIcons.create(color, text, current);
        float density = context.getResources().getDisplayMetrics().density;
        Bitmap scaled = Bitmap.createScaledBitmap(original, Math.round(original.getWidth() * density),
                Math.round(original.getHeight() * density), true);
        return new BitmapDrawable(context.getResources(), scaled);
    }

    public void addOnuMarker(MapPoint p, String title, Runnable onClick) {
        addCadSymbol(p,title,null,onClick);
    }

    public void addCadSymbol(MapPoint p, String title, String symbol, Runnable onClick) {
        Marker marker = new Marker(map);
        marker.setPosition(point(p));
        marker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM);
        Bitmap shape=CadSymbolIcon.create(symbol);
        if(shape!=null){
            float density=context.getResources().getDisplayMetrics().density;
            marker.setIcon(new BitmapDrawable(context.getResources(),Bitmap.createScaledBitmap(shape,Math.round(64*density),Math.round(64*density),true)));
            marker.setAnchor(Marker.ANCHOR_CENTER,Marker.ANCHOR_CENTER);
        }else marker.setIcon(icon(Color.rgb(220, 65, 45), "CAD", false));
        marker.setTitle(title);
        marker.setOnMarkerClickListener((selected, view) -> { onClick.run(); return true; });
        map.getOverlays().add(marker);
        map.invalidate();
    }

    boolean addGeoCadSymbol(MapPoint p,String layout,java.util.Set<String> visibleCables,Runnable onClick){
        if(layout==null)return false;
        try{
            CmbGeoSymbolOverlay overlay=new CmbGeoSymbolOverlay(p,new org.json.JSONObject(layout),visibleCables,
                    context.getResources().getDisplayMetrics().density,onClick);
            cadSymbols.add(overlay);map.getOverlays().add(overlay);return true;
        }catch(Exception error){android.util.Log.w("CmbSymbol","Invalid geographic symbol layout",error);return false;}
    }
    void bringCadSymbolsToFront(){
        map.getOverlays().removeAll(cadSymbols);map.getOverlays().addAll(cadSymbols);map.invalidate();
    }

    public void addNetworkLine(List<MapPoint> points, boolean fiber) {
        if (points == null || points.size() < 2) return;
        Polyline line = new Polyline();
        ArrayList<GeoPoint> converted = new ArrayList<>();
        for (MapPoint p : points) converted.add(point(p));
        line.setPoints(converted);
        line.getOutlinePaint().setStrokeWidth(5f * context.getResources().getDisplayMetrics().density);
        line.getOutlinePaint().setColor(fiber ? Color.rgb(30, 136, 229) : Color.rgb(245, 124, 0));
        line.setOnClickListener((selected,view,point)->{
            if(mapClick!=null)mapClick.accept(new MapPoint(point.getLatitude(),point.getLongitude()));return true;
        });
        networkLines.add(line);
        map.getOverlays().add(line);
        map.invalidate();
    }

    public void setCurrentLocation(MapPoint p, String accuracy) {
        if (current == null) {
            current = new Marker(map);
            current.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER);
            current.setIcon(icon(Color.rgb(37, 99, 235), "내 위치", true));
            current.setTitle("현재 위치");
            map.getOverlays().add(current);
        }
        current.setPosition(point(p));
        current.setSnippet(accuracy);
        map.invalidate();
    }

    public void setMapClick(PointClick click){mapClick=click;}
    public android.graphics.Point screenPoint(MapPoint p){return map.getProjection().toPixels(point(p),null);}
    public MapViewport viewport(){
        if(map.getWidth()==0||map.getHeight()==0)return null;
        BoundingBox box=map.getBoundingBox();
        return new MapViewport(box.getLonWest(),box.getLatSouth(),box.getLonEast(),box.getLatNorth());
    }
    public void showMeasurements(List<DistanceMeasurement.Line> lines,List<DistanceMeasurement.Point> current){
        map.getOverlays().removeAll(measurementLines);measurementLines.clear();
        for(DistanceMeasurement.Line line:lines)addMeasurement(line.points);
        addMeasurement(current);map.invalidate();
    }
    private void addMeasurement(List<DistanceMeasurement.Point> points){
        if(points.size()<2)return;
        Polyline line=new Polyline();ArrayList<GeoPoint> converted=new ArrayList<>();
        for(DistanceMeasurement.Point point:points)converted.add(new GeoPoint(point.lat,point.lon));
        line.setPoints(converted);line.getOutlinePaint().setColor(Color.rgb(170,40,210));
        line.getOutlinePaint().setStrokeWidth(7f*context.getResources().getDisplayMetrics().density);
        // Propagate taps to the map handler, which selects only this measurement.
        line.setOnClickListener((selected,view,point)->{
            if(mapClick!=null)mapClick.accept(new MapPoint(point.getLatitude(),point.getLongitude()));return true;
        });
        measurementLines.add(line);map.getOverlays().add(line);
    }

    public void center(MapPoint p, boolean zoomIn) {
        if (zoomIn) map.getController().setZoom(17.0);
        map.getController().animateTo(point(p));
    }

    public void showAll(List<MapPoint> points) {
        if (points.isEmpty()) return;
        if (points.size() == 1) { center(points.get(0), true); return; }
        ArrayList<GeoPoint> converted = new ArrayList<>();
        for (MapPoint p : points) converted.add(point(p));
        map.zoomToBoundingBox(BoundingBox.fromGeoPoints(converted), true,
                Math.round(60 * context.getResources().getDisplayMetrics().density), 18.0, null);
    }

    public void resume() { map.onResume(); }
    public void pause() { map.onPause(); }
    public void destroy() { map.onDetach(); }
}
