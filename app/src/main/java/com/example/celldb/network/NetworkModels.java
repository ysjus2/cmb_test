package com.example.celldb.network;

import java.util.ArrayList;
import java.util.List;

public final class NetworkModels {
    private NetworkModels() {}

    public static final class GeoPoint {
        public final double lat;
        public final double lon;
        public GeoPoint(double lat, double lon) { this.lat = lat; this.lon = lon; }
    }

    public static final class PointItem {
        public final String category;
        public final String id;
        public final String name;
        public final double lat;
        public final double lon;
        public final String detail;

        public PointItem(String category, String id, String name,
                         double lat, double lon, String detail) {
            this.category = category;
            this.id = id;
            this.name = name;
            this.lat = lat;
            this.lon = lon;
            this.detail = detail;
        }
    }

    public static final class LineItem {
        public final String id;
        public final String cableName;
        public final String cableId;
        public final String connection;
        public final String length;
        public final List<GeoPoint> points = new ArrayList<>();

        public LineItem(String id, String cableName, String cableId,
                        String connection, String length) {
            this.id = id;
            this.cableName = cableName;
            this.cableId = cableId;
            this.connection = connection;
            this.length = length;
        }
    }

    public static final class NetworkData {
        public int skippedRows;
        public final List<PointItem> cells = new ArrayList<>();
        public final List<PointItem> facilities = new ArrayList<>();
        public final List<PointItem> equipment = new ArrayList<>();
        public final List<LineItem> fiber = new ArrayList<>();
        public final List<LineItem> coax = new ArrayList<>();

        public int totalPointCount() {
            return cells.size() + facilities.size() + equipment.size();
        }
    }
}
