package com.example.celldb;

import java.util.Locale;

final class LayerGroups {
    static final String[] IDS = {"FIBER", "COAX", "POLE"};
    static final String[] NAMES = {"광", "동축", "전주·맨홀"};
    static boolean excluded(String layer) {
        String s=layer.toUpperCase(Locale.ROOT);
        return s.startsWith("TL_") || s.startsWith("CN_L_POLEMAP_")
                || s.contains("BUILDING") || s.contains("ROAD") || s.contains("TERRAIN")
                || s.contains("도로") || s.contains("건물") || s.contains("지형");
    }
    static String defaultGroup(String layer, String category) {
        if(excluded(layer)) return "";
        String s=layer.toUpperCase(Locale.ROOT);
        if(s.startsWith("CN_L_POLE_") || s.contains("MANHOLE") || s.contains("HANDHOLE")
                || s.contains("전주") || s.contains("맨홀")) return "POLE";
        if(s.startsWith("CN_F_") || s.contains("FIBER") || s.contains("광")) return "FIBER";
        if(s.startsWith("CN_C_") || s.contains("COAX") || s.contains("동축")) return "COAX";
        if("FACILITY".equals(category)) return "POLE";
        if("FIBER".equals(category)) return "FIBER";
        if("COAX".equals(category) || "CELL".equals(category) || "EQUIPMENT".equals(category)) return "COAX";
        return "";
    }
    static boolean importSheet(String name) {
        return !defaultGroup(name, "").isEmpty() || name.equals("LAYER_INDEX")
                || name.equals("CELL") || name.equals("FACILITY") || name.equals("EQUIPMENT")
                || name.equals("FIBER") || name.equals("COAX");
    }
    static String key(CadRecord r) { return r.layer.isEmpty() ? "기본 · "+r.category : r.layer; }
}
