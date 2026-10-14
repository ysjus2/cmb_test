package com.example.celldb;

import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import java.util.ArrayList;
import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class ServerIntegrationTest {
    @Test public void preservesAuthoredGeographicLayoutButIgnoresOtherSources() throws Exception {
        JSONObject feature=new JSONObject(point("device",126.01));
        JSONObject layout=new JSONObject("{\"source\":\"cmb-authored-v1\",\"filled\":false,\"ring\":[[126,35],[126.01,35],[126,35.01],[126,35]],\"links\":[]}");
        feature.getJSONObject("properties").put("cmb_layout",layout);
        CadRecord record=ServerCadParser.feature("hp",feature).get(0);
        assertEquals(layout.toString(),record.fields.get("__cmbLayout"));
        layout.put("source","original-cad");
        assertNull(ServerCadParser.feature("hp",feature).get(0).fields.get("__cmbLayout"));
    }
    @Test public void ignoresOriginalDxfSymbolAndUsesCmbType() throws Exception {
        JSONObject f=new JSONObject(point("device",126.01));
        f.getJSONObject("properties").put("symbol",new JSONObject("{\"block\":\"ONU\",\"paths\":[[[0,0],[1,0],[0,1],[0,0]]]}"));
        CadRecord record=ServerCadParser.feature("hp",f).get(0);
        assertEquals("POLE:0.0",record.fields.get("__symbol"));
    }
    private static String point(String entity,double lon){return "{\"type\":\"Feature\",\"id\":\""+entity+"\",\"properties\":{\"layer\":\"CN_L_Pole_Pole\",\"entity_id\":\""+entity+"\",\"group_id\":\"POLE\",\"name\":\"Pole\"},\"geometry\":{\"type\":\"Point\",\"coordinates\":["+lon+",35.01]}}";}

    @Test public void parsesCablesWithoutLosingVertexOrderOrIdentity() throws Exception {
        JSONObject feature=new JSONObject("{\"properties\":{\"layer\":\"CN_F_Cable_FOC\",\"entity_id\":\"A\",\"group_id\":\"FIBER\",\"name\":\"Cable\"},\"geometry\":{\"type\":\"LineString\",\"coordinates\":[[126,35],[126.1,35.1],[126.2,35.2]]}}");
        ArrayList<CadRecord> records=ServerCadParser.feature("hp-main",feature);
        assertEquals(3,records.size());assertEquals("FIBER",records.get(0).category);
        assertEquals(records.get(0).id,records.get(2).id);assertEquals(2,records.get(2).sequence);
        assertEquals(126.1,records.get(1).longitude,0);assertEquals("SERVER",records.get(0).source);
        assertNotEquals(records.get(0).id,ServerCadParser.feature("other",feature).get(0).id);
    }

    @Test public void rejectsBadServerCoordinatesAndInsecureUrls() throws Exception {
        try{ServerCadParser.feature("hp",new JSONObject(point("bad",999)));fail();}catch(Exception expected){}
        assertEquals("https://192.168.246.54:8443",ServerApiClient.BASE_URL);
        assertTrue(new MapViewport(126,35,126.1,35.1).queryable());
        assertFalse(new MapViewport(126,35,127,36).queryable());
        assertFalse(new MapViewport(Double.NaN,35,126,36).queryable());
    }

    @Test public void refreshesTokenAndFetchesAllPinnedPages() throws Exception {
        MockWebServer mock=new MockWebServer();
        mock.enqueue(new MockResponse().setBody("{\"access_token\":\"old\",\"refresh_token\":\"refresh-old\"}"));
        mock.enqueue(new MockResponse().setResponseCode(401).setBody("{}"));
        mock.enqueue(new MockResponse().setBody("{\"access_token\":\"new\",\"refresh_token\":\"refresh-new\"}"));
        mock.enqueue(new MockResponse().setBody("{\"version\":\"v1\",\"features\":["+point("A",126.01)+"],\"next_cursor\":\"cursor\"}"));
        mock.enqueue(new MockResponse().setBody("{\"version\":\"v1\",\"features\":["+point("B",126.02)+"],\"next_cursor\":null}"));
        mock.start();
        try{
            ServerApiClient client=new ServerApiClient(url -> {
                assertEquals("https",url.getProtocol());
                assertEquals("192.168.246.54",url.getHost());
                assertEquals(8443,url.getPort());
                return (java.net.HttpURLConnection)mock.url(url.getFile()).url().openConnection();
            });
            client.login("alice","test-password");
            ArrayList<CadRecord> rows=client.objects("hp-main",new MapViewport(126,35,126.1,35.1),"CN_L_Pole_Pole");
            assertEquals(2,rows.size());assertEquals(5,mock.getRequestCount());
            assertEquals("/auth/login",mock.takeRequest().getPath());
            assertEquals("Bearer old",mock.takeRequest().getHeader("Authorization"));
            assertEquals("/auth/refresh",mock.takeRequest().getPath());
            assertEquals("Bearer new",mock.takeRequest().getHeader("Authorization"));
            RecordedRequest page=mock.takeRequest();assertTrue(page.getPath().contains("version=v1"));assertTrue(page.getPath().contains("after=cursor"));
            assertEquals("v1",rows.get(0).fields.get("__serverVersion"));client.clear();
        }finally{mock.shutdown();}
    }
}
