package com.example.celldb;
import org.junit.Test;
import static org.junit.Assert.*;

public class CadObjectInfoTest {
    @Test public void extractsEntityPoleWithoutConfusingHandlesOrCellNumbers() {
        CadRecord r=new CadRecord();r.id="1225AA";
        r.fields.put("ATTRIBUTES","ID=A05 | MODEL=AMP");
        r.fields.put("XDATA","1225AB | 9901G433 | GN7501");
        assertEquals("9901G433",CadObjectInfo.pole(r));
        assertEquals("",CadObjectInfo.address(r));
        r.fields.put("XDATA","1225AB | GN7501 | 4671025022");
        assertEquals("",CadObjectInfo.pole(r));
    }
    @Test public void explicitPropertiesTakePriorityAndKeepAddress() {
        CadRecord r=new CadRecord();
        r.fields.put("전주번호","0000X000");
        r.fields.put("ATTRIBUTES","POLE_ID=9901G433 | ADDRESS=테스트 주소 | MODEL=M1");
        assertEquals("0000X000",CadObjectInfo.pole(r));
        assertEquals("테스트 주소",CadObjectInfo.address(r));
        assertEquals("M1",CadObjectInfo.attributes(r).get("MODEL"));
    }
}
