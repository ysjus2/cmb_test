package com.example.celldb;
import java.util.Locale;

/** Uses semantic names only, without reading CAD symbol geometry. */
final class CmbSymbolType {
    private CmbSymbolType(){}

    static String fromLayer(String layer){
        String s=(layer==null?"":layer).toUpperCase(Locale.ROOT);
        if(s.contains("MANHOLE")||s.contains("HANDHOLE")||s.contains("맨홀"))
            return (s.contains("RECT")||s.contains("SQUARE")||s.contains("사각"))?"MH_RECT":"MH";
        if(s.startsWith("CN_L_POLE_")||s.contains("전주"))return "POLE";
        if(s.contains("ONU"))return "ONU";
        if(s.contains("POWER")||s.matches(".*(^|[^A-Z0-9])PS([^A-Z0-9]|$).*"))return "PWR_PS";
        if(s.contains("AMP"))return "AMP";
        if(s.contains("TAP"))return "TAP";
        if(s.contains("3WAY")||s.contains("3-WAY")||s.contains("3분기"))return "SPL3";
        if(s.contains("2WAY")||s.contains("2-WAY")||s.contains("2분기"))return "SPL2";
        if(s.contains("PASSIVE")||s.contains("SPLIT"))return "SPL";
        if(s.contains("CLOSURE")||s.contains("TERMINAL"))return "FBR";
        if(s.contains("CENTER")||s.contains("CABINET"))return "CAB";
        return "DEV";
    }
}
