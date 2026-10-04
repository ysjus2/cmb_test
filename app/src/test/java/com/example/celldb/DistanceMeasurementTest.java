package com.example.celldb;
import org.junit.Test;
import static org.junit.Assert.*;

public class DistanceMeasurementTest {
    @Test public void finishRetainsOnlyClickedVerticesAndCumulativeDistance(){
        DistanceMeasurement m=new DistanceMeasurement();m.start();m.add(0,0);m.add(0,0.001);m.add(0.001,0.001);
        DistanceMeasurement.Line line=m.finish();
        assertFalse(m.active());assertEquals(3,line.points.size());assertEquals(222.39,line.meters,0.1);
        m.add(0.01,0.01);assertEquals(3,line.points.size());assertNull(m.finish());
        assertEquals(1,m.lines().size());
    }
    @Test public void deletesOnlyChosenCompletedMeasurement(){
        DistanceMeasurement m=new DistanceMeasurement();m.start();m.add(35,127);m.add(35.001,127);
        long first=m.finish().id;m.start();m.add(35,127);m.add(35,127.001);long second=m.finish().id;
        assertFalse(m.delete(999));assertTrue(m.delete(first));assertFalse(m.delete(first));
        assertEquals(1,m.lines().size());assertEquals(second,m.lines().get(0).id);
    }
    @Test public void noLineForSinglePointOrRepeatedFinish(){
        DistanceMeasurement m=new DistanceMeasurement();m.start();m.add(35,127);
        assertNull(m.finish());assertNull(m.finish());assertTrue(m.lines().isEmpty());
    }
}
