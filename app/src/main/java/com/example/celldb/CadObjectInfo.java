package com.example.celldb;

import java.util.*;
import java.util.regex.*;

/** Properties come from the selected entity, never from a guessed nearby pole. */
final class CadObjectInfo {
    private static final Pattern POLE=Pattern.compile("(?<![A-Za-z0-9])[0-9]{4}[A-Za-z]{1,2}[0-9]{3}(?![A-Za-z0-9])");
    static Map<String,String> attributes(CadRecord record) {
        LinkedHashMap<String,String> result=new LinkedHashMap<>();
        String raw=record.fields.get("ATTRIBUTES");
        if(raw==null)raw=record.fields.get("원본속성");
        if(raw!=null)for(String item:raw.split("\\|")) {
            int equal=item.indexOf('=');
            if(equal>0)result.put(item.substring(0,equal).trim(),item.substring(equal+1).trim());
        }
        return result;
    }
    private static String first(Map<String,String> values,String... names) {
        for(String key:names){String value=values.get(key);if(value!=null&&!value.trim().isEmpty())return value.trim();}
        return "";
    }
    static String pole(CadRecord record) {
        Map<String,String> attrs=attributes(record);
        String value=first(record.fields,"전주번호","전주정보","POLE_ID","POLE_NO");
        if(value.isEmpty())value=first(attrs,"전주번호","전주정보","POLE_ID","POLE_NO");
        if(!value.isEmpty())return value;
        for(String candidate:new String[]{first(attrs,"ID","SUB_ID"),first(record.fields,"LOCATION"),first(record.fields,"XDATA")}) {
            Matcher match=POLE.matcher(candidate);if(match.find())return match.group().toUpperCase(Locale.ROOT);
        }
        return "";
    }
    static String address(CadRecord record) {
        String[] keys={"주소","도로명주소","지번주소","ADDRESS","ROAD_ADDRESS"};
        String value=first(record.fields,keys);
        return value.isEmpty()?first(attributes(record),keys):value;
    }
}
