package com.example.celldb.network;

import android.util.Log;

import org.w3c.dom.*;
import javax.xml.parsers.DocumentBuilderFactory;

import java.io.*;
import java.util.*;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

public final class SimpleXlsxReader {
    private static final String TAG = "SimpleXlsxReader";

    public static final class Sheet {
        public final String name;
        public final List<List<String>> rows;
        Sheet(String name, List<List<String>> rows) {
            this.name = name;
            this.rows = rows;
        }
    }

    private SimpleXlsxReader() {}

    public static Map<String, Sheet> read(InputStream input) throws Exception {
        Map<String, byte[]> files = unzip(input);
        List<String> shared = readSharedStrings(files.get("xl/sharedStrings.xml"));

        byte[] workbookBytes = files.get("xl/workbook.xml");
        byte[] relBytes = files.get("xl/_rels/workbook.xml.rels");
        if (workbookBytes == null || relBytes == null) {
            throw new IOException("유효한 XLSX가 아닙니다.");
        }

        Map<String, String> relTargets = parseRelationships(relBytes);
        LinkedHashMap<String, Sheet> result = new LinkedHashMap<>();

        Document workbook = parse(workbookBytes);
        NodeList sheets = workbook.getElementsByTagNameNS("*", "sheet");
        for (int i = 0; i < sheets.getLength(); i++) {
            Element e = (Element) sheets.item(i);
            String name = e.getAttribute("name");
            String rid = e.getAttributeNS(
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships", "id");
            if (rid == null || rid.isEmpty()) rid = e.getAttribute("r:id");
            String target = relTargets.get(rid);
            if (target == null) continue;

            String path = target.startsWith("/") ? target.substring(1) : "xl/" + target;
            path = normalize(path);
            byte[] sheetBytes = files.get(path);
            if (sheetBytes == null) {
                Log.w(TAG, "Missing sheet: " + path);
                continue;
            }
            result.put(name, new Sheet(name, readSheet(sheetBytes, shared)));
        }
        return result;
    }

    private static Map<String, byte[]> unzip(InputStream input) throws IOException {
        HashMap<String, byte[]> out = new HashMap<>();
        ZipInputStream zin = new ZipInputStream(new BufferedInputStream(input));
        ZipEntry entry;
        byte[] buf = new byte[8192];
        while ((entry = zin.getNextEntry()) != null) {
            if (!entry.isDirectory()) {
                ByteArrayOutputStream bos = new ByteArrayOutputStream();
                int n;
                while ((n = zin.read(buf)) > 0) bos.write(buf, 0, n);
                out.put(normalize(entry.getName()), bos.toByteArray());
            }
            zin.closeEntry();
        }
        zin.close();
        return out;
    }

    private static Document parse(byte[] bytes) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setNamespaceAware(true);
        try { f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true); } catch (Exception ignored) {}
        return f.newDocumentBuilder().parse(new ByteArrayInputStream(bytes));
    }

    private static Map<String, String> parseRelationships(byte[] bytes) throws Exception {
        HashMap<String, String> out = new HashMap<>();
        Document d = parse(bytes);
        NodeList rels = d.getElementsByTagNameNS("*", "Relationship");
        for (int i = 0; i < rels.getLength(); i++) {
            Element e = (Element) rels.item(i);
            out.put(e.getAttribute("Id"), e.getAttribute("Target"));
        }
        return out;
    }

    private static List<String> readSharedStrings(byte[] bytes) throws Exception {
        ArrayList<String> out = new ArrayList<>();
        if (bytes == null) return out;
        Document d = parse(bytes);
        NodeList sis = d.getElementsByTagNameNS("*", "si");
        for (int i = 0; i < sis.getLength(); i++) {
            Element si = (Element) sis.item(i);
            NodeList ts = si.getElementsByTagNameNS("*", "t");
            StringBuilder s = new StringBuilder();
            for (int j = 0; j < ts.getLength(); j++) s.append(ts.item(j).getTextContent());
            out.add(s.toString());
        }
        return out;
    }

    private static List<List<String>> readSheet(byte[] bytes, List<String> shared) throws Exception {
        ArrayList<List<String>> out = new ArrayList<>();
        Document d = parse(bytes);
        NodeList rowNodes = d.getElementsByTagNameNS("*", "row");

        for (int i = 0; i < rowNodes.getLength(); i++) {
            Element row = (Element) rowNodes.item(i);
            NodeList cells = row.getElementsByTagNameNS("*", "c");
            TreeMap<Integer, String> values = new TreeMap<>();
            int max = -1;

            for (int j = 0; j < cells.getLength(); j++) {
                Element c = (Element) cells.item(j);
                String ref = c.getAttribute("r");
                int col = columnIndex(ref);
                max = Math.max(max, col);

                String type = c.getAttribute("t");
                String value = "";
                if ("inlineStr".equals(type)) {
                    NodeList ts = c.getElementsByTagNameNS("*", "t");
                    StringBuilder sb = new StringBuilder();
                    for (int k = 0; k < ts.getLength(); k++) sb.append(ts.item(k).getTextContent());
                    value = sb.toString();
                } else {
                    NodeList vs = c.getElementsByTagNameNS("*", "v");
                    if (vs.getLength() > 0) value = vs.item(0).getTextContent();
                    if ("s".equals(type) && !value.isEmpty()) {
                        try {
                            int idx = Integer.parseInt(value);
                            if (idx >= 0 && idx < shared.size()) value = shared.get(idx);
                        } catch (Exception ignored) {}
                    }
                }
                values.put(col, value);
            }

            ArrayList<String> rowOut = new ArrayList<>();
            for (int col = 0; col <= max; col++) rowOut.add(values.containsKey(col) ? values.get(col) : "");
            out.add(rowOut);
        }
        return out;
    }

    private static int columnIndex(String ref) {
        int result = 0;
        int i = 0;
        while (i < ref.length()) {
            char ch = ref.charAt(i);
            if (ch < 'A' || ch > 'Z') break;
            result = result * 26 + (ch - 'A' + 1);
            i++;
        }
        return Math.max(0, result - 1);
    }

    private static String normalize(String p) {
        ArrayDeque<String> s = new ArrayDeque<>();
        for (String part : p.split("/")) {
            if (part.equals("..")) { if (!s.isEmpty()) s.removeLast(); }
            else if (!part.equals(".") && !part.isEmpty()) s.addLast(part);
        }
        StringBuilder path = new StringBuilder();
        for (String part : s) { if (path.length() > 0) path.append('/'); path.append(part); }
        return path.toString();
    }
}
