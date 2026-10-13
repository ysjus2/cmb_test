package com.example.celldb;
import java.util.Locale;

/** Uses semantic names only, without reading CAD symbol geometry. */
final class CmbSymbolType {
    private CmbSymbolType(){}

    static String fromLayer(String layer){
        String s=(layer==null?"":layer).toUpperCase(Locale.ROOT);
        String normalized=" "+s.replace('-',' ').replace('_',' ')+" ";

        if(s.contains("ANNO")||s.contains("CONNECTOR")||s.contains("FO_VCONN")||s.contains("FO_VOCONN"))return "HIDDEN";

        if(s.contains("MANHOLE")||s.contains("HANDHOLE")||s.contains("맨홀"))
            return (s.contains("RECT")||s.contains("SQUARE")||s.contains("사각"))?"MH_RECT":"MH";
        if(s.startsWith("CN_L_POLE_")||s.contains("전주"))return "POLE";

        // 실제 CMB CAD code를 일반 키워드보다 우선한다.
        if(s.contains("CN_C_ONU")||normalized.contains(" ONU "))return "ONU";
        if(s.contains("CN_C_AMP")||normalized.contains(" AMP ")||s.contains("증폭"))return "AMP";
        if(s.contains("CN_C_TAP")||normalized.contains(" TAP "))return "TAP";

        if(s.contains("3SP")||s.contains("3WAY")||s.contains("3-WAY")||s.contains("3분기")||s.contains("3분배"))return "SPL3";
        if(s.contains("2SP")||s.contains("2WAY")||s.contains("2-WAY")||s.contains("2분기")||s.contains("2분배"))return "SPL2";
        if(s.contains("CN_C_DC")||normalized.contains(" DC ")||s.contains("DIRECTIONAL COUPLER"))return "SPL_DC";
        if(s.contains("CN_C_PI")||normalized.contains(" PI "))return "PI";

        if(s.contains("CN_C_POWER")||s.contains("POWER")||normalized.contains(" PS "))return "PWR_PS";

        // Windows v4.27 optical symbol policy.
        if(s.contains("NETOFD"))return "FIBER_OFD";
        if(s.contains("NETFDF"))return "FIBER_FDF";
        if(s.contains("RN-8")||s.contains("RN_8"))return "FIBER_RN8";
        if(s.contains("RN-4")||s.contains("RN_4"))return "FIBER_RN4";
        if(s.contains("OIM-L2")||s.contains("OIM_L2"))return "FIBER_L2";
        if(s.contains("OIM-L3")||s.contains("OIM_L3"))return "FIBER_L3";
        if(s.contains("CN_F_TERMINAL")||s.contains("TERMINAL"))return "FIBER_TERMINAL";
        if(s.contains("CN_F_CLOSURE")||s.contains("CLOSURE")||s.contains("SPL-"))return "FIBER_CLOSURE";
        if(s.contains("CN_F_CENTER")||s.contains("CENTER")||s.contains("CABINET"))return "CAB";

        if(s.contains("PASSIVE")||s.contains("SPLIT"))return "SPL";
        return "DEV";
    }}
