package com.example.celldb;

import java.util.ArrayList;
import java.util.Iterator;
import org.json.JSONArray;
import org.json.JSONObject;

final class ServerCadParser {
    static ArrayList<CadRecord> feature(String dataset,JSONObject feature) throws Exception {
        JSONObject properties=feature.getJSONObject("properties"),geometry=feature.getJSONObject("geometry");
        String type=geometry.getString("type"),group=properties.getString("group_id");
        JSONArray coordinates=geometry.getJSONArray("coordinates");
        if(!type.equals("Point")&&!type.equals("LineString"))throw new Exception("지원하지 않는 서버 객체입니다.");
        ArrayList<CadRecord> rows=new ArrayList<>();
        int count=type.equals("Point")?1:coordinates.length();
        if(count<1||count>5000)throw new Exception("서버 객체의 정점 수가 잘못되었습니다.");
        JSONObject fields=properties.optJSONObject("attributes");
        fields=fields==null?null:fields.optJSONObject("fields");
        for(int i=0;i<count;i++){
            JSONArray point=type.equals("Point")?coordinates:coordinates.getJSONArray(i);
            CadRecord record=new CadRecord();
            record.layer=properties.getString("layer");
            String entity=properties.getString("entity_id");
            record.id=dataset+":"+record.layer+":"+entity;
            record.category=type.equals("LineString")?(group.equals("FIBER")?"FIBER":"COAX"):(group.equals("POLE")?"FACILITY":"EQUIPMENT");
            record.name=properties.optString("name",record.layer);record.source="SERVER";record.sequence=i;
            record.longitude=point.getDouble(0);record.latitude=point.getDouble(1);
            if(!record.hasCoordinates())throw new Exception("서버 좌표가 잘못되었습니다.");
            if(fields!=null)for(Iterator<String> keys=fields.keys();keys.hasNext();){String key=keys.next();record.fields.put(key,fields.optString(key,""));}
            record.fields.put("CAD레이어",record.layer);
            record.fields.put("__symbol",CmbSymbolType.fromLayer(record.layer+" "+record.name)+":"+properties.optDouble("symbol_rotation",0));
            JSONObject layout=properties.optJSONObject("cmb_layout");
            if(type.equals("Point")&&layout!=null&&"cmb-authored-v1".equals(layout.optString("source")))
                record.fields.put("__cmbLayout",layout.toString());
            record.fields.put("__serverDataset",dataset);record.fields.put("__serverEntity",entity);
            rows.add(record);
        }
        return rows;
    }
}
