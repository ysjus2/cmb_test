package com.example.celldb;
import java.util.Locale;
/** Uses semantic names only, without reading CAD symbol geometry. */
final class CmbSymbolType {
    static String fromLayer(String layer){
        String s=layer.toUpperCase(Locale.ROOT);
        if(s.contains("MANHOLE")||s.contains("HANDHOLE")||s.contains("맨홀"))return (s.contains("RECT")||s.contains("SQUARE")||s.contains("사각"))?"MH_RECT":"MH";
        if(s.startsWith("CN_L_POLE_")||s.contains("전주"))return "POLE";
        if(s.contains("ONU"))return "ONU";
        if(s.contains("POWER"))return "PWR";
        if(s.contains("AMP"))return "AMP";
        if(s.contains("TAP"))return "TAP";
        if(s.contains("PASSIVE")||s.contains("SPLIT"))return "SPL";
        if(s.contains("CLOSURE"))return "FBR";
        if(s.contains("CENTER")||s.contains("CABINET"))return "CAB";
        return "DEV";
    }
}
