package com.example.celldb;

import static org.junit.Assert.*;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import org.junit.Test;

public class MobileWindowsParityTest {
    @Test public void cmbCodeFirstSymbolsMatchWindowsPolicy() {
        assertEquals("SPL2", CmbSymbolType.fromLayer("CN_C_Passive 2SP-B"));
        assertEquals("SPL3", CmbSymbolType.fromLayer("CN_C_Passive 3SP-B"));
        assertEquals("SPL_DC", CmbSymbolType.fromLayer("CN_C_DC DC-12"));
        assertEquals("PI", CmbSymbolType.fromLayer("CN_C_PI PI"));
        assertEquals("AMP", CmbSymbolType.fromLayer("CN_C_AMP AMP"));
        assertEquals("TAP", CmbSymbolType.fromLayer("CN_C_TAP TAP"));
        assertEquals("ONU", CmbSymbolType.fromLayer("CN_C_ONU ONU"));
        assertEquals("HIDDEN", CmbSymbolType.fromLayer("CN_C_CONNECTOR CONNECTOR"));
        assertEquals("HIDDEN", CmbSymbolType.fromLayer("CN_C_Passive-ANNO"));
    }

    @Test public void revisionChangeKeepsRecordsButInvalidatesCoverage() {
        ServerMapCache.State state=new ServerMapCache.State();
        CadRecord record=new CadRecord();
        record.category="FIBER"; record.id="old"; record.layer="CN_F_CABLE";
        record.latitude=35.0; record.longitude=126.0;
        state.records.add(record);

        ServerMapCache.Coverage c=new ServerMapCache.Coverage();
        c.lat=35.0;c.lng=126.0;c.radius=500;c.filter="CN_F_CABLE";c.versionKey="old";
        state.coverage.add(c);
        state.versions.put("FIBER","1");

        LinkedHashMap<String,String> server=new LinkedHashMap<>();
        server.put("FIBER","2");

        assertTrue(ServerMapCache.applyVersions(state,server));
        assertEquals(1,state.records.size());
        assertTrue(state.coverage.isEmpty());
    }

    @Test public void successfulFetchReplacesCurrentArea() {
        ServerMapCache.State state=new ServerMapCache.State();

        CadRecord old=new CadRecord();
        old.category="FIBER"; old.id="old"; old.layer="CN_F_CABLE";
        old.latitude=35.0; old.longitude=126.0;
        state.records.add(old);

        CadRecord fresh=new CadRecord();
        fresh.category="FIBER"; fresh.id="new"; fresh.layer="CN_F_CABLE";
        fresh.latitude=35.0001; fresh.longitude=126.0001;

        ArrayList<CadRecord> rows=new ArrayList<>();
        rows.add(fresh);
        ServerMapCache.merge(state,rows,new MapPoint(35.0,126.0),500,"CN_F_CABLE","v2");

        assertEquals(1,state.records.size());
        assertEquals("new",state.records.get(0).id);
    }

    @Test public void fiberClosureIsL3AndOtherFiberDevicesAreL2() {
        CadRecord closure=new CadRecord();
        closure.category="EQUIPMENT";
        closure.fields.put("__serverGroup","FIBER");
        closure.fields.put("__symbol","FIBER_CLOSURE:0");

        CadRecord terminal=new CadRecord();
        terminal.category="EQUIPMENT";
        terminal.fields.put("__serverGroup","FIBER");
        terminal.fields.put("__symbol","FIBER_TERMINAL:0");

        assertTrue(DrawingLevel.recordVisible("L3",closure));
        assertFalse(DrawingLevel.recordVisible("L3",terminal));
        assertTrue(DrawingLevel.recordVisible("L2",terminal));
    }

    @Test public void fullFiberReplacementKeepsNonFiberCache() {
        ServerMapCache.State state=new ServerMapCache.State();

        CadRecord oldFiber=new CadRecord();
        oldFiber.category="FIBER";oldFiber.id="old-fiber";
        oldFiber.fields.put("__serverGroup","FIBER");
        oldFiber.latitude=35.0;oldFiber.longitude=126.0;

        CadRecord coax=new CadRecord();
        coax.category="COAX";coax.id="coax";
        coax.fields.put("__serverGroup","COAX");
        coax.latitude=35.0;coax.longitude=126.0;

        state.records.add(oldFiber);
        state.records.add(coax);

        CadRecord freshFiber=new CadRecord();
        freshFiber.category="FIBER";freshFiber.id="fresh-fiber";
        freshFiber.fields.put("__serverGroup","FIBER");
        freshFiber.latitude=35.1;freshFiber.longitude=126.1;

        ArrayList<CadRecord> rows=new ArrayList<>();
        rows.add(freshFiber);
        ServerMapCache.replaceGroup(state,rows,"FIBER");

        assertEquals(2,state.records.size());
        assertTrue(state.records.stream().anyMatch(r->"coax".equals(r.id)));
        assertTrue(state.records.stream().anyMatch(r->"fresh-fiber".equals(r.id)));
        assertFalse(state.records.stream().anyMatch(r->"old-fiber".equals(r.id)));
    }

    @Test public void minimalPoleNumberIsExposedToAndroidDetails() throws Exception {
        org.json.JSONObject feature=new org.json.JSONObject()
                .put("geometry",new org.json.JSONObject()
                        .put("type","Point")
                        .put("coordinates",new org.json.JSONArray().put(126.8).put(35.1)))
                .put("properties",new org.json.JSONObject()
                        .put("group_id","POLE")
                        .put("entity_id","P1")
                        .put("layer","CN_L_Pole")
                        .put("entity_type","INSERT")
                        .put("block_name","")
                        .put("attributes",new org.json.JSONObject().put("_cmb_pole_no","7792A141")));

        CadRecord record=ServerCadParser.feature("CMB_GN_HP",feature).get(0);
        assertEquals("7792A141",record.fields.get("전주번호"));
        assertEquals("7792A141",CadObjectInfo.pole(record));
    }

}
