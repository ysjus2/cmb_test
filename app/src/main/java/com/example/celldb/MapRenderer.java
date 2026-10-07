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
    void setMapClick(PointClick click);
    void showMeasurements(List<DistanceMeasurement.Line> lines,List<DistanceMeasurement.Point> current);
    android.graphics.Point screenPoint(MapPoint point);
    MapViewport viewport();
    void setCurrentLocation(MapPoint point, String accuracy);
    void center(MapPoint point, boolean zoomIn);
    void showAll(List<MapPoint> points);
    void resume();
    void pause();
    void destroy();
}
