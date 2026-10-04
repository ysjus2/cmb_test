package com.example.celldb;

import java.util.*;

/** Only user-created measurements can be removed; CAD entities are not stored here. */
final class DistanceMeasurement {
    static final class Point {
        final double lat,lon;
        Point(double lat,double lon){this.lat=lat;this.lon=lon;}
    }
    static final class Line {
        final long id;
        final List<Point> points;
        final double meters;
        Line(long id,List<Point> points){
            this.id=id;this.points=Collections.unmodifiableList(new ArrayList<>(points));
            double distance=0;
            for(int i=1;i<points.size();i++)distance+=distance(points.get(i-1),points.get(i));
            meters=distance;
        }
    }
    private long nextId=1;
    private final List<Point> current=new ArrayList<>();
    private final List<Line> completed=new ArrayList<>();
    private boolean active;
    void start(){current.clear();active=true;}
    boolean active(){return active;}
    void add(double lat,double lon){
        if(!active)return;
        if(Double.isNaN(lat)||Double.isInfinite(lat)||Double.isNaN(lon)||Double.isInfinite(lon)||Math.abs(lat)>90||Math.abs(lon)>180)return;
        current.add(new Point(lat,lon));
    }
    List<Point> current(){return Collections.unmodifiableList(new ArrayList<>(current));}
    List<Line> lines(){return Collections.unmodifiableList(new ArrayList<>(completed));}
    Line finish(){
        if(!active)return null;
        active=false;
        if(current.size()<2){current.clear();return null;}
        Line line=new Line(nextId++,current);completed.add(line);current.clear();return line;
    }
    boolean delete(long id){
        for(int i=0;i<completed.size();i++)if(completed.get(i).id==id){completed.remove(i);return true;}
        return false;
    }
    static double distance(Point a,Point b){
        double lat=Math.toRadians(b.lat-a.lat),lon=Math.toRadians(b.lon-a.lon);
        double h=Math.sin(lat/2)*Math.sin(lat/2)+Math.cos(Math.toRadians(a.lat))*Math.cos(Math.toRadians(b.lat))*Math.sin(lon/2)*Math.sin(lon/2);
        return 6371008.8*2*Math.asin(Math.sqrt(Math.max(0,Math.min(1,h))));
    }
}
