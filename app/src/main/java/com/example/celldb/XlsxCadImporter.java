package com.example.celldb;

import android.content.Context;
import android.net.Uri;
import org.w3c.dom.*;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.*;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

final class XlsxCadImporter {
    private XlsxCadImporter() {}

    static ArrayList<CadRecord> read(Context context, Uri uri) throws Exception {
        LinkedHashMap<String, byte[]> files = new LinkedHashMap<>();
        try (InputStream input = context.getContentResolver().openInputStream(uri);
             ZipInputStream zip = new ZipInputStream(new BufferedInputStream(input))) {
            ZipEntry e;
            byte[] buffer = new byte[16384];
            while ((e = zip.getNextEntry()) != null) {
                if (e.isDirectory()) continue;
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                int n;
                while ((n = zip.read(buffer)) > 0) out.write(buffer, 0, n);
                files.put(e.getName(), out.toByteArray());
            }
        }
        if (!files.containsKey("xl/workbook.xml")) throw new IOException("XLSX workbook.xml이 없습니다.");

        Map<String,String> relTargets = workbookRelationships(files.get("xl/_rels/workbook.xml.rels"));
        LinkedHashMap<String,String> sheets = workbookSheets(files.get("xl/workbook.xml"), relTargets);
        ArrayList<String> shared = sharedStrings(files.get("xl/sharedStrings.xml"));

        ArrayList<CadRecord> result = new ArrayList<>();
        for (String wanted : new String[]{"CELL","FACILITY","EQUIPMENT","FIBER","COAX"}) {
            String target = sheets.get(wanted);
            if (target == null) continue;
            String path = target.startsWith("/") ? target.substring(1)
                    : (target.startsWith("xl/") ? target : "xl/" + target.replace("../", ""));
            byte[] sheet = files.get(path);
            if (sheet == null) continue;
            result.addAll(parseSheet(wanted, sheet, shared));
        }
        return result;
    }

    private static Document xml(byte[] bytes) throws Exception {
        if (bytes == null) return null;
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(true);
        try { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true); } catch (Exception ignored) {}
        return f.newDocumentBuilder().parse(new ByteArrayInputStream(bytes));
    }

    private static Map<String,String> workbookRelationships(byte[] data) throws Exception {
        HashMap<String,String> map = new HashMap<>();
        Document d = xml(data);
        if (d == null) return map;
        NodeList rels = d.getElementsByTagNameNS("*", "Relationship");
        for (int i=0;i<rels.getLength();i++) {
            Element e=(Element)rels.item(i);
            map.put(e.getAttribute("Id"), e.getAttribute("Target"));
        }
        return map;
    }

    private static LinkedHashMap<String,String> workbookSheets(byte[] data, Map<String,String> rels) throws Exception {
        LinkedHashMap<String,String> out = new LinkedHashMap<>();
        Document d = xml(data);
        NodeList list = d.getElementsByTagNameNS("*", "sheet");
        for (int i=0;i<list.getLength();i++) {
            Element e=(Element)list.item(i);
            String name=e.getAttribute("name");
            String rid=e.getAttributeNS("http://schemas.openxmlformats.org/officeDocument/2006/relationships","id");
            String target=rels.get(rid);
            if (target!=null) out.put(name.trim().toUpperCase(Locale.US), target);
        }
        return out;
    }

    private static ArrayList<String> sharedStrings(byte[] data) throws Exception {
        ArrayList<String> out=new ArrayList<>();
        Document d=xml(data);
        if (d==null) return out;
        NodeList si=d.getElementsByTagNameNS("*","si");
        for(int i=0;i<si.getLength();i++) out.add(allText(si.item(i)));
        return out;
    }

    private static String allText(Node node) {
        StringBuilder b=new StringBuilder();
        NodeList list=((Element)node).getElementsByTagNameNS("*","t");
        for(int i=0;i<list.getLength();i++) b.append(list.item(i).getTextContent());
        return b.toString();
    }

    private static ArrayList<CadRecord> parseSheet(String category, byte[] data, ArrayList<String> shared) throws Exception {
        ArrayList<CadRecord> out=new ArrayList<>();
        Document d=xml(data);
        NodeList rows=d.getElementsByTagNameNS("*","row");
        if(rows.getLength()==0) return out;
        LinkedHashMap<Integer,String> headers = rowValues((Element)rows.item(0), shared);
        for(int i=1;i<rows.getLength();i++) {
            LinkedHashMap<Integer,String> values=rowValues((Element)rows.item(i), shared);
            if(values.isEmpty()) continue;
            LinkedHashMap<String,String> fields=new LinkedHashMap<>();
            for(Map.Entry<Integer,String> e:headers.entrySet()) fields.put(e.getValue(), values.getOrDefault(e.getKey(),"").trim());
            CadRecord r=toRecord(category, fields);
            if(r!=null) out.add(r);
        }
        return out;
    }

    private static LinkedHashMap<Integer,String> rowValues(Element row, ArrayList<String> shared) {
        LinkedHashMap<Integer,String> out=new LinkedHashMap<>();
        NodeList cells=row.getElementsByTagNameNS("*","c");
        for(int i=0;i<cells.getLength();i++) {
            Element c=(Element)cells.item(i);
            int col=columnIndex(c.getAttribute("r"));
            String type=c.getAttribute("t");
            String value="";
            if("inlineStr".equals(type)) {
                NodeList is=c.getElementsByTagNameNS("*","is");
                if(is.getLength()>0) value=allText(is.item(0));
            } else {
                NodeList vs=c.getElementsByTagNameNS("*","v");
                if(vs.getLength()>0) value=vs.item(0).getTextContent();
                if("s".equals(type)) {
                    try { value=shared.get(Integer.parseInt(value)); } catch(Exception ignored) {}
                }
            }
            out.put(col, value==null?"":value);
        }
        return out;
    }

    private static int columnIndex(String ref) {
        int col=0;
        for(int i=0;i<ref.length();i++) {
            char c=ref.charAt(i);
            if(c<'A'||c>'Z') break;
            col=col*26+(c-'A'+1);
        }
        return Math.max(0,col-1);
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
