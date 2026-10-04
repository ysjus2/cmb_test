package com.example.celldb.network;

import java.io.*;
import java.util.*;
import java.util.zip.*;
import javax.xml.parsers.SAXParserFactory;
import org.xml.sax.*;
import org.xml.sax.helpers.DefaultHandler;

/** Disk-backed ZIP and streaming XML for large CAD exports. */
public final class SimpleXlsxReader {
    public static final class Sheet {
        public final String name;
        public final List<List<String>> rows;
        Sheet(String name,List<List<String>> rows) { this.name=name; this.rows=rows; }
    }
    public interface SheetFilter { boolean accept(String name); }
    public interface RowVisitor { void row(String sheet,int index,List<String> values) throws Exception; }
    private SimpleXlsxReader() {}
    public static Map<String,Sheet> read(InputStream input) throws Exception {
        LinkedHashMap<String,Sheet> result=new LinkedHashMap<>();
        visit(input,name->true,(name,index,row)->{
            Sheet sheet=result.get(name);
            if(sheet==null) { sheet=new Sheet(name,new ArrayList<>()); result.put(name,sheet); }
            sheet.rows.add(row);
        });
        return result;
    }
    public static void visit(InputStream input,SheetFilter filter,RowVisitor visitor) throws Exception {
        visit(input,filter,visitor,null);
    }
    public static void visit(InputStream input,SheetFilter filter,RowVisitor visitor,File cacheDir) throws Exception {
        File temp=File.createTempFile("cad-import-", ".xlsx",cacheDir);
        try {
            try(OutputStream out=new BufferedOutputStream(new FileOutputStream(temp))) {
                byte[] b=new byte[32768]; int n;
                while((n=input.read(b))!=-1) out.write(b,0,n);
            }
            try(ZipFile zip=new ZipFile(temp)) {
                Map<String,String> rels=new HashMap<>();
                parse(zip,"xl/_rels/workbook.xml.rels",new DefaultHandler(){
                    public void startElement(String uri,String local,String q,Attributes a) {
                        if(local.equals("Relationship")) rels.put(a.getValue("Id"),a.getValue("Target"));
                    }
                },true);
                LinkedHashMap<String,String> sheets=new LinkedHashMap<>();
                parse(zip,"xl/workbook.xml",new DefaultHandler(){
                    public void startElement(String uri,String local,String q,Attributes a) {
                        if(local.equals("sheet")) {
                            String rid=a.getValue("http://schemas.openxmlformats.org/officeDocument/2006/relationships","id");
                            if(rid==null) rid=a.getValue("r:id");
                            sheets.put(a.getValue("name"),rels.get(rid));
                        }
                    }
                },true);
                List<String> shared=new ArrayList<>();
                parse(zip,"xl/sharedStrings.xml",new DefaultHandler(){
                    StringBuilder value; boolean text;
                    public void startElement(String uri,String local,String q,Attributes a){
                        if(local.equals("si"))value=new StringBuilder();
                        if(local.equals("t"))text=true;
                    }
                    public void characters(char[] c,int s,int n){if(text && value!=null)value.append(c,s,n);}
                    public void endElement(String uri,String local,String q){
                        if(local.equals("t"))text=false;
                        if(local.equals("si")){shared.add(value.toString());value=null;}
                    }
                },false);
                for(Map.Entry<String,String> sheet:sheets.entrySet()) {
                    if(!filter.accept(sheet.getKey()))continue;
                    String target=sheet.getValue();
                    if(target==null)throw new IOException("시트 연결이 없습니다: "+sheet.getKey());
                    String path=target.startsWith("/")?target.substring(1):"xl/"+target;
                    parse(zip,normalize(path),new Rows(sheet.getKey(),shared,visitor),true);
                }
            }
        } finally { temp.delete(); }
    }
    private static void parse(ZipFile zip,String path,DefaultHandler handler,boolean required) throws Exception {
        ZipEntry entry=zip.getEntry(path);
        if(entry==null) { if(required)throw new IOException("유효한 XLSX가 아닙니다: "+path); return; }
        SAXParserFactory f=SAXParserFactory.newInstance(); f.setNamespaceAware(true);
        try{f.setFeature("http://apache.org/xml/features/disallow-doctype-decl",true);}catch(Exception ignored){}
        try{f.setFeature("http://xml.org/sax/features/external-general-entities",false);}catch(Exception ignored){}
        try{f.setFeature("http://xml.org/sax/features/external-parameter-entities",false);}catch(Exception ignored){}
        try(InputStream stream=zip.getInputStream(entry)){f.newSAXParser().parse(stream,handler);}
    }
    private static final class Rows extends DefaultHandler {
        final String sheet; final List<String> shared; final RowVisitor visitor;
        List<String> row; String type; int column,index; StringBuilder value; boolean capture;
        Rows(String sheet,List<String> shared,RowVisitor visitor){this.sheet=sheet;this.shared=shared;this.visitor=visitor;}
        public void startElement(String uri,String local,String q,Attributes a){
            if(local.equals("row"))row=new ArrayList<>();
            if(local.equals("c")) {column=columnIndex(a.getValue("r"));type=a.getValue("t");value=new StringBuilder();}
            if(local.equals("v") || local.equals("t"))capture=true;
        }
        public void characters(char[] c,int s,int n){if(capture && value!=null)value.append(c,s,n);}
        public void endElement(String uri,String local,String q) throws SAXException {
            if(local.equals("v") || local.equals("t"))capture=false;
            if(local.equals("c")) {
                String v=value.toString();
                if("s".equals(type))try{v=shared.get(Integer.parseInt(v));}catch(Exception e){throw new SAXException("잘못된 공유 문자열",e);}
                while(row.size()<=column)row.add("");row.set(column,v);
            }
            if(local.equals("row"))try{visitor.row(sheet,index++,row);}catch(Exception e){throw new SAXException(e);}
        }
    }
    private static int columnIndex(String ref){
        int n=0;if(ref==null)return 0;
        for(int i=0;i<ref.length();i++){char c=ref.charAt(i);if(c<'A'||c>'Z')break;n=n*26+c-'A'+1;}
        return Math.max(0,n-1);
    }
    private static String normalize(String path){
        LinkedList<String> parts=new LinkedList<>();
        for(String s:path.split("/")){if(s.equals("..")){if(!parts.isEmpty())parts.removeLast();}else if(!s.isEmpty()&&!s.equals("."))parts.add(s);}
        StringBuilder out=new StringBuilder();for(String s:parts){if(out.length()>0)out.append('/');out.append(s);}return out.toString();
    }
}
