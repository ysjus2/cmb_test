package com.example.celldb;

import android.content.Context;
import android.net.Uri;
import java.io.*;
import java.util.*;
import com.example.celldb.network.SimpleXlsxReader;

final class XlsxCadImporter {
    private XlsxCadImporter() {}
    static ArrayList<CadRecord> read(Context context,Uri uri) throws Exception {
        try(InputStream in=context.getContentResolver().openInputStream(uri)) {
            if(in==null) throw new IOException("파일을 열 수 없습니다.");
            return read(in,context.getCacheDir());
        }
    }
    static ArrayList<CadRecord> read(InputStream in) throws Exception {
        return read(in,null);
    }
    private static ArrayList<CadRecord> read(InputStream in,File cacheDir) throws Exception {
        ArrayList<CadRecord> result=new ArrayList<>();
        Map<String,List<String>> headers=new LinkedHashMap<>();
        Map<String,String> originalLayers=new HashMap<>();
        List<String> legacy=Arrays.asList("CELL","FACILITY","EQUIPMENT","FIBER","COAX");
        try {
            SimpleXlsxReader.visit(in,LayerGroups::importSheet,(sheet,index,row)->{
                if(index==0) {
                    headers.put(sheet,row);
                    if(!sheet.equals("LAYER_INDEX")) {
                        String id=legacy.contains(sheet)?(sheet.equals("CELL")?"셀번호":sheet.equals("FACILITY")?"시설ID":sheet.equals("EQUIPMENT")?"장비ID":"선로ID"):"ENTITY_ID";
                        for(String required:new String[]{id,"경도","위도"})
                            if(!row.contains(required))throw new IOException(sheet+" 시트에 "+required+" 열이 없습니다.");
                        if((sheet.equals("FIBER")||sheet.equals("COAX"))&&!row.contains("순번"))throw new IOException(sheet+" 시트에 순번 열이 없습니다.");
                        if(!legacy.contains(sheet))for(String required:new String[]{"ENTITY_TYPE","SEQ"})
                            if(!row.contains(required))throw new IOException(sheet+" 시트에 "+required+" 열이 없습니다.");
                    }
                    return;
                }
                if(sheet.equals("LAYER_INDEX")) {
                    if(row.size()>1)originalLayers.put(row.get(1),row.get(0));
                    return;
                }
                List<String> h=headers.get(sheet);
                LinkedHashMap<String,String> f=new LinkedHashMap<>();
                for(int c=0;c<h.size();c++)f.put(h.get(c).trim(),c<row.size()?row.get(c).trim():"");
                CadRecord record;
                if(legacy.contains(sheet))record=toRecord(sheet,f);
                else record=layerRecord(originalLayers.containsKey(sheet)?originalLayers.get(sheet):sheet,f);
                if(record!=null && !LayerGroups.excluded(record.layer))result.add(record);
            },cacheDir);
        } catch(org.xml.sax.SAXException e) {
            if(e.getException() instanceof IOException)throw (IOException)e.getException();
            throw e;
        }
        boolean layered=false;
        for(String sheet:headers.keySet())if(!legacy.contains(sheet)&&!sheet.equals("LAYER_INDEX"))layered=true;
        if(!layered)for(String sheet:legacy)if(!headers.containsKey(sheet))throw new IOException(sheet+" 시트가 없습니다.");
        if(result.isEmpty())throw new IOException("표시할 네트워크 데이터가 없습니다. 레이어와 좌표를 확인하세요.");
        boolean validCoordinates=false;
        for(CadRecord r:result)if(r.hasCoordinates()){validCoordinates=true;break;}
        if(layered && !validCoordinates)throw new IOException("네트워크 레이어에 유효한 경도/위도가 없습니다.");
        return result;
    }
    private static CadRecord layerRecord(String layer,LinkedHashMap<String,String> f) throws IOException {
        String group=LayerGroups.defaultGroup(layer,"");
        if(group.isEmpty())return null;
        String type=get(f,"ENTITY_TYPE").toUpperCase(Locale.ROOT);
        CadRecord r=new CadRecord();r.layer=layer;r.fields.putAll(f);r.fields.put("CAD레이어",layer);
        String handle=get(f,"ENTITY_ID");
        if(handle.isEmpty())return null;
        r.id=layer+":"+handle;
        // ESSENPOLY is a recovered CAD cable polyline; its rows are vertices, not equipment markers.
        boolean line=type.equals("LINE")||type.contains("POLYLINE")||type.equals("ESSENPOLY");
        if(layer.toUpperCase(Locale.ROOT).contains("_CABLE_") && !line)
            throw new IOException(layer+" 케이블 객체 형식을 지원하지 않습니다: "+type);
        r.category=line?(group.equals("FIBER")?"FIBER":"COAX"):(group.equals("POLE")?"FACILITY":"EQUIPMENT");
        r.subtype=get(f,"BLOCK_NAME");r.name=get(f,"TEXT");
        if(line) {
            Map<String,String> attrs=CadObjectInfo.attributes(r);
            String cableName=get(attrs,"ESSEN_300"),cableId=get(attrs,"ESSEN_302");
            if(r.name.isEmpty())r.name=cableName;
            if(r.subtype.isEmpty())r.subtype=cableId;
            r.fields.put("케이블명",cableName);r.fields.put("케이블ID",cableId);
            r.fields.put("연결정보",get(attrs,"ESSEN_307"));
        }
        if(r.name.isEmpty())r.name=r.subtype.isEmpty()?layer:r.subtype;
        r.longitude=num(get(f,"경도"));r.latitude=num(get(f,"위도"));
        double seq=num(get(f,"SEQ"));
        boolean finite=!Double.isNaN(seq)&&!Double.isInfinite(seq);
        if(line && (!finite||seq<0||seq!=Math.rint(seq)||seq>Integer.MAX_VALUE))throw new IOException(layer+" 선로 순번이 잘못됐습니다.");
        r.sequence=finite?(int)seq:0;
        r.fields.put("순번",Integer.toString(r.sequence));
        return r;
    }
    private static CadRecord toRecord(String category, LinkedHashMap<String,String> f) {
        CadRecord r=new CadRecord();
        r.category=category;
        r.source=CadRecord.SOURCE_CAD;
        r.fields.putAll(f);
        if("CELL".equals(category)) {
            r.id=get(f,"셀번호");
            r.name=get(f,"셀명");
            r.subtype=get(f,"셀구분");
            r.longitude=num(get(f,"경도"));
            r.latitude=num(get(f,"위도"));
        } else if("FACILITY".equals(category)) {
            r.id=get(f,"시설ID");
            r.name=get(f,"구분");
            r.subtype=get(f,"블록명");
            r.layer=get(f,"CAD레이어");
            r.longitude=num(get(f,"경도"));
            r.latitude=num(get(f,"위도"));
        } else if("EQUIPMENT".equals(category)) {
            r.id=get(f,"장비ID");
            r.name=get(f,"구분");
            r.subtype=get(f,"블록명");
            r.layer=get(f,"CAD레이어");
            r.longitude=num(get(f,"경도"));
            r.latitude=num(get(f,"위도"));
        } else {
            r.id=get(f,"선로ID");
            r.name=get(f,"케이블명");
            r.subtype=get(f,"케이블ID");
            r.layer=get(f,"CAD레이어");
            r.longitude=num(get(f,"경도"));
            r.latitude=num(get(f,"위도"));
            r.sequence=(int)num(get(f,"순번"));
        }
        if(r.id.trim().isEmpty() && !r.hasCoordinates()) return null;
        return r;
    }

    private static String get(Map<String,String> m,String k){ String v=m.get(k); return v==null?"":v.trim(); }
    private static double num(String s){ try{return Double.parseDouble(s);}catch(Exception e){return Double.NaN;} }
}
