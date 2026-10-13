package com.example.celldb;

import android.view.View;
import java.util.List;

/** The activity owns CAD data and GPS; providers own rendering and map gestures. */
interface MapRenderer {
    interface ErrorCallback { void accept(String message); }
    interface PointClick { void accept(MapPoint point); }
    View getView();
    String getName();
    void start(Runnable onReady, ErrorCallback onError);
    void clearOnuMarkers();
    void clearNetworkLines();
    void addOnuMarker(MapPoint point, String title, Runnable onClick);
    void addCadSymbol(MapPoint point, String title, String symbol, Runnable onClick);
    void addNetworkLine(List<MapPoint> points, boolean fiber);
    default void addNetworkLine(List<MapPoint> points, boolean fiber, boolean selected) {
        addNetworkLine(points, fiber);
    }
    void setMapClick(PointClick click);
    void showMeasurements(List<DistanceMeasurement.Line> lines,List<DistanceMeasurement.Point> current);
    android.graphics.Point screenPoint(MapPoint point);
    MapViewport viewport();
    default int windowsMapLevel(){
        MapViewport v=viewport();
        if(v==null)return 6;
        double meters=(v.east-v.west)*111320*Math.cos(Math.toRadians((v.north+v.south)/2));
        if(meters<=450)return 3;
        if(meters<=900)return 4;
        if(meters<=1800)return 5;
        return 6;
    }
    void setCurrentLocation(MapPoint point, String accuracy);
    default boolean supportsHybridMap(){ return false; }
    default void setHybridMap(boolean hybrid) { }
    void center(MapPoint point, boolean zoomIn);
    void showAll(List<MapPoint> points);
    void resume();
    void pause();
    void destroy();
}
