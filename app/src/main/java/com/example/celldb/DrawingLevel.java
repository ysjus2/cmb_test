package com.example.celldb;

import java.util.Locale;

/** Windows 1.0 display-level policy mirrored on Android. */
final class DrawingLevel {
    private DrawingLevel(){}

    static String forWindowsLevel(int level){
        return "L"+Math.max(1,Math.min(14,level));
    }

    // Legacy server detail_level compatibility. Screen visibility no longer uses these names.
    static String forViewport(MapViewport v){
        if(v==null)return "overview";
        double meters=(v.east-v.west)*111320*Math.cos(Math.toRadians((v.north+v.south)/2));
        return meters>5000?"overview":meters>1000?"network":"facilities";
    }

    static int number(String level){
        if(level==null)return 6;
        try{
            String s=level.trim().toUpperCase(Locale.ROOT);
            if(s.startsWith("L"))s=s.substring(1);
            return Math.max(1,Math.min(14,Integer.parseInt(s)));
        }catch(Exception ignored){return 6;}
    }

    static boolean groupVisible(String level,String group){
        int lv=number(level);
        if("FIBER".equals(group))return true;
        if("COAX".equals(group))return lv<=5;
        if("POLE".equals(group)||"CONDUIT".equals(group))return lv<=3;
        return false;
    }

    static boolean isCellBoundary(CadRecord r){
        String s=((r.layer==null?"":r.layer)+" "+(r.name==null?"":r.name)).toUpperCase(Locale.ROOT);
        return s.startsWith("CN_C_CELLBOUND")||s.contains("CELLBOUND");
    }

    static boolean isCellNumber(CadRecord r){
        String s=((r.layer==null?"":r.layer)+" "+(r.name==null?"":r.name)).toUpperCase(Locale.ROOT);
        return s.startsWith("CN_C_CELLNO")||s.contains("CELLNO");
    }

    static String serverGroup(CadRecord r){
        String g=r.fields.get("__serverGroup");
        return g==null?"":g.trim().toUpperCase(Locale.ROOT);
    }

    static String symbol(CadRecord r){
        String raw=r.fields.get("__symbol");
        if(raw==null)return "";
        int colon=raw.indexOf(':');
        return (colon<0?raw:raw.substring(0,colon)).trim().toUpperCase(Locale.ROOT);
    }

    static boolean isFiberCable(CadRecord r){
        return "FIBER".equals(r.category);
    }

    static boolean isFiberDevice(CadRecord r){
        return "FIBER".equals(serverGroup(r)) && !"FIBER".equals(r.category);
    }

    static boolean isCoaxCable(CadRecord r){
        return "COAX".equals(r.category);
    }

    static boolean isTapCable(CadRecord r){
        String s=((r.layer==null?"":r.layer)+" "+(r.name==null?"":r.name)+" "+r.fields.get("__serverBlock")).toUpperCase(Locale.ROOT);
        return s.contains("TAP");
    }

    static boolean coaxDeviceVisible(CadRecord r,int lv){
        String k=symbol(r);
        if(lv<=1)return true;
        if(lv==2){
            return k.equals("ONU")||k.equals("AMP")||k.startsWith("SPL")||
                    k.equals("PWR")||k.equals("PWR_PS")||k.equals("TAP")||
                    k.equals("PI")||k.equals("FIBER_CLOSURE")||k.equals("DEV");
        }
        if(lv==3){
            return k.equals("ONU")||k.equals("AMP")||k.startsWith("SPL")||
                    k.equals("PWR")||k.equals("PWR_PS")||k.equals("FIBER_CLOSURE");
        }
        return false;
    }

    static boolean recordVisible(String level,CadRecord r){
        int lv=number(level);

        // 광 선로는 모든 레벨에서 유지한다.
        if(isFiberCable(r))return true;

        // Windows 기준: 광함체는 L3부터, 그 외 광기기는 L2부터 표시한다.
        if(isFiberDevice(r)){
            return "FIBER_CLOSURE".equals(symbol(r)) ? lv<=3 : lv<=2;
        }

        // 동축 셀경계/셀번호는 L5/L4 단계에서 별도 표시.
        if(isCellBoundary(r))return lv<=5;
        if(isCellNumber(r))return lv<=4;

        if(isCoaxCable(r)){
            if(lv>3)return false;
            if(lv==3)return !isTapCable(r); // 주요 trunk 중심
            return true;
        }

        if("COAX".equals(serverGroup(r)))return lv<=3 && coaxDeviceVisible(r,lv);

        // 전주/관로 및 기타 상세 객체는 L3 이하에서만.
        return lv<=3;
    }

    static String label(String level){
        int lv=number(level);
        if(lv>=6)return "L"+lv+" · 광";
        if(lv==5)return "L5 · 광 + 셀경계";
        if(lv==4)return "L4 · 광 + 셀경계 + 셀번호";
        if(lv==3)return "L3 · 광함체 + 주요 동축";
        if(lv==2)return "L2 · 광기기 + 동축 상세";
        return "L1 · 전체 상세";
    }
}
