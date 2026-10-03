package com.example.celldb;

import org.junit.Test;
import static org.junit.Assert.*;
import java.io.*;
import java.util.*;
import com.example.celldb.network.NetworkExcelRepositoryTest;

public class XlsxCadImporterTest {
    @Test public void keepsCadIdsAndVertexSequenceForEditing() throws Exception {
        ArrayList<CadRecord> records=XlsxCadImporter.read(new ByteArrayInputStream(new NetworkExcelRepositoryTest().workbook(false,false)));
        assertEquals(10,records.size());
        CadRecord cell=records.get(0);
        assertEquals("0001",cell.id); assertEquals("D1",cell.name);
        assertEquals("126.82",cell.fields.get("경도"));
        assertTrue(cell.hasCoordinates()); assertFalse(records.get(1).hasCoordinates());
        List<CadRecord> fiber=new ArrayList<>();
        for(CadRecord r:records) if(r.category.equals("FIBER")) fiber.add(r);
        assertEquals(3,fiber.size());
        assertEquals(2,fiber.get(0).sequence); assertEquals(1,fiber.get(1).sequence);
        assertNotEquals(fiber.get(0).stableKey(),fiber.get(1).stableKey());
    }
    @Test public void refusesUnrelatedExcelBeforeDbReplacement() throws Exception {
        try {
            XlsxCadImporter.read(new ByteArrayInputStream(new NetworkExcelRepositoryTest().workbook(true,false)));
            fail("Missing category accepted");
        } catch(IOException expected) { assertTrue(expected.getMessage().contains("COAX")); }
    }
}
