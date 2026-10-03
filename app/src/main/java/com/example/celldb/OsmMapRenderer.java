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
import java.io.File;
import java.util.ArrayList;
import java.util.List;

final class OsmMapRenderer implements MapRenderer {
    private final Context context;
    private final MapView map;
    private Marker current;

    OsmMapRenderer(Context context) {
        this.context = context;
        IConfigurationProvider config = Configuration.getInstance();
        config.setUserAgentValue("ONUPositionDB/1.2 (com.example.celldb; https://github.com/ysjus2/cmb_test)");
        config.setOsmdroidBasePath(new File(context.getFilesDir(), "maps"));
        config.setOsmdroidTileCache(new File(context.getCacheDir(), "map-tiles"));
        map = new MapView(context);
        map.setTileSource(TileSourceFactory.MAPNIK);
        map.setMultiTouchControls(true);
        map.getController().setZoom(16.0);
        map.getController().setCenter(new GeoPoint(36.5, 127.5));
    }

    public View getView() { return map; }
    public String getName() { return "OpenStreetMap"; }
    public void start(Runnable onReady, ErrorCallback onError) { onReady.run(); }
    public void clearOnuMarkers() { map.getOverlays().clear(); current = null; }
    private GeoPoint point(MapPoint p) { return new GeoPoint(p.getLatitude(), p.getLongitude()); }

    private BitmapDrawable icon(int color, String text, boolean current) {
        Bitmap original = MarkerIcons.create(color, text, current);
        float density = context.getResources().getDisplayMetrics().density;
        Bitmap scaled = Bitmap.createScaledBitmap(original, Math.round(original.getWidth() * density),
                Math.round(original.getHeight() * density), true);
        return new BitmapDrawable(context.getResources(), scaled);
    }

    public void addOnuMarker(MapPoint p, String title, Runnable onClick) {
        Marker marker = new Marker(map);
        marker.setPosition(point(p));
        marker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM);
        marker.setIcon(icon(Color.rgb(220, 65, 45), "ONU", false));
        marker.setTitle(title);
        marker.setOnMarkerClickListener((selected, view) -> { onClick.run(); return true; });
        map.getOverlays().add(marker);
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
        current.setPosition(point(p)); current.setSnippet(accuracy); map.invalidate();
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
