package com.example.celldb;

/** Provider-independent level based on the ground width of the current viewport. */
final class DrawingLevel {
    static String forViewport(MapViewport v){
        if(v==null)return "overview";
        double meters=(v.east-v.west)*111320*Math.cos(Math.toRadians((v.north+v.south)/2));
        return meters>5000?"overview":meters>1000?"network":"facilities";
    }
    static boolean groupVisible(String level,String group){
        return "FIBER".equals(group)||(!"overview".equals(level)&&"COAX".equals(group))
            ||("facilities".equals(level)&&"POLE".equals(group));
    }
    static boolean recordVisible(String level,CadRecord r){
        return "facilities".equals(level)||"FIBER".equals(r.category)||"COAX".equals(r.category);
    }
    static String label(String level){
        return "overview".equals(level)?"광케이블":"network".equals(level)?"광 + 동축케이블":"광 + 동축 + 시설";
    }
}
