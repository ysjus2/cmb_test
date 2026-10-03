package com.example.celldb;

import android.location.Location;

/** Coordinates and distance calculation independent of the map provider. */
final class MapPoint {
    private final double latitude;
    private final double longitude;

    MapPoint(double latitude, double longitude) {
        this.latitude = latitude;
        this.longitude = longitude;
    }

    MapPoint(Location location) { this(location.getLatitude(), location.getLongitude()); }
    double getLatitude() { return latitude; }
    double getLongitude() { return longitude; }

    double distanceToAsDouble(MapPoint other) {
        float[] result = new float[1];
        Location.distanceBetween(latitude, longitude, other.latitude, other.longitude, result);
        return result[0];
    }
}
