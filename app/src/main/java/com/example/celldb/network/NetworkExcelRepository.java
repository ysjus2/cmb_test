package com.example.celldb.network;

import com.example.celldb.network.NetworkModels.GeoPoint;
import com.example.celldb.network.NetworkModels.LineItem;
import com.example.celldb.network.NetworkModels.NetworkData;
import com.example.celldb.network.NetworkModels.PointItem;

import java.io.InputStream;
import java.util.*;

public final class NetworkExcelRepository {
    private NetworkExcelRepository() {}

    public static NetworkData read(InputStream in) throws Exception {
        Map<String, SimpleXlsxReader.Sheet> sheets = SimpleXlsxReader.read(in);
        for (String name : new String[]{"CELL", "FACILITY", "EQUIPMENT", "FIBER", "COAX"}) {
            SimpleXlsxReader.Sheet sheet = sheets.get(name);
            if (sheet == null || sheet.rows.isEmpty()) throw new java.io.IOException(name + " 시트가 없습니다.");
            Map<String,Integer> columns = header(sheet.rows.get(0));
            String id = name.equals("CELL") ? "셀번호" : name.equals("FACILITY") ? "시설ID"
                    : name.equals("EQUIPMENT") ? "장비ID" : "선로ID";
            for (String required : new String[]{id, "경도", "위도"}) {
                if (!columns.containsKey(required)) throw new java.io.IOException(name + " 시트에 " + required + " 열이 없습니다.");
            }
            if ((name.equals("FIBER") || name.equals("COAX")) && !columns.containsKey("순번"))
                throw new java.io.IOException(name + " 시트에 순번 열이 없습니다.");
        }
        NetworkData data = new NetworkData();

        readCell(sheets.get("CELL"), data);
        readFacility(sheets.get("FACILITY"), data);
        readEquipment(sheets.get("EQUIPMENT"), data);
        data.fiber.addAll(readLines(sheets.get("FIBER"), data));
        data.coax.addAll(readLines(sheets.get("COAX"), data));
        return data;
    }

    private static Map<String,Integer> header(List<String> row) {
        HashMap<String,Integer> out = new HashMap<>();
        if (row == null) return out;
        for (int i=0;i<row.size();i++) out.put(row.get(i).trim(), i);
        return out;
    }

    private static String v(List<String> row, Map<String,Integer> h, String key) {
        Integer i = h.get(key);
        return i == null || i < 0 || i >= row.size() ? "" : row.get(i).trim();
    }

    private static double d(List<String> row, Map<String,Integer> h, String key) {
        try { return Double.parseDouble(v(row,h,key)); } catch (Exception e) { return Double.NaN; }
    }

    private static int n(List<String> row, Map<String,Integer> h, String key) {
        try { return (int)Math.round(Double.parseDouble(v(row,h,key))); } catch (Exception e) { return 0; }
    }

    private static boolean valid(double lat, double lon) {
        return !Double.isNaN(lat) && !Double.isInfinite(lat) && !Double.isNaN(lon) && !Double.isInfinite(lon)
                && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
    }

    private static boolean blank(List<String> row) {
        for (String value : row) if (!value.trim().isEmpty()) return false;
        return true;
    }

    private static void readCell(SimpleXlsxReader.Sheet sheet, NetworkData data) {
        if (sheet == null || sheet.rows.isEmpty()) return;
        Map<String,Integer> h = header(sheet.rows.get(0));
        for (int i=1;i<sheet.rows.size();i++) {
            List<String> r = sheet.rows.get(i);
            double lon=d(r,h,"경도"), lat=d(r,h,"위도");
            if (!valid(lat, lon)) { if (!blank(r)) data.skippedRows++; continue; }
            String id=v(r,h,"셀번호");
            String name=v(r,h,"셀명");
            String detail="상위국사: "+v(r,h,"상위국사")
                    +"\n상향포트: "+v(r,h,"상향포트")
                    +"\n하향포트: "+v(r,h,"하향포트")
                    +"\n주소: "+v(r,h,"주소")
                    +"\n전주번호: "+v(r,h,"전주번호")
                    +"\n셀구분: "+v(r,h,"셀구분")
                    +"\n비고: "+v(r,h,"비고");
            data.cells.add(new PointItem("CELL", id, name, lat, lon, detail));
        }
    }

    private static void readFacility(SimpleXlsxReader.Sheet sheet, NetworkData data) {
        if (sheet == null || sheet.rows.isEmpty()) return;
        Map<String,Integer> h = header(sheet.rows.get(0));
        for (int i=1;i<sheet.rows.size();i++) {
            List<String> r=sheet.rows.get(i);
            double lon=d(r,h,"경도"), lat=d(r,h,"위도");
            if (!valid(lat, lon)) { if (!blank(r)) data.skippedRows++; continue; }
            String type=v(r,h,"구분");
            String id=v(r,h,"시설ID");
            String detail="구분: "+type+"\n블록: "+v(r,h,"블록명")
                    +"\n레이어: "+v(r,h,"CAD레이어")
                    +"\n원본속성: "+v(r,h,"원본속성");
            data.facilities.add(new PointItem("FACILITY", id, type+" "+id, lat, lon, detail));
        }
    }

    private static void readEquipment(SimpleXlsxReader.Sheet sheet, NetworkData data) {
        if (sheet == null || sheet.rows.isEmpty()) return;
        Map<String,Integer> h = header(sheet.rows.get(0));
        for (int i=1;i<sheet.rows.size();i++) {
            List<String> r=sheet.rows.get(i);
            double lon=d(r,h,"경도"), lat=d(r,h,"위도");
            if (!valid(lat, lon)) { if (!blank(r)) data.skippedRows++; continue; }
            String type=v(r,h,"구분");
            String id=v(r,h,"장비ID");
            String detail="구분: "+type
                    +"\n셀정보: "+v(r,h,"셀정보")
                    +"\nOBJECT: "+v(r,h,"OBJECT")
                    +"\nLOCATION: "+v(r,h,"LOCATION")
                    +"\nFIBER: "+v(r,h,"FIBER");
            data.equipment.add(new PointItem("EQUIPMENT", id, type+" "+id, lat, lon, detail));
        }
    }

    private static List<LineItem> readLines(SimpleXlsxReader.Sheet sheet, NetworkData data) {
        ArrayList<LineItem> out = new ArrayList<>();
        if (sheet == null || sheet.rows.isEmpty()) return out;
        Map<String,Integer> h=header(sheet.rows.get(0));

        LinkedHashMap<String, TreeMap<Integer, GeoPoint>> points = new LinkedHashMap<>();
        LinkedHashMap<String, LineItem> lines = new LinkedHashMap<>();

        for (int i=1;i<sheet.rows.size();i++) {
            List<String> r=sheet.rows.get(i);
            String id=v(r,h,"선로ID");
            if (id.isEmpty()) continue;
            double lon=d(r,h,"경도"), lat=d(r,h,"위도");
            if (!valid(lat, lon) || Double.isNaN(d(r,h,"순번"))) { data.skippedRows++; continue; }
            if (!lines.containsKey(id)) lines.put(id, new LineItem(
                    id, v(r,h,"케이블명"), v(r,h,"케이블ID"), v(r,h,"연결정보"), v(r,h,"길이")));
            if (!points.containsKey(id)) points.put(id, new TreeMap<>());
            points.get(id).put(n(r,h,"순번"), new GeoPoint(lat,lon));
        }

        for (Map.Entry<String,LineItem> e : lines.entrySet()) {
            TreeMap<Integer,GeoPoint> p=points.get(e.getKey());
            if (p != null) e.getValue().points.addAll(p.values());
            if (e.getValue().points.size() >= 2) out.add(e.getValue());
        }
        return out;
    }
}
