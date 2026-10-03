package com.example.celldb;

import android.content.Context;
import android.net.Uri;
import java.io.*;
import java.util.*;
import com.example.celldb.network.SimpleXlsxReader;
import com.example.celldb.network.NetworkExcelRepository;

final class XlsxCadImporter {
    private XlsxCadImporter() {}
    static ArrayList<CadRecord> read(Context context,Uri uri) throws Exception {
        try(InputStream in=context.getContentResolver().openInputStream(uri)) {
            if(in==null) throw new IOException("파일을 열 수 없습니다.");
            return read(in);
        }
    }
    static ArrayList<CadRecord> read(InputStream in) throws Exception {
        Map<String,SimpleXlsxReader.Sheet> sheets=SimpleXlsxReader.read(in);
        NetworkExcelRepository.validateSheets(sheets);
        ArrayList<CadRecord> result=new ArrayList<>();
        for(String category:new String[]{"CELL","FACILITY","EQUIPMENT","FIBER","COAX"}) {
            SimpleXlsxReader.Sheet sheet=sheets.get(category);
            List<String> headers=sheet.rows.get(0);
            for(int i=1;i<sheet.rows.size();i++) {
                List<String> row=sheet.rows.get(i);
                LinkedHashMap<String,String> fields=new LinkedHashMap<>();
                for(int col=0;col<headers.size();col++) fields.put(headers.get(col).trim(),col<row.size()?row.get(col).trim():"");
                CadRecord record=toRecord(category,fields);
                if(record!=null) result.add(record);
            }
        }
        return result;
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
