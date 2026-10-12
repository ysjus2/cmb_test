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
}
