package com.example.celldb;
import org.junit.Test;
import static org.junit.Assert.*;
public class DrawingLevelTest {
    @Test public void addsInformationAsViewportNarrows(){
        assertEquals("overview",DrawingLevel.forViewport(new MapViewport(126,35,126.1,35.1)));
        assertEquals("network",DrawingLevel.forViewport(new MapViewport(126,35,126.03,35.03)));
        assertEquals("facilities",DrawingLevel.forViewport(new MapViewport(126,35,126.005,35.005)));
        assertFalse(DrawingLevel.groupVisible("overview","COAX"));
        assertFalse(DrawingLevel.groupVisible("network","POLE"));
        assertTrue(DrawingLevel.groupVisible("facilities","POLE"));
    }
    @Test public void hidesBlockSymbolsUntilFacilityLevel(){
        CadRecord r=new CadRecord();r.category="EQUIPMENT";
        assertFalse(DrawingLevel.recordVisible("overview",r));
        assertFalse(DrawingLevel.recordVisible("network",r));
        assertTrue(DrawingLevel.recordVisible("facilities",r));
    }
}
