package com.example.celldb;
import org.junit.Test;
import static org.junit.Assert.*;

public class DrawingLevelTest {
    @Test public void keepsLegacyServerDetailLevels(){
        assertEquals("overview",DrawingLevel.forViewport(new MapViewport(126,35,126.1,35.1)));
        assertEquals("network",DrawingLevel.forViewport(new MapViewport(126,35,126.03,35.03)));
        assertEquals("facilities",DrawingLevel.forViewport(new MapViewport(126,35,126.005,35.005)));
    }

    @Test public void mirrorsWindowsGroupVisibility(){
        assertTrue(DrawingLevel.groupVisible("L6","FIBER"));
        assertFalse(DrawingLevel.groupVisible("L6","COAX"));
        assertTrue(DrawingLevel.groupVisible("L5","COAX"));
        assertFalse(DrawingLevel.groupVisible("L4","POLE"));
        assertTrue(DrawingLevel.groupVisible("L3","POLE"));
        assertTrue(DrawingLevel.groupVisible("L3","CONDUIT"));
    }

    @Test public void windowsCellBoundaryAndNumberGates(){
        CadRecord boundary=new CadRecord();boundary.category="COAX";boundary.layer="CN_C_CELLBOUND_MAIN";
        CadRecord number=new CadRecord();number.category="EQUIPMENT";number.layer="CN_C_CELLNO";
        assertTrue(DrawingLevel.recordVisible("L5",boundary));
        assertFalse(DrawingLevel.recordVisible("L5",number));
        assertTrue(DrawingLevel.recordVisible("L4",number));
    }

    @Test public void fiberCablePersistsButFiberDeviceStartsAtL3(){
        CadRecord cable=new CadRecord();cable.category="FIBER";cable.layer="CN_F_CABLE";
        CadRecord device=new CadRecord();device.category="EQUIPMENT";device.layer="CN_F_TERMINAL";
        device.fields.put("__serverGroup","FIBER");
        device.fields.put("__symbol","FIBER_L2:0");
        assertTrue(DrawingLevel.recordVisible("L8",cable));
        assertFalse(DrawingLevel.recordVisible("L4",device));
        assertTrue(DrawingLevel.recordVisible("L3",device));
    }
}
