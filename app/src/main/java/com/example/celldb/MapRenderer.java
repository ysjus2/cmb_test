package com.example.celldb;

import android.view.View;
import java.util.List;

/** The activity owns data and GPS; providers own only rendering and map gestures. */
interface MapRenderer {
    interface ErrorCallback { void accept(String message); }
    View getView();
    String getName();
    void start(Runnable onReady, ErrorCallback onError);
    void clearOnuMarkers();
    void addOnuMarker(MapPoint point, String title, Runnable onClick);
    void setCurrentLocation(MapPoint point, String accuracy);
    void center(MapPoint point, boolean zoomIn);
    void showAll(List<MapPoint> points);
    void resume();
    void pause();
    void destroy();
}
