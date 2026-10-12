package com.example.celldb;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/**
 * Persistent regional map cache.
 * Stores server CAD rows plus covered query centers.
 * Cache validity is controlled by per-group server version strings.
 */
final class ServerMapCache {
    private final File root;

    ServerMapCache(Context context) {
        root = new File(context.getFilesDir(), "server_map_cache");
        if (!root.exists()) root.mkdirs();
    }

    private static String safe(String text) {
        return String.valueOf(text == null ? "" : text)
                .replaceAll("[^A-Za-z0-9_.-]", "_");
    }

    private File file(String region) {
        return new File(root, safe(region) + ".json");
    }

    static final class State {
        final LinkedHashMap<String,String> versions = new LinkedHashMap<>();
        final ArrayList<CadRecord> records = new ArrayList<>();
        final ArrayList<Coverage> coverage = new ArrayList<>();
    }

    static final class Coverage {
        double lat,lng;
        int radius;
        String filter;
        String versionKey;

        JSONObject json() throws Exception {
            return new JSONObject()
                    .put("lat",lat).put("lng",lng).put("radius",radius)
                    .put("filter",filter).put("versionKey",versionKey);
        }

        static Coverage from(JSONObject o) {
            Coverage c=new Coverage();
            c.lat=o.optDouble("lat",Double.NaN);
            c.lng=o.optDouble("lng",Double.NaN);
            c.radius=o.optInt("radius",0);
            c.filter=o.optString("filter","");
            c.versionKey=o.optString("versionKey","");
            return c;
        }
    }

    State load(String region) {
        State state=new State();
        File f=file(region);
        if(!f.isFile())return state;
        try {
            byte[] bytes=new byte[(int)Math.min(Integer.MAX_VALUE,f.length())];
            try(InputStream in=new FileInputStream(f)){
                int off=0,n;
                while(off<bytes.length&&(n=in.read(bytes,off,bytes.length-off))>0)off+=n;
                if(off!=bytes.length)return new State();
            }
            JSONObject root=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
            JSONObject versions=root.optJSONObject("versions");
            if(versions!=null){
                Iterator<String> keys=versions.keys();
                while(keys.hasNext()){String k=keys.next();state.versions.put(k,versions.optString(k,""));}
            }
            JSONArray rows=root.optJSONArray("records");
            if(rows!=null)for(int i=0;i<rows.length();i++){
                JSONObject o=rows.optJSONObject(i);
                if(o!=null)state.records.add(CadRecord.fromJson(o));
            }
            JSONArray cover=root.optJSONArray("coverage");
            if(cover!=null)for(int i=0;i<cover.length();i++){
                JSONObject o=cover.optJSONObject(i);
                if(o!=null)state.coverage.add(Coverage.from(o));
            }
        } catch(Exception ignored) {
            return new State();
        }
        return state;
    }

    void save(String region,State state) {
        try {
            JSONObject rootJson=new JSONObject();
            JSONObject versions=new JSONObject();
            for(Map.Entry<String,String> e:state.versions.entrySet())versions.put(e.getKey(),e.getValue());
            rootJson.put("versions",versions);

            JSONArray rows=new JSONArray();
            for(CadRecord r:state.records)rows.put(r.toJson());
            rootJson.put("records",rows);

            JSONArray coverage=new JSONArray();
            for(Coverage c:state.coverage)coverage.put(c.json());
            rootJson.put("coverage",coverage);

            File out=file(region),tmp=new File(out.getParentFile(),out.getName()+".tmp");
            try(OutputStream stream=new FileOutputStream(tmp)){
                stream.write(rootJson.toString().getBytes(StandardCharsets.UTF_8));
            }
            if(out.exists()&&!out.delete())throw new IOException("old cache delete failed");
            if(!tmp.renameTo(out))throw new IOException("cache rename failed");
        } catch(Exception ignored) {}
    }

    static String group(CadRecord r) {
        String g=r.fields.get("__serverGroup");
        if(g!=null&&!g.trim().isEmpty())return g.trim().toUpperCase(Locale.ROOT);
        if("FIBER".equals(r.category))return "FIBER";
        if("COAX".equals(r.category))return "COAX";
        if("FACILITY".equals(r.category))return "POLE";
        return "EQUIPMENT";
    }

    static String versionKey(Map<String,String> versions,String filter) {
        ArrayList<String> keys=new ArrayList<>(versions.keySet());
        Collections.sort(keys);
        StringBuilder b=new StringBuilder(filter==null?"":filter);
        for(String k:keys)b.append('|').append(k).append('=').append(versions.get(k));
        return b.toString();
    }

    private static double distanceMeters(double lat1,double lng1,double lat2,double lng2) {
        double r=6371000.0;
        double p1=Math.toRadians(lat1),p2=Math.toRadians(lat2);
        double dp=Math.toRadians(lat2-lat1),dl=Math.toRadians(lng2-lng1);
        double a=Math.sin(dp/2)*Math.sin(dp/2)
                +Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);
        return r*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
    }

    static boolean covered(State state,MapPoint center,int radius,String filter,String versionKey) {
        for(Coverage c:state.coverage){
            if(c.radius<radius)continue;
            if(!Objects.equals(c.filter,filter))continue;
            if(!Objects.equals(c.versionKey,versionKey))continue;
            if(new MapPoint(c.lat,c.lng).distanceToAsDouble(center)<=Math.max(20,radius/3.0))return true;
        }
        return false;
    }

    static void merge(State state,ArrayList<CadRecord> rows,MapPoint center,int radius,String filter,String versionKey) {
        // 새 서버 응답을 정상 수신한 뒤에만 해당 조회 범위/레이어의 오래된 캐시를 교체한다.
        // 그 전까지는 applyVersions()가 기존 records를 유지하므로 화면이 먼저 보인다.
        HashSet<String> selectedLayers=new HashSet<>();
        if(filter!=null&&!filter.trim().isEmpty())for(String item:filter.split(",")){
            String value=item.trim();
            if(!value.isEmpty())selectedLayers.add(value);
        }
        final double replaceRadius=Math.max(radius*1.20,radius+50.0);
        state.records.removeIf(r->
                r.hasCoordinates()
                && (selectedLayers.isEmpty()||selectedLayers.contains(r.layer))
                && distanceMeters(r.latitude,r.longitude,center.getLatitude(),center.getLongitude())<=replaceRadius
        );

        LinkedHashMap<String,CadRecord> merged=new LinkedHashMap<>();
        for(CadRecord r:state.records)merged.put(r.stableKey(),r);
        for(CadRecord r:rows)merged.put(r.stableKey(),r);
        state.records.clear();
        state.records.addAll(merged.values());

        Coverage c=new Coverage();
        c.lat=center.getLatitude();c.lng=center.getLongitude();c.radius=radius;
        c.filter=filter;c.versionKey=versionKey;
        state.coverage.add(c);

        // Bound metadata growth; record cache remains revision-controlled.
        while(state.coverage.size()>200)state.coverage.remove(0);
    }

    static boolean applyVersions(State state,Map<String,String> serverVersions) {
        HashSet<String> changed=new HashSet<>();
        for(Map.Entry<String,String> e:serverVersions.entrySet()){
            String old=state.versions.get(e.getKey());
            if(old!=null&&!old.equals(e.getValue()))changed.add(e.getKey());
        }
        if(!changed.isEmpty()){
            // Windows Viewer와 동일하게 기존 캐시를 먼저 유지한다.
            // Revision이 바뀌면 coverage만 무효화하고, 새 범위를 성공적으로
            // 내려받아 저장한 뒤 해당 stableKey가 새 데이터로 교체되게 한다.
            state.coverage.clear();
        }
        state.versions.clear();
        state.versions.putAll(serverVersions);
        return !changed.isEmpty();
    }

    static ArrayList<CadRecord> around(State state,MapPoint center,double meters) {
        ArrayList<CadRecord> rows=new ArrayList<>();
        for(CadRecord r:state.records){
            if(!r.hasCoordinates())continue;
            if(new MapPoint(r.latitude,r.longitude).distanceToAsDouble(center)<=meters)rows.add(r);
        }
        return rows;
    }

    void clearRegion(String region) {
        File f=file(region);
        if(f.exists())f.delete();
    }
}
