package com.example.celldb;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.*;
import java.util.zip.*;

public class LayerWorkbookTest {
    private static void put(ZipOutputStream z,String path,String text)throws Exception {
        z.putNextEntry(new ZipEntry(path));z.write(text.getBytes("UTF-8"));z.closeEntry();
    }
    private static String row(String... values) {
        StringBuilder b=new StringBuilder("<row>");
        for(int i=0;i<values.length;i++)b.append("<c r='").append((char)('A'+i)).append("1' t='inlineStr'><is><t>").append(values[i]).append("</t></is></c>");
        return b.append("</row>").toString();
    }
    private byte[] book(boolean badSequence,boolean badCoordinates)throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(ZipOutputStream z=new ZipOutputStream(bytes)) {
            String[] names={"CN_F_Cable","CN_C_Cable","CN_C_ONU","CN_L_Pole_Manhole-CATV","TL_SPRD_RW","CN_M_User_Building","CN_L_Polemap_Bound"};
            StringBuilder wb=new StringBuilder("<workbook xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'><sheets>");
            StringBuilder rel=new StringBuilder("<Relationships>");
            for(int i=0;i<names.length;i++) {
                wb.append("<sheet name='").append(names[i]).append("' r:id='r").append(i).append("'/>");
                rel.append("<Relationship Id='r").append(i).append("' Target='worksheets/s").append(i).append(".xml'/>");
                String rows=row("ENTITY_TYPE","ENTITY_ID","BLOCK_NAME","SEQ","CAD_X","CAD_Y","경도","위도","길이","TEXT","ATTRIBUTES","XDATA");
                if(i<2)rows+=row(i==0?"ESSENPOLY":"LWPOLYLINE","same","",badSequence?"bad":"2","","","127.1",badCoordinates?"95":"35.2","10","","ESSEN_300=FC0001/144C | ESSEN_302=FC0001 | ESSEN_307=J1:J2","")
                    +row(i==0?"ESSENPOLY":"LWPOLYLINE","same","","1","","","127.0",badCoordinates?"95":"35.1","10","","ESSEN_300=FC0001/144C | ESSEN_302=FC0001 | ESSEN_307=J1:J2","");
                else rows+=row("INSERT","same","block","1","","","127.0",badCoordinates?"95":"35.1","","","ID=001","");
                // Excluded sheets deliberately have invalid XML: they must never be parsed.
                put(z,"xl/worksheets/s"+i+".xml",i>=4?"broken excluded XML":"<worksheet><sheetData>"+rows+"</sheetData></worksheet>");
            }
            put(z,"xl/workbook.xml",wb.append("</sheets></workbook>").toString());
            put(z,"xl/_rels/workbook.xml.rels",rel.append("</Relationships>").toString());
        }
        return bytes.toByteArray();
    }
    @Test public void importsLayersKeepsVerticesAndSkipsTerrain()throws Exception {
        List<CadRecord> rows=XlsxCadImporter.read(new ByteArrayInputStream(book(false,false)));
        assertEquals(6,rows.size());
        Set<String> keys=new HashSet<>();for(CadRecord r:rows)assertTrue(keys.add(r.stableKey()));
        assertEquals("FIBER",rows.get(0).category);assertEquals(2,rows.get(0).sequence);
        assertEquals("FC0001/144C",rows.get(0).name);assertEquals("FC0001",rows.get(0).subtype);
        assertEquals("J1:J2",rows.get(0).fields.get("연결정보"));
        assertEquals(1,rows.get(1).sequence);assertEquals("COAX",rows.get(2).category);
        assertEquals("CN_C_ONU",rows.get(4).layer);assertEquals("FACILITY",rows.get(5).category);
        assertEquals("POLE",LayerGroups.defaultGroup(rows.get(5).layer,rows.get(5).category));
    }
    @Test public void rejectsBadVertexSequenceAndAllInvalidCoordinates()throws Exception {
        for(boolean badSequence:new boolean[]{true,false})try {
            XlsxCadImporter.read(new ByteArrayInputStream(book(badSequence,!badSequence)));
            fail("Invalid export accepted");
        }catch(IOException expected){assertTrue(expected.getMessage().contains(badSequence?"순번":"위도"));}
    }
    @Test public void groupsEquipmentAndCableTogetherAndNeverIncludesTerrain() {
        assertEquals("FIBER",LayerGroups.defaultGroup("CN_F_Closure","EQUIPMENT"));
        assertEquals("COAX",LayerGroups.defaultGroup("CN_C_ONU","EQUIPMENT"));
        assertEquals("POLE",LayerGroups.defaultGroup("CN_L_Pole_Handhole-TEL","FACILITY"));
        assertFalse(LayerGroups.importSheet("TL_SPRD_RW"));
        assertFalse(LayerGroups.importSheet("CN_M_User_Building"));
        assertFalse(LayerGroups.importSheet("CN_L_Polemap_Bound"));
    }
}
