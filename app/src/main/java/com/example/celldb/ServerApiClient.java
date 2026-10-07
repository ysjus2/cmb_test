package com.example.celldb;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import org.json.*;

/** Session tokens and server CAD rows are kept in memory only. */
final class ServerApiClient {
    static final class ApiError extends IOException {
        final int status;
        ApiError(int status,String message){super(message);this.status=status;}
    }
    static final String BASE_URL="https://192.168.246.54:8443";
    interface ConnectionFactory { HttpURLConnection open(URL url) throws IOException; }
    private final ConnectionFactory connections;
    private volatile String access="",refresh="";
    private volatile HttpURLConnection active;
    ServerApiClient() { this(url -> (HttpURLConnection)url.openConnection()); }
    // Transport injection for JVM tests; the app always uses the default HTTPS transport.
    ServerApiClient(ConnectionFactory connections) { this.connections=connections; }
    void cancel(){HttpURLConnection connection=active;if(connection!=null)connection.disconnect();}
    void clear(){access="";refresh="";cancel();}
    private Object request(String path,JSONObject body,boolean authenticated,boolean retry) throws Exception {
        if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();
        HttpURLConnection connection=connections.open(new URL(BASE_URL+path));
        active=connection;
        try {
            connection.setConnectTimeout(8000);connection.setReadTimeout(12000);
            connection.setInstanceFollowRedirects(false);connection.setUseCaches(false);
            connection.setRequestProperty("Accept","application/json");
            if(authenticated)connection.setRequestProperty("Authorization","Bearer "+access);
            if(body!=null){
                connection.setRequestMethod("POST");connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
                try(OutputStream out=connection.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}
            }
            int status=connection.getResponseCode();
            if(status==401&&authenticated&&retry&&!refresh.isEmpty()){
                connection.disconnect();
                try{JSONObject tokens=(JSONObject)request("/auth/refresh",new JSONObject().put("refresh_token",refresh),false,false);setTokens(tokens);}
                catch(Exception error){clear();throw new ApiError(401,"로그인이 만료됐습니다. 다시 로그인하세요.");}
                return request(path,body,true,false);
            }
            if(status<200||status>=300){
                String message=status==401?"계정 또는 비밀번호를 확인하세요.":status==403?"이 지역에 접근 권한이 없습니다.":status==409?"서버 자료가 갱신됐습니다.":status==429?"로그인 시도가 많습니다. 15분 후 다시 시도하세요.":"서버 응답 오류 ("+status+")";
                throw new ApiError(status,message);
            }
            if(status==204)return new JSONObject();
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            try(InputStream in=connection.getInputStream()){
                byte[] buffer=new byte[8192];int n;
                while((n=in.read(buffer))!=-1){
                    if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();
                    out.write(buffer,0,n);if(out.size()>3*1024*1024)throw new IOException("서버 응답이 너무 큽니다.");
                }
            }
            return new JSONTokener(out.toString("UTF-8")).nextValue();
        } finally {connection.disconnect();if(active==connection)active=null;}
    }
    private void setTokens(JSONObject tokens) throws Exception {access=tokens.getString("access_token");refresh=tokens.getString("refresh_token");}
    void login(String username,String password) throws Exception {
        setTokens((JSONObject)request("/auth/login",new JSONObject().put("username",username).put("password",password),false,false));
    }
    void logout(){try{request("/auth/logout",new JSONObject(),true,true);}catch(Exception ignored){}finally{clear();}}
    static String encoded(String text)throws Exception{return URLEncoder.encode(text,"UTF-8");}
    JSONArray regions()throws Exception{return (JSONArray)request("/regions",null,true,true);}
    JSONArray datasets(String region)throws Exception{return (JSONArray)request("/regions/"+encoded(region)+"/datasets",null,true,true);}
    JSONObject layers(String dataset)throws Exception{return (JSONObject)request("/datasets/"+encoded(dataset)+"/layers",null,true,true);}
    JSONObject detail(String dataset,String layer,String entity,String version)throws Exception {
        return (JSONObject)request("/datasets/"+encoded(dataset)+"/object?layer="+encoded(layer)+"&entity_id="+encoded(entity)+"&version="+encoded(version),null,true,true);
    }
    ArrayList<CadRecord> objects(String dataset,MapViewport viewport,String layerFilter) throws Exception {
        for(int attempt=0;attempt<2;attempt++){
            try{return fetchPages(dataset,viewport,layerFilter);}catch(ApiError e){if(e.status!=409||attempt==1)throw e;}
        }
        throw new IOException("서버 자료를 다시 조회하세요.");
    }
    private ArrayList<CadRecord> fetchPages(String dataset,MapViewport viewport,String filter)throws Exception {
        ArrayList<CadRecord> rows=new ArrayList<>();HashSet<String> seen=new HashSet<>();
        String cursor="",version="";
        int count=0;
        do {
            String path="/datasets/"+encoded(dataset)+"/objects?bbox="+encoded(viewport.bbox())+"&limit=200";
            path+="&detail_level="+DrawingLevel.forViewport(viewport);
            if(!filter.isEmpty())path+="&layers="+encoded(filter);
            if(!cursor.isEmpty())path+="&after="+encoded(cursor)+"&version="+encoded(version);
            JSONObject page=(JSONObject)request(path,null,true,true);
            version=page.getString("version");JSONArray features=page.getJSONArray("features");
            for(int i=0;i<features.length();i++){
                JSONObject feature=features.getJSONObject(i);
                if(!seen.add(feature.getString("id")))throw new IOException("서버 조회 중 중복 객체가 발견됐습니다.");
                ArrayList<CadRecord> parsed=ServerCadParser.feature(dataset,feature);
                for(CadRecord r:parsed)r.fields.put("__serverVersion",version);
                rows.addAll(parsed);if(rows.size()>30000)throw new IOException("표시할 객체가 많습니다. 지도를 확대하세요.");
            }
            cursor=page.isNull("next_cursor")?"":page.getString("next_cursor");
            if(++count>100)throw new IOException("조회 범위가 너무 큽니다. 지도를 확대하세요.");
        } while(!cursor.isEmpty());
        return rows;
    }
}
