package com.example.celldb.network;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.zip.*;
import com.example.celldb.network.NetworkModels.NetworkData;

public class NetworkExcelRepositoryTest {
    private String cell(String ref, String value) {
        return "<c r='" + ref + "' t='inlineStr'><is><t>" + value + "</t></is></c>";
    }
    private String row(int index, String... values) {
        StringBuilder out = new StringBuilder("<row r='" + index + "'>");
        for (int i=0; i<values.length; i++) out.append(cell("" + (char)('A'+i) + index, values[i]));
        return out.append("</row>").toString();
    }
    private byte[] workbook(boolean missingSheet, boolean badHeader) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(out)) {
            String[] names = {"CELL", "FACILITY", "EQUIPMENT", "FIBER", "COAX"};
            StringBuilder wb = new StringBuilder("<workbook xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets>");
            StringBuilder rel = new StringBuilder("<Relationships>");
            for (int i=0;i<(missingSheet ? 4 : 5);i++) {
                wb.append("<sheet name='").append(names[i]).append("' r:id='r").append(i).append("'/>");
                rel.append("<Relationship Id='r").append(i).append("' Target='/xl/worksheets/s").append(i).append(".xml'/>");
                String rows;
                if (i == 0) rows = row(1,"셀번호","셀명",badHeader ? "X" : "경도","위도")
                        + row(2,"0001","D1","126.82","35.17") + row(3,"bad","bad","126","95") + row(4,"","","","");
                else if (i == 1) rows = row(1,"시설ID","구분","경도","위도") + row(2,"P1","전주","126.83","35.18");
                else if (i == 2) rows = row(1,"장비ID","구분","경도","위도") + row(2,"E1","ONU","126.84","35.19");
                else rows = row(1,"선로ID","순번","경도","위도") + row(2,"L1","2","126.83","35.18")
                        + row(3,"L1","1","126.82","35.17") + row(4,"single","1","126.9","35.2");
                put(zip,"xl/worksheets/s"+i+".xml","<worksheet><sheetData>"+rows+"</sheetData></worksheet>");
            }
            put(zip,"xl/workbook.xml",wb.append("</sheets></workbook>").toString());
            put(zip,"xl/_rels/workbook.xml.rels",rel.append("</Relationships>").toString());
        }
        return out.toByteArray();
    }
    private void put(ZipOutputStream zip, String name, String text) throws Exception {
        zip.putNextEntry(new ZipEntry(name)); zip.write(text.getBytes("UTF-8")); zip.closeEntry();
    }
    @Test public void loadsCategoriesSortsVerticesAndRejectsInvalidCoordinates() throws Exception {
        NetworkData data = NetworkExcelRepository.read(new ByteArrayInputStream(workbook(false,false)));
        assertEquals(1,data.cells.size()); assertEquals("0001",data.cells.get(0).id);
        assertEquals(1,data.facilities.size()); assertEquals(1,data.equipment.size());
        assertEquals(1,data.fiber.size()); assertEquals(1,data.coax.size());
        assertEquals(126.82,data.fiber.get(0).points.get(0).lon,0.00001);
        assertEquals(1,data.skippedRows);
    }
    @Test public void rejectsWrongWorkbookInsteadOfClearingExistingData() throws Exception {
        for (boolean missing : new boolean[]{true,false}) {
            try {
                NetworkExcelRepository.read(new ByteArrayInputStream(workbook(missing,!missing)));
                fail("Invalid workbook accepted");
            } catch (IOException expected) { assertTrue(expected.getMessage().contains(missing ? "COAX" : "경도")); }
        }
    }
    @Test public void readsSparseCellsAndRichSharedStrings() throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        try (ZipOutputStream zip = new ZipOutputStream(out)) {
            put(zip,"xl/workbook.xml","<workbook xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheet name='CELL' r:id='r1'/></workbook>");
            put(zip,"xl/_rels/workbook.xml.rels","<Relationships><Relationship Id='r1' Target='worksheets/s.xml'/></Relationships>");
            put(zip,"xl/sharedStrings.xml","<sst><si><r><t>D</t></r><r><t>1</t></r></si></sst>");
            put(zip,"xl/worksheets/s.xml","<worksheet><row><c r='C1' t='s'><v>0</v></c><c r='E1'><v>126.82</v></c></row></worksheet>");
        }
        java.util.List<String> row = SimpleXlsxReader.read(new ByteArrayInputStream(out.toByteArray())).get("CELL").rows.get(0);
        assertEquals(5,row.size()); assertEquals("",row.get(1)); assertEquals("D1",row.get(2)); assertEquals("126.82",row.get(4));
    }
}
