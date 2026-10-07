package com.example.celldb;

final class MapViewport {
    final double west,south,east,north;
    MapViewport(double west,double south,double east,double north){
        this.west=west;this.south=south;this.east=east;this.north=north;
    }
    boolean queryable(){
        return queryable(0.2);
    }
    boolean queryable(double maxSpan){
        return finite(west)&&finite(south)&&finite(east)&&finite(north)
            && west>=-180&&east<=180&&south>=-90&&north<=90&&west<east&&south<north
            && east-west<=maxSpan&&north-south<=maxSpan;
    }
    private boolean finite(double value){return !Double.isNaN(value)&&!Double.isInfinite(value);}
    String bbox(){return west+","+south+","+east+","+north;}
    String key(){return Math.round(west*100000)+":"+Math.round(south*100000)+":"+Math.round(east*100000)+":"+Math.round(north*100000);}
}
