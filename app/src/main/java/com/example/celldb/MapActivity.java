package com.example.celldb;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.*;
import android.net.Uri;
import android.widget.CheckBox;
import android.widget.HorizontalScrollView;
import android.widget.Toast;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import com.example.celldb.network.KakaoNetworkRenderer;
import com.example.celldb.network.NetworkModels.*;

public class MapActivity extends Activity {
    // Final single-server mode. Normal login is always used.
    private static final boolean ONLINE_VIEW_TEST_MODE = false;
    private final ArrayList<CadRecord> visibleRecords = new ArrayList<>();
    private final ArrayList<MapPoint> visiblePoints = new ArrayList<>();
    private final ArrayList<MapPoint> boundsPoints = new ArrayList<>();
    private MapRenderer map;
    private android.widget.FrameLayout screen;
    private LinearLayout mapScreen;
    private android.widget.ScrollView loginScreen;
    private TextView loginMessage;
    private boolean mapStarted;
    private android.widget.ScrollView settingsPanel;
    private TextView header;
    private float headerTouchY,headerTouchX;
    private LinearLayout settingsContent;
    private android.view.View mapArea;
    private TextView mapAttribution,connectionBadge;

    private boolean mapReady;
    private boolean destroyed;
    private String mapError;
    private TextView status;
    private LocationManager locationManager;
    private Location currentLocation;
    private boolean requestingLocation;
    private boolean centerOnFix;
    private KakaoNetworkRenderer networkRenderer;
    private NetworkData networkData;
    private final boolean[] layers = {true,true,false,false};
    private ArrayList<CadRecord> allRecords = new ArrayList<>();


    private final String[] categories = LayerGroups.IDS;
    private final Map<String,CadRecord> networkRecords = new HashMap<>();


    private TextView regionStatus;
    private TextView selectionStatus;
    private Button measureButton;
    private Button hybridButton;
    private final ArrayList<Button> quickLayerButtons=new ArrayList<>();
    private boolean hybridMode;
    private final DistanceMeasurement measurements=new DistanceMeasurement();
    private CadRecord selectedRecord;
    private String selectedCableKey="";
    private DistanceMeasurement.Line selectedMeasurement;
    private final ArrayList<ArrayList<CadRecord>> displayedLines=new ArrayList<>();
    private long ignoreTapUntil;
    private boolean escapeConsumed;
    private ServerApiClient server;
    private String serverDataset="",serverRegion="";
    private org.json.JSONArray serverLayers=new org.json.JSONArray();
    private Button serverButton, logoutButton;
    private TextView connectionStatus;
    private long lastVerified, lastConnectionCheck;
    private final ExecutorService serverWorker=Executors.newSingleThreadExecutor();
    private java.util.concurrent.Future<?> serverTask;
    private final android.os.Handler serverHandler=new android.os.Handler(android.os.Looper.getMainLooper());
    private int serverGeneration;
    private String viewportKey="",pendingViewportKey="";
    private String drawingLevel="L6";
    private long viewportChangedAt;
    private boolean foreground;
    private long lastServerFetch;
    private int displayRadiusMeters=500;
    private int refreshDistanceMeters=200;
    private MapPoint lastQueryCenter=null;
    private String lastQueryFilter="";
    private String lastQueryLevel="";
    private ServerMapCache mapCache;
    private ServerMapCache.State cacheState=new ServerMapCache.State();
    private final LinkedHashMap<String,String> serverVersions=new LinkedHashMap<>();
    private long lastVersionCheck;
    private final ArrayList<MapPoint> serverBounds=new ArrayList<>();
    private final Runnable serverPoll=new Runnable(){public void run(){
        if(!foreground||destroyed)return;
        checkServerConnection();pollServerViewport();serverHandler.postDelayed(this,400);
    }};


    private final LocationListener listener = new LocationListener() {
        @Override public void onLocationChanged(Location location) { updateLocation(location); }
        @Override public void onProviderEnabled(String provider) { }
        @Override public void onProviderDisabled(String provider) {
            status.setText("위치 제공 기능이 꺼졌습니다. 휴대폰 위치 설정을 확인하세요.");
        }
        @Override public void onStatusChanged(String provider, int state, Bundle extras) { }
    };

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        new android.util.AtomicFile(new java.io.File(getFilesDir(), "cad_records.json")).delete();


        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });

        TextView title = new TextView(this);
        title.setText("CMB 온라인 지도");header=title;
        title.setTextSize(14);
        title.setTextColor(Color.WHITE);
        title.setBackgroundColor(Color.rgb(15, 23, 42));
        title.setPadding(dp(10), dp(6), dp(10), dp(6));
        root.addView(title);
        LinearLayout menu=new LinearLayout(this);settingsContent=menu;menu.setOrientation(LinearLayout.VERTICAL);
        settingsPanel=new android.widget.ScrollView(this);settingsPanel.addView(menu);
        settingsPanel.setVisibility(android.view.View.GONE);root.addView(settingsPanel,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(200)));
        title.setOnClickListener(v->toggleSettingsPanel());
        title.setOnTouchListener((v,event)->{
            if(event.getAction()==android.view.MotionEvent.ACTION_DOWN){headerTouchY=event.getY();headerTouchX=event.getX();}
            if(event.getAction()==android.view.MotionEvent.ACTION_UP&&(landscape()?event.getX()-headerTouchX:event.getY()-headerTouchY)>dp(24)){toggleSettingsPanel();return true;}
            return false;
        });

        status = new TextView(this);
        status.setPadding(dp(8), dp(2), dp(8), dp(2));status.setTextSize(11);status.setMaxLines(1);

        HorizontalScrollView quickScroll=new HorizontalScrollView(this);
        quickScroll.setHorizontalScrollBarEnabled(false);
        LinearLayout quickBar=new LinearLayout(this);
        quickBar.setOrientation(LinearLayout.HORIZONTAL);
        String[] quickNames=LayerGroups.NAMES;
        for(int i=0;i<quickNames.length;i++){
            final int index=i;
            boolean defaultOn=index<2;
            layers[index]=getSharedPreferences("network_prefs",MODE_PRIVATE).getBoolean("group_"+categories[index],defaultOn);
            Button b=new Button(this);
            b.setText(quickNames[i]);
            b.setTextSize(11);
            b.setMinHeight(dp(36));
            b.setPadding(dp(8),0,dp(8),0);
            b.setSelected(layers[index]);
            updateLayerButtonStyle(b,layers[index]);
            b.setOnClickListener(v->{
                layers[index]=!layers[index];
                getSharedPreferences("network_prefs",MODE_PRIVATE).edit().putBoolean("group_"+categories[index],layers[index]).apply();
                updateLayerButtonStyle(b,layers[index]);
                loadMarkers();
            });
            quickLayerButtons.add(b);
            quickBar.addView(b,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,dp(38)));
        }
        hybridButton=new Button(this);
        hybridButton.setText("위성지도");
        hybridButton.setTextSize(11);
        hybridButton.setMinHeight(dp(36));
        hybridButton.setOnClickListener(v->{
            if(map==null||!map.supportsHybridMap()){
                Toast.makeText(this,"현재 지도에서는 위성지도를 지원하지 않습니다.",Toast.LENGTH_SHORT).show();
                return;
            }
            hybridMode=!hybridMode;
            map.setHybridMap(hybridMode);
            hybridButton.setText(hybridMode?"일반지도":"위성지도");
            status.setText(hybridMode?"위성지도":"일반지도");
        });
        quickBar.addView(hybridButton,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,dp(38)));

        measureButton=new Button(this);measureButton.setText("거리");measureButton.setTextSize(11);measureButton.setMinHeight(dp(36));
        measureButton.setOnClickListener(v->{
            if(measurements.active())finishMeasurement();
            else {measurements.start();selectedRecord=null;selectedMeasurement=null;measureButton.setText("완료");
                if(selectionStatus!=null)selectionStatus.setText("지도를 눌러 측정점을 추가하세요 · 완료로 구간 종료");drawMeasurements();}
        });
        quickBar.addView(measureButton,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,dp(38)));

        Button clearDistanceButton=new Button(this);clearDistanceButton.setText("거리 삭제");clearDistanceButton.setTextSize(11);clearDistanceButton.setMinHeight(dp(36));
        clearDistanceButton.setOnClickListener(v->{
            measurements.clearAll();selectedMeasurement=null;drawMeasurements();measureButton.setText("거리");
            if(selectionStatus!=null)selectionStatus.setText("거리 측정을 모두 삭제했습니다.");
        });
        quickBar.addView(clearDistanceButton,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,dp(38)));

        Button currentButton=new Button(this);currentButton.setText("현재위치");currentButton.setTextSize(11);currentButton.setMinHeight(dp(36));
        currentButton.setOnClickListener(v->{centerOnFix=true;requestLocation();});
        quickBar.addView(currentButton,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,dp(38)));

        Button settingsQuick=new Button(this);settingsQuick.setText("메뉴");settingsQuick.setTextSize(11);settingsQuick.setMinHeight(dp(36));
        settingsQuick.setOnClickListener(v->toggleSettingsPanel());
        quickBar.addView(settingsQuick,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,dp(38)));

        quickScroll.addView(quickBar);
        root.addView(quickScroll,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(40)));
        root.addView(status);

        LinearLayout actions = new LinearLayout(this);
        addButton(actions, "내 위치", () -> { centerOnFix = true; requestLocation(); });
        addButton(actions, "전체 보기", this::showAll);
        addButton(actions, "가까운 시설", this::showNearest);
        menu.addView(actions);
        LinearLayout tools=new LinearLayout(this);
        addButton(tools,"선택 메뉴",this::showSelectionMenu);
        addButton(tools,"전체 보기",this::showAll);
        menu.addView(tools);
        selectionStatus=new TextView(this);selectionStatus.setText("객체 선택 후 길게 누르기 / 우클릭 → 속성");
        selectionStatus.setPadding(dp(12),dp(4),dp(12),dp(4));menu.addView(selectionStatus);
        serverButton=new Button(this);serverButton.setText("서버 로그인");
        serverButton.setOnClickListener(v->showServerLogin());menu.addView(serverButton);
        logoutButton=new Button(this);logoutButton.setText("로그아웃");logoutButton.setEnabled(false);
        logoutButton.setOnClickListener(v->disconnectServer());menu.addView(logoutButton);
        connectionStatus=new TextView(this);connectionStatus.setPadding(dp(12),dp(2),dp(12),dp(2));connectionStatus.setTextSize(11);connectionStatus.setMaxLines(1);
        connectionStatus.setText("● 로그아웃 · 서버 연결 안 됨");root.addView(connectionStatus);
        regionStatus = new TextView(this);
        regionStatus.setText("서버 로그인 후 시설 도면을 조회합니다");
        regionStatus.setTextSize(11);
        regionStatus.setPadding(dp(12),dp(2),dp(12),dp(2));
        root.addView(regionStatus);
        // Windows 1.0 parity: display layers are controlled only by the compact top toolbar.
        // Keep this panel for account/region and object actions, not duplicate layer settings.

        map = BuildConfig.KAKAO_NATIVE_APP_KEY.isEmpty() ? new OsmMapRenderer(this)
                : new KakaoMapRenderer(this, BuildConfig.KAKAO_NATIVE_APP_KEY);
        map.setMapClick(this::onMapTap);
        MapInteractionView interaction=new MapInteractionView(this,()->{ignoreTapUntil=android.os.SystemClock.uptimeMillis()+600;showSelectionMenu();});
        interaction.addView(map.getView(),new android.widget.FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.MATCH_PARENT));
        mapArea=interaction;root.addView(interaction,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1f));

        TextView attribution = new TextView(this);
        attribution.setText((map instanceof OsmMapRenderer ? "© OpenStreetMap contributors" : "카카오맵")
                + " · CAD 좌표 변환 데이터");
        attribution.setTextSize(11);
        attribution.setGravity(Gravity.CENTER);
        attribution.setPadding(dp(4), dp(6), dp(4), dp(6));
        mapAttribution=attribution;root.addView(attribution);

        mapScreen=root;connectionBadge=new TextView(this);connectionBadge.setText("●");connectionBadge.setTextSize(18);connectionBadge.setGravity(Gravity.CENTER);
        layoutMapScreen();mapScreen.setVisibility(android.view.View.GONE);
        screen=new android.widget.FrameLayout(this);screen.addView(mapScreen);setContentView(screen);
        locationManager = (LocationManager) getSystemService(LOCATION_SERVICE);
        mapCache = new ServerMapCache(this);

        if (ONLINE_VIEW_TEST_MODE) enterOnlineViewTestMode();
        else showLoginScreen();
    }

    private void enterOnlineViewTestMode(){
        if(loginScreen!=null){
            screen.removeView(loginScreen);
            loginScreen=null;
        }
        mapScreen.setVisibility(android.view.View.VISIBLE);
        header.setText("CMB 온라인 지도");
        status.setText("CMB 서버 연결 준비");
        connectionStatus.setText("● 서버 연결 준비");
        connectionStatus.setTextColor(Color.rgb(180,110,0));
        regionStatus.setText("카카오맵 배경 + CMB 서버 Overlay 연결 준비");
        serverButton.setText("서버 로그인");
        logoutButton.setEnabled(false);
        startMap();
        mapScreen.postDelayed(()->{
            if(destroyed)return;
            if(foreground){
                map.resume();
                requestLocation();
            }
        },150);
    }

    private void startMap(){
        if(mapStarted)return;mapStarted=true;
        map.start(() -> {
            if (destroyed) return;
            mapReady = true;
            mapError = null;
            networkRenderer=null;
            loadMarkers();if(!serverBounds.isEmpty())map.showAll(serverBounds);
        }, message -> {
            mapError = message;
            status.setText(message);
        });
    }

    private boolean landscape(){return getResources().getConfiguration().orientation==android.content.res.Configuration.ORIENTATION_LANDSCAPE;}

    private void detach(android.view.View view){
        if(view.getParent() instanceof ViewGroup)((ViewGroup)view.getParent()).removeView(view);
    }

    private void layoutMapScreen(){
        // Keep the Kakao MapView in the same parent for the lifetime of the Activity.
        // Re-parenting its rendering surface during rotation can leave a black map.
        if(mapArea.getParent()!=mapScreen){
            for(android.view.View view:new android.view.View[]{header,settingsPanel,status,connectionStatus,regionStatus,mapArea,mapAttribution,connectionBadge})detach(view);
            mapScreen.removeAllViews();
            mapScreen.setOrientation(LinearLayout.VERTICAL);
            mapScreen.addView(header,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));
            mapScreen.addView(settingsPanel,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(250)));
            mapScreen.addView(status);
            mapScreen.addView(connectionStatus);
            mapScreen.addView(regionStatus);
            mapScreen.addView(mapArea,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));
            mapScreen.addView(mapAttribution);
        }

        header.setText("CMB 온라인 지도");
        header.setTextSize(landscape()?12:14);
        header.setGravity(Gravity.START);
        header.setPadding(dp(8),dp(5),dp(8),dp(5));

        ViewGroup.LayoutParams panelParams=settingsPanel.getLayoutParams();
        if(panelParams!=null){
            panelParams.height=landscape()?Math.min(dp(180),(int)(getResources().getDisplayMetrics().heightPixels*0.38)):dp(250);
            settingsPanel.setLayoutParams(panelParams);
        }
        settingsPanel.setVisibility(android.view.View.GONE);
        mapArea.requestLayout();
        mapArea.invalidate();
    }

    private void toggleSettingsPanel(){
        boolean opening=settingsPanel.getVisibility()!=android.view.View.VISIBLE;
        if(!landscape())settingsPanel.getLayoutParams().height=Math.min(dp(300),(int)(getResources().getDisplayMetrics().heightPixels*0.45));
        settingsPanel.setVisibility(opening?android.view.View.VISIBLE:android.view.View.GONE);
        header.setText(opening?"CMB 온라인 지도 · 메뉴":"CMB 온라인 지도");
        settingsPanel.requestLayout();
    }

    @Override public void onConfigurationChanged(android.content.res.Configuration configuration){
        super.onConfigurationChanged(configuration);
        // Do not detach/re-attach the Kakao MapView on rotation.
        layoutMapScreen();
        map.getView().requestLayout();
        map.getView().invalidate();
        if(mapStarted){
            map.getView().postDelayed(()->{
                if(destroyed)return;
                map.getView().requestLayout();
                map.getView().invalidate();
                if(server!=null&&mapReady){
                    viewportKey="";pendingViewportKey="";
                    showAll();
                }
            },250);
        }
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private void updateLayerButtonStyle(Button button,boolean on){
        button.setTextColor(on?Color.WHITE:Color.rgb(30,41,59));
        button.setBackgroundColor(on?Color.rgb(37,99,235):Color.rgb(241,245,249));
    }

    private void addButton(LinearLayout parent, String text, Runnable action) {
        Button button = new Button(this);
        button.setText(text);
        button.setTextSize(13);
        button.setOnClickListener(v -> action.run());
        parent.addView(button, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
    }

    @Override protected void onResume() {
        super.onResume();
        if(mapStarted)map.resume();
        loadMarkers();
        if(server!=null)requestLocation();
        foreground=true;serverHandler.removeCallbacks(serverPoll);serverHandler.post(serverPoll);
        if(server==null){
            serverButton.setEnabled(true);
            if(!ONLINE_VIEW_TEST_MODE) showLoginScreen();
        }
    }

    @Override protected void onPause() {
        foreground=false;serverHandler.removeCallbacks(serverPoll);cancelServerRequest();viewportKey="";
        stopLocation();
        if(mapStarted)map.pause();
        super.onPause();
    }

    @Override protected void onDestroy() {
        destroyed = true;

        serverHandler.removeCallbacksAndMessages(null);cancelServerRequest();
        if(server!=null)server.clear();serverWorker.shutdownNow();
        if(mapStarted)map.destroy();
        super.onDestroy();
    }

    private android.content.SharedPreferences layerPrefs() {
        return getSharedPreferences("network_prefs",MODE_PRIVATE);
    }

    private String group(CadRecord r) {
        if(LayerGroups.excluded(r.layer+" "+r.name+" "+r.fields.get("__serverBlock"))) return "";
        return layerPrefs().getString("assignment_"+LayerGroups.key(r),LayerGroups.defaultGroup(r.layer,r.category));
    }

    private boolean recordVisible(CadRecord r) {
        if(LayerGroups.excluded(r.layer+" "+r.name+" "+r.fields.get("__serverBlock")))return false;
        String symbol=String.valueOf(r.fields.get("__symbol"));
        if(symbol.startsWith("HIDDEN:"))return false;
        String group=group(r);
        if(!DrawingLevel.groupVisible(drawingLevel,group)||!DrawingLevel.recordVisible(drawingLevel,r))return false;
        for(int i=0;i<categories.length;i++) if(categories[i].equals(group))
            return layers[i];
        return false;
    }

    private void applyVisibility() {
        // Data is filtered by group AND sublayer before either renderer receives it.
        if(networkRenderer==null)return;
        networkRenderer.setCellVisible(true);networkRenderer.setFacilityVisible(true);
        networkRenderer.setEquipmentVisible(true);networkRenderer.setFiberVisible(true);networkRenderer.setCoaxVisible(true);
    }

    private void loadMarkers() {
        viewportKey="";
        if(server==null) allRecords.clear();
        renderMarkers();
    }

    private void renderMarkers() {
        if(selectedRecord!=null){
            String key=selectedRecord.stableKey();selectedRecord=null;
            for(CadRecord r:allRecords)if(r.stableKey().equals(key)){selectedRecord=r;break;}
            if(selectedRecord==null)selectionStatus.setText("객체를 선택하세요.");
        }
        visibleRecords.clear(); visiblePoints.clear(); boundsPoints.clear(); networkRecords.clear();
        if(mapReady) { map.clearOnuMarkers(); map.clearNetworkLines(); }
        networkData=new NetworkData();displayedLines.clear();
        if(selectedRecord!=null && !recordVisible(selectedRecord)){selectedRecord=null;selectionStatus.setText("선택한 객체가 숨겨졌습니다.");}
        LinkedHashMap<String,ArrayList<CadRecord>> fiber=new LinkedHashMap<>(), coax=new LinkedHashMap<>();
        java.util.HashSet<String> visibleCables=new java.util.HashSet<>();
        for(CadRecord r:allRecords)if(recordVisible(r)&&("FIBER".equals(r.category)||"COAX".equals(r.category)))
            visibleCables.add(r.layer+"|"+r.fields.get("__serverEntity"));
        for(CadRecord r:allRecords) {
            if(!recordVisible(r))continue;
            if(!r.hasCoordinates()) { networkData.skippedRows++; continue; }
            MapPoint point=new MapPoint(r.latitude,r.longitude);
            boundsPoints.add(point);
            if("FIBER".equals(r.category) || "COAX".equals(r.category)) {
                LinkedHashMap<String,ArrayList<CadRecord>> lines="FIBER".equals(r.category)?fiber:coax;
                if(!lines.containsKey(r.layer+"|"+r.id)) lines.put(r.layer+"|"+r.id,new ArrayList<>());
                lines.get(r.layer+"|"+r.id).add(r); continue;
            }
            visibleRecords.add(r); visiblePoints.add(point); networkRecords.put(r.stableKey(),r);
            PointItem item=new PointItem(r.category,r.stableKey(),r.title(),r.latitude,r.longitude,"");
            if("CELL".equals(r.category)) networkData.cells.add(item);
            else if("FACILITY".equals(r.category)) networkData.facilities.add(item);
            else if("EQUIPMENT".equals(r.category)) networkData.equipment.add(item);
            if(mapReady && networkRenderer==null && recordVisible(r)) {
                boolean geographic=map instanceof OsmMapRenderer && ((OsmMapRenderer)map).addGeoCadSymbol(point,r.fields.get("__cmbLayout"),visibleCables,()->selectRecord(r,point));
                if(!geographic)map.addCadSymbol(point,r.title(),r.fields.get("__symbol"),()->selectRecord(r,point));
            }
        }
        addLines(fiber,true); addLines(coax,false);
        if(map instanceof OsmMapRenderer)((OsmMapRenderer)map).bringCadSymbolsToFront();
        if(networkRenderer!=null) { networkRenderer.render(networkData); applyVisibility(); }
        status.setText("표시 중: 시설 "+networkData.facilities.size()+" · 장비/주석 "+(networkData.cells.size()+networkData.equipment.size())
            +" · 광 선형 "+networkData.fiber.size()+" · 동축 선형 "+networkData.coax.size()
            +(networkData.skippedRows>0?" · 좌표 오류 "+networkData.skippedRows+"행":""));
        android.util.Log.i("OnuNetwork","Loaded cells="+networkData.cells.size()+" facilities="+networkData.facilities.size()
            +" equipment="+networkData.equipment.size()+" fiber="+networkData.fiber.size()+" coax="+networkData.coax.size());
        drawMeasurements();
        if(currentLocation!=null) updateLocation(currentLocation);
        if(mapError!=null) status.setText(mapError);
    }

    private void addLines(LinkedHashMap<String,ArrayList<CadRecord>> grouped,boolean isFiber) {
        for(ArrayList<CadRecord> records:grouped.values()) {
            Collections.sort(records,(a,b)->Integer.compare(a.sequence,b.sequence));
            if(records.size()<2) continue;
            displayedLines.add(records);
            CadRecord first=records.get(0);
            LineItem line=new LineItem(first.id,first.name,first.subtype,first.fields.get("연결정보"),first.fields.get("길이"));
            ArrayList<MapPoint> points=new ArrayList<>();
            for(CadRecord r:records) { line.points.add(new GeoPoint(r.latitude,r.longitude)); points.add(new MapPoint(r.latitude,r.longitude)); }
            (isFiber?networkData.fiber:networkData.coax).add(line);
            String lineKey=first.layer+"|"+first.id;
            boolean selected=lineKey.equals(selectedCableKey);
            if(mapReady && networkRenderer==null) map.addNetworkLine(points,isFiber,selected);
        }
    }

    private void showAll() {
        if(server!=null&&!serverBounds.isEmpty()){if(mapReady)map.showAll(serverBounds);return;}
        ArrayList<MapPoint> points=new ArrayList<>();
        for(CadRecord r:allRecords) if(r.hasCoordinates() && recordVisible(r)) points.add(new MapPoint(r.latitude,r.longitude));
        if(points.isEmpty()) { Toast.makeText(this,"표시할 데이터가 없습니다. 지역 DB와 레이어 설정을 확인해주세요.",Toast.LENGTH_LONG).show(); return; }
        double south=90,north=-90,west=180,east=-180;
        for(MapPoint p:points) { south=Math.min(south,p.getLatitude()); north=Math.max(north,p.getLatitude()); west=Math.min(west,p.getLongitude()); east=Math.max(east,p.getLongitude()); }
        ArrayList<MapPoint> corners=new ArrayList<>(); corners.add(new MapPoint(south,west)); corners.add(new MapPoint(north,east));
        if(mapReady) map.showAll(corners);
    }

    private String distance(MapPoint point) {
        if (currentLocation == null) return "현재 위치 확인 전";
        float[] result = new float[1];
        Location.distanceBetween(currentLocation.getLatitude(), currentLocation.getLongitude(),
                point.getLatitude(), point.getLongitude(), result);
        return result[0] < 1000 ? Math.round(result[0]) + "m"
                : String.format(Locale.KOREA, "%.2fkm", result[0] / 1000);
    }

    private void showDetails(CadRecord r, MapPoint point) {
        if("SERVER".equals(r.source)&&!r.fields.containsKey("__detail")){
            loadServerDetails(r,point);return;
        }
        if (mapReady) map.center(point, false);
        StringBuilder details = new StringBuilder();
        String pole=CadObjectInfo.pole(r),address=CadObjectInfo.address(r);
        details.append("속성\n레이어: ").append(r.layer.isEmpty()?r.category:r.layer)
                .append("\n전주정보: ").append(pole.isEmpty()?"자료 없음":pole)
                .append("\n주소: ").append(address.isEmpty()?"자료 없음":address)
                .append("\n\n상세 정보\n분류: ").append(r.category)
                .append("\nID: ").append(r.id)
                .append("\n구분/이름: ").append(r.name)
                .append("\n세부유형: ").append(r.subtype)
                .append("\n거리: ").append(distance(point))
                .append("\n경도: ").append(r.longitude)
                .append("\n위도: ").append(r.latitude)
                .append("\n출처: ").append(r.source);
        for (Map.Entry<String,String> e : r.fields.entrySet()) {
            String v = e.getValue();
            if (v != null && !v.trim().isEmpty()
                    && !e.getKey().startsWith("__")
                    && !"경도".equals(e.getKey()) && !"위도".equals(e.getKey())) {
                details.append("\n").append(e.getKey()).append(": ").append(v);
            }
        }

        new AlertDialog.Builder(this)
                .setTitle(r.title())
                .setMessage(details.toString())
                .setPositiveButton("확인", null)
                .show();
    }

    private void cancelServerRequest(){
        ++serverGeneration;if(serverTask!=null)serverTask.cancel(true);
        if(server!=null)server.cancel();
    }

    private void showServerLogin(){
        if(server!=null){
            new AlertDialog.Builder(this).setTitle("서버 연결")
                .setItems(new String[]{"다른 허용 지역 선택","로그아웃"},(d,index)->{
                    if(index==0)chooseServerDataset();else disconnectServer();
                }).setNegativeButton("닫기",null).show();return;
        }
        showLoginScreen();
    }

    private void showLoginScreen(){
        if(loginScreen!=null)screen.removeView(loginScreen);
        mapScreen.setVisibility(android.view.View.GONE);
        loginScreen=new android.widget.ScrollView(this);loginScreen.setFillViewport(true);
        loginScreen.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets;});
        LinearLayout body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(dp(18),dp(8),dp(18),dp(8));
        body.setGravity(Gravity.CENTER_VERTICAL);body.setBackgroundColor(Color.rgb(246,248,251));
        TextView heading=new TextView(this);heading.setText("CMB 시설 조회");heading.setTextSize(28);heading.setTextColor(Color.rgb(15,23,42));body.addView(heading);
        TextView description=new TextView(this);description.setText("서버에 로그인하면 허용된 지역의 도면을 조회할 수 있습니다.");description.setPadding(0,dp(12),0,dp(24));body.addView(description);
        TextView connectionInfo=new TextView(this);connectionInfo.setText("CMB 보안 서버 연결");connectionInfo.setTextColor(Color.rgb(71,85,105));body.addView(connectionInfo);
        getSharedPreferences("server_prefs",MODE_PRIVATE).edit().remove("url").apply();

        android.widget.EditText username=new android.widget.EditText(this);
        username.setSingleLine(true);
        username.setHint("아이디");
        username.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS);
        if(android.os.Build.VERSION.SDK_INT>=26){
            username.setAutofillHints(android.view.View.AUTOFILL_HINT_USERNAME);
            username.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_YES);
        }
        body.addView(username);

        android.widget.EditText password=new android.widget.EditText(this);
        password.setSingleLine(true);
        password.setHint("비밀번호");
        password.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setSaveEnabled(true);
        if(android.os.Build.VERSION.SDK_INT>=26){
            password.setAutofillHints(android.view.View.AUTOFILL_HINT_PASSWORD);
            password.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_YES);
        }
        body.addView(password);

        Button savedLogin=new Button(this);
        savedLogin.setText("저장된 로그인 정보 / 지문");
        body.addView(savedLogin);

        loginMessage=new TextView(this);loginMessage.setPadding(0,dp(12),0,dp(12));body.addView(loginMessage);
        Button login=new Button(this);login.setText("로그인");body.addView(login);
        loginScreen.addView(body);screen.addView(loginScreen);

        savedLogin.setOnClickListener(v->{
            loginMessage.setText("휴대폰의 저장된 로그인 정보를 확인하는 중…");
            MobileCredentialHelper.requestSavedLogin(this,new MobileCredentialHelper.LoginCallback(){
                @Override public void onCredential(String savedUser,String savedPassword){
                    username.setText(savedUser);
                    password.setText(savedPassword);
                    loginMessage.setText("저장된 계정을 불러왔습니다.");
                    login.performClick();
                }
                @Override public void onUnavailable(){
                    loginMessage.setText("저장된 로그인 정보가 없습니다. 아이디와 비밀번호를 직접 입력해주세요.");
                }
            });
        });

        login.setOnClickListener(v->{
            final String user=username.getText().toString().trim(),secret=password.getText().toString();
            if(user.isEmpty()||secret.isEmpty()){password.setError("계정과 비밀번호를 입력하세요.");return;}
            final ServerApiClient candidate=new ServerApiClient();
            password.setText("");login.setEnabled(false);loginMessage.setText("로그인 중…");serverButton.setEnabled(false);connectionStatus.setText("● 서버 로그인 중…");status.setText("서버 로그인 중…");
            final int generation=++serverGeneration;
            serverTask=serverWorker.submit(()->{
                try{
                    candidate.login(user,secret);
                    runOnUiThread(()->{
                        if(destroyed||generation!=serverGeneration){candidate.clear();return;}
                        server=candidate;allRecords.clear();renderMarkers();markServerOnline();logoutButton.setEnabled(true);
                        MobileCredentialHelper.offerSaveLogin(this,user,secret);
                        serverButton.setEnabled(true);serverButton.setText("서버 · "+user);
                        screen.removeView(loginScreen);loginScreen=null;mapScreen.setVisibility(android.view.View.VISIBLE);
                        startMap();if(foreground){map.resume();requestLocation();}chooseServerDataset();
                    });
                }catch(Exception error){candidate.clear();runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration)return;
                    login.setEnabled(true);loginMessage.setText("로그인 실패: "+serverMessage(error));
                    connectionStatus.setText("● 로그인 실패 · 연결 안 됨");serverButton.setEnabled(true);status.setText("로그인 실패: "+serverMessage(error));
                });}
            });
        });
    }

    private String serverMessage(Exception error){
        String category=ServerError.category(error);
        if(BuildConfig.DEBUG)android.util.Log.w("CmbServer",category);
        return ServerError.userMessage(error);
    }

    private void disconnectServer(){
        ServerApiClient previous=server;cancelServerRequest();server=null;serverDataset="";serverLayers=new org.json.JSONArray();
        serverBounds.clear();lastVerified=0;lastConnectionCheck=0;
        lastQueryCenter=null;lastQueryFilter="";lastQueryLevel="";
        cacheState=new ServerMapCache.State();serverVersions.clear();lastVersionCheck=0;
        logoutButton.setEnabled(false);connectionStatus.setText("● 로그아웃 · 서버 연결 안 됨");
        allRecords.clear();selectedRecord=null;renderMarkers();serverButton.setEnabled(true);serverButton.setText("서버 로그인");
        regionStatus.setText("서버 연결 해제 · 시설 도면 없음");
        if(previous!=null)serverWorker.execute(previous::logout);
        loadMarkers();stopLocation();
        if(ONLINE_VIEW_TEST_MODE) enterOnlineViewTestMode();
        else showLoginScreen();
    }

    private void chooseServerDataset(){
        cancelServerRequest();serverDataset="";allRecords.clear();renderMarkers();
        lastQueryCenter=null;lastQueryFilter="";lastQueryLevel="";
        final ServerApiClient client=server;if(client==null)return;final int generation=serverGeneration;
        status.setText("권한 지역을 조회하는 중…");
        serverTask=serverWorker.submit(()->{
            try{
                org.json.JSONArray regions=client.regions();
                ArrayList<String> titles=new ArrayList<>(),ids=new ArrayList<>();
                for(int i=0;i<regions.length();i++){
                    org.json.JSONObject region=regions.getJSONObject(i);
                    String id=region.optString("id","").trim();
                    if(id.isEmpty())continue;
                    String name=region.optString("name",id).trim();
                    titles.add(name.equals(id)?id:(name+" ("+id+")"));
                    ids.add(id);
                }
                runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration)return;
                    if(ids.isEmpty()){
                        status.setText("배정된 canonical 지역 권한이 없습니다.");
                        regionStatus.setText("시설 도면 없음");
                        return;
                    }
                    if(ids.size()==1){
                        selectServerDataset(client,ids.get(0),titles.get(0));
                    }else{
                        new AlertDialog.Builder(this)
                            .setTitle("권한 지역 선택")
                            .setItems(titles.toArray(new String[0]),(d,i)->selectServerDataset(client,ids.get(i),titles.get(i)))
                            .setNegativeButton("닫기",null)
                            .show();
                    }
                });
            }catch(Exception error){runOnUiThread(()->{if(!destroyed&&generation==serverGeneration){markServerOffline();status.setText(serverMessage(error));}});}
        });
    }

    private LinkedHashMap<String,String> versionMap(org.json.JSONObject json){
        LinkedHashMap<String,String> out=new LinkedHashMap<>();
        if(json==null)return out;
        Iterator<String> keys=json.keys();
        while(keys.hasNext()){
            String key=keys.next();
            String value=json.optString(key,"");
            if(!key.trim().isEmpty()&&!value.trim().isEmpty())out.put(key.trim().toUpperCase(),value.trim());
        }
        return out;
    }

    private void showCachedAround(MapPoint center){
        if(center==null)return;
        double keepRadius=Math.max(displayRadiusMeters*1.6,displayRadiusMeters+refreshDistanceMeters);
        allRecords=ServerMapCache.around(cacheState,center,keepRadius);
        renderMarkers();
    }

    private void selectServerDataset(ServerApiClient client,String dataset,String title){
        cancelServerRequest();final int generation=serverGeneration;
        serverTask=serverWorker.submit(()->{
            try{
                org.json.JSONObject metadata=client.onlineLayers(dataset);
                org.json.JSONObject displaySettings=client.mapDisplaySettings();
                org.json.JSONObject versionsJson=client.onlineVersions(dataset);
                LinkedHashMap<String,String> versions=versionMap(versionsJson);
                ServerMapCache.State loadedCache=mapCache.load(dataset);
                boolean cacheInvalidated=ServerMapCache.applyVersions(loadedCache,versions);
                if(cacheInvalidated)mapCache.save(dataset,loadedCache);
                runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration||client!=server)return;
                    markServerOnline();serverDataset=dataset;serverRegion=title;serverLayers=metadata.optJSONArray("layers");
                    cacheState=loadedCache;serverVersions.clear();serverVersions.putAll(versions);
                    lastVersionCheck=android.os.SystemClock.uptimeMillis();
                    displayRadiusMeters=Math.max(100,Math.min(3000,displaySettings.optInt("radius_m",500)));
                    refreshDistanceMeters=Math.max(25,Math.min(displayRadiusMeters,displaySettings.optInt("refresh_distance_m",200)));
                    lastQueryCenter=null;lastQueryFilter="";lastQueryLevel="";
                    if(serverLayers==null)serverLayers=new org.json.JSONArray();
                    regionStatus.setText(title+" · 서버 조회");viewportKey="";pendingViewportKey="";
                    org.json.JSONObject box=metadata.optJSONObject("bounds");
                    if(box!=null){
                        serverBounds.clear();
                        serverBounds.add(new MapPoint(box.optDouble("south"),box.optDouble("west")));
                        serverBounds.add(new MapPoint(box.optDouble("north"),box.optDouble("east")));
                    }
                    if(mapReady&&currentLocation!=null){
                        MapPoint here=new MapPoint(currentLocation);
                        showCachedAround(here);
                        map.center(here,true);
                        if(!cacheState.records.isEmpty())status.setText("로컬 캐시 즉시 표시 · 서버 Revision 확인 완료");
                    }
                });
            }catch(Exception error){runOnUiThread(()->{if(!destroyed&&generation==serverGeneration){markServerOffline();status.setText(serverMessage(error));}});}
        });
    }

    private String serverLayerFilter(){
        ArrayList<String> selected=new ArrayList<>();
        for(int i=0;i<serverLayers.length();i++){
            org.json.JSONObject info=serverLayers.optJSONObject(i);if(info==null)continue;
            CadRecord r=new CadRecord();r.layer=info.optString("layer");r.category=info.optString("group_id").equals("POLE")?"FACILITY":info.optString("group_id");
            String assigned=group(r);
            for(int j=0;j<categories.length;j++)if(categories[j].equals(assigned)&&layers[j]&&DrawingLevel.groupVisible(drawingLevel,assigned))selected.add(r.layer);
        }
        return android.text.TextUtils.join(",",selected);
    }

    private void markServerOnline(){
        lastVerified=android.os.SystemClock.uptimeMillis();
        connectionStatus.setText("● 온라인 · 서버 응답 확인 " + new java.text.SimpleDateFormat("HH:mm:ss",Locale.KOREA).format(new Date()));
        connectionStatus.setTextColor(Color.rgb(0,120,60));connectionBadge.setTextColor(Color.rgb(0,120,60));
    }

    private void markServerOffline(){
        lastVerified=0;
        connectionStatus.setText("● 연결 확인 실패 · 재연결 중");
        connectionStatus.setTextColor(Color.RED);connectionBadge.setTextColor(Color.RED);
        // 서버가 잠시 끊겨도 Windows Viewer와 동일하게 기존 캐시 화면을 유지한다.
        viewportKey="";
    }

    private void checkServerConnection(){
        if(server==null)return;
        long now=android.os.SystemClock.uptimeMillis();
        if(lastVerified>0 && now-lastVerified>15000)markServerOffline();
        if(now-lastConnectionCheck<5000 || (serverTask!=null&&!serverTask.isDone()))return;
        lastConnectionCheck=now;
        final ServerApiClient client=server;final int generation=serverGeneration;
        serverTask=serverWorker.submit(()->{
            try{
                client.regions();
                org.json.JSONObject versionsJson=null;
                long versionNow=android.os.SystemClock.uptimeMillis();
                if(!serverDataset.isEmpty()&&(lastVersionCheck==0||versionNow-lastVersionCheck>=60000)){
                    versionsJson=client.onlineVersions(serverDataset);
                }
                final org.json.JSONObject checkedVersions=versionsJson;
                runOnUiThread(()->{
                    if(destroyed||!foreground||server!=client||generation!=serverGeneration)return;
                    markServerOnline();
                    if(checkedVersions!=null){
                        LinkedHashMap<String,String> versions=versionMap(checkedVersions);
                        boolean changed=ServerMapCache.applyVersions(cacheState,versions);
                        serverVersions.clear();serverVersions.putAll(versions);
                        lastVersionCheck=android.os.SystemClock.uptimeMillis();
                        if(changed){
                            mapCache.save(serverDataset,cacheState);
                            lastQueryCenter=null;lastQueryFilter="";lastQueryLevel="";
                            MapViewport v=map.viewport();
                            if(v!=null)showCachedAround(new MapPoint((v.south+v.north)/2.0,(v.west+v.east)/2.0));
                            status.setText("서버 도면 변경 감지 · 변경 그룹만 갱신");
                        }
                    }
                });
            }catch(Exception error){
                runOnUiThread(()->{if(!destroyed&&foreground&&server==client&&generation==serverGeneration)markServerOffline();});
            }
        });
    }

    private MapViewport viewportAround(MapPoint center,int radiusMeters){
        double lat=center.getLatitude(),lng=center.getLongitude();
        double latDelta=radiusMeters/111320.0;
        double scale=Math.max(0.2,Math.cos(Math.toRadians(lat)));
        double lngDelta=radiusMeters/(111320.0*scale);
        return new MapViewport(lng-lngDelta,lat-latDelta,lng+lngDelta,lat+latDelta);
    }

    private void mergeServerRows(
            ArrayList<CadRecord> rows,
            MapPoint queryCenter,
            String filter,
            String versionKey
    ){
        ServerMapCache.merge(
                cacheState,
                rows,
                queryCenter,
                displayRadiusMeters,
                filter,
                versionKey
        );
        mapCache.save(serverDataset,cacheState);
        showCachedAround(queryCenter);
    }

    private void pollServerViewport(){
        if(server==null||serverDataset.isEmpty()||!mapReady)return;
        MapViewport visible=map.viewport();if(visible==null)return;

        String level=DrawingLevel.forWindowsLevel(map.windowsMapLevel());
        if(!level.equals(drawingLevel)){drawingLevel=level;renderMarkers();}
        regionStatus.setText(serverRegion+" · "+DrawingLevel.label(drawingLevel)
                +" · 반경 "+displayRadiusMeters+"m");

        String filter=serverLayerFilter();
        if(filter.isEmpty())return;

        MapPoint center=new MapPoint(
                (visible.south+visible.north)/2.0,
                (visible.west+visible.east)/2.0
        );

        boolean moved=lastQueryCenter==null
                || lastQueryCenter.distanceToAsDouble(center)>=refreshDistanceMeters;
        boolean modeChanged=!filter.equals(lastQueryFilter)||!drawingLevel.equals(lastQueryLevel);
        long now=android.os.SystemClock.uptimeMillis();
        String cacheVersionKey=ServerMapCache.versionKey(serverVersions,filter);

        if(!moved&&!modeChanged)return;

        if(ServerMapCache.covered(
                cacheState,
                center,
                displayRadiusMeters,
                filter,
                cacheVersionKey
        )){
            lastQueryCenter=center;
            lastQueryFilter=filter;
            lastQueryLevel=drawingLevel;
            showCachedAround(center);
            status.setText("로컬 캐시 · 주변 "+displayRadiusMeters+"m");
            return;
        }

        if(serverTask!=null&&!serverTask.isDone())return;

        final MapViewport queryViewport=viewportAround(center,displayRadiusMeters);
        final MapPoint queryCenter=center;
        final String queryFilter=filter;
        final String queryLevel=drawingLevel;
        final String queryVersionKey=cacheVersionKey;
        final int generation=serverGeneration;
        final ServerApiClient client=server;
        final String dataset=serverDataset;

        status.setText("주변 "+displayRadiusMeters+"m 서버 자료를 갱신하는 중…");
        serverTask=serverWorker.submit(()->{
            try{
                ArrayList<CadRecord> rows=client.onlineObjects(dataset,queryViewport,queryFilter);
                runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration)return;
                    markServerOnline();
                    lastServerFetch=android.os.SystemClock.uptimeMillis();
                    lastQueryCenter=queryCenter;
                    lastQueryFilter=queryFilter;
                    lastQueryLevel=queryLevel;
                    mergeServerRows(rows,queryCenter,queryFilter,queryVersionKey);
                    regionStatus.setText(serverRegion+" · "+DrawingLevel.label(drawingLevel)
                            +" · 반경 "+displayRadiusMeters+"m");
                });
            }catch(Exception error){runOnUiThread(()->{
                if(destroyed||generation!=serverGeneration)return;
                markServerOffline();
                status.setText("서버 조회 실패: "+serverMessage(error));
            });}
        });
    }

    private void loadServerDetails(CadRecord record,MapPoint point){
        if(record!=null&&record.fields.containsKey("__onlineRegion")){showDetails(record,point);return;}
        if(server==null)return;cancelServerRequest();final int generation=serverGeneration;final ServerApiClient client=server;
        status.setText("서버에서 객체 속성을 조회하는 중…");
        serverTask=serverWorker.submit(()->{
            try{
                org.json.JSONObject detail=client.detail(record.fields.get("__serverDataset"),record.layer,record.fields.get("__serverEntity"),record.fields.get("__serverVersion"));
                org.json.JSONObject fields=detail.getJSONObject("feature").getJSONObject("properties").getJSONObject("attributes").getJSONObject("fields");
                runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration)return;
                    markServerOnline();for(Iterator<String> keys=fields.keys();keys.hasNext();){String key=keys.next();record.fields.put(key,fields.optString(key,""));}
                    record.fields.put("__detail","yes");showDetails(record,point);
                });
            }catch(Exception error){runOnUiThread(()->{if(!destroyed&&generation==serverGeneration){markServerOffline();status.setText(serverMessage(error));}});}
        });
    }

    private void selectRecord(CadRecord record,MapPoint point) {
        if(android.os.SystemClock.uptimeMillis()<ignoreTapUntil)return;
        if(measurements.active()){addMeasurementPoint(point);return;}
        boolean hadCable=!selectedCableKey.isEmpty();
        selectedCableKey="";
        selectedRecord=record;selectedMeasurement=null;
        String pole=CadObjectInfo.pole(record);
        selectionStatus.setText("선택: "+record.title()+(pole.isEmpty()?"":" · 전주 "+pole)+" · 길게 누르기/우클릭으로 속성");
        if(hadCable)renderMarkers();
    }

    private void addMeasurementPoint(MapPoint point){
        measurements.add(point.getLatitude(),point.getLongitude());drawMeasurements();
        List<DistanceMeasurement.Point> points=measurements.current();double meters=0;
        for(int i=1;i<points.size();i++)meters+=DistanceMeasurement.distance(points.get(i-1),points.get(i));
        selectionStatus.setText("측정 중 · "+points.size()+"점 · "+formatMeters(meters));
    }

    private String formatMeters(double meters){return meters<1000?String.format(Locale.KOREA,"%.1f m",meters):String.format(Locale.KOREA,"%.3f km",meters/1000);}

    private void finishMeasurement(){
        DistanceMeasurement.Line line=measurements.finish();measureButton.setText("거리 측정");drawMeasurements();
        selectedRecord=null;selectedMeasurement=line;
        selectionStatus.setText(line==null?"측정 종료 · 두 점 이상을 선택해야 선이 생성됩니다.":"측정 완료 · "+formatMeters(line.meters)+" · 선 선택 후 메뉴에서 삭제");
    }

    private void drawMeasurements(){if(mapReady)map.showMeasurements(measurements.lines(),measurements.current());}

    private double segmentDistance(android.graphics.Point tap,android.graphics.Point a,android.graphics.Point b){
        if(tap==null||a==null||b==null)return Double.POSITIVE_INFINITY;
        double dx=b.x-a.x,dy=b.y-a.y,length=dx*dx+dy*dy;
        double t=length==0?0:Math.max(0,Math.min(1,((tap.x-a.x)*dx+(tap.y-a.y)*dy)/length));
        return Math.hypot(tap.x-a.x-t*dx,tap.y-a.y-t*dy);
    }

    private void onMapTap(MapPoint point){
        if(android.os.SystemClock.uptimeMillis()<ignoreTapUntil)return;
        if(measurements.active()){addMeasurementPoint(point);return;}
        android.graphics.Point tap=map.screenPoint(point);
        double best=dp(20);DistanceMeasurement.Line chosen=null;
        for(DistanceMeasurement.Line line:measurements.lines())for(int i=1;i<line.points.size();i++){
            DistanceMeasurement.Point a=line.points.get(i-1),b=line.points.get(i);
            double distance=segmentDistance(tap,map.screenPoint(new MapPoint(a.lat,a.lon)),map.screenPoint(new MapPoint(b.lat,b.lon)));
            if(distance<best){best=distance;chosen=line;}
        }
        if(chosen!=null){selectedMeasurement=chosen;selectedRecord=null;selectionStatus.setText("측정선 선택 · "+formatMeters(chosen.meters)+" · 길게 누르기/우클릭으로 삭제");return;}
        CadRecord candidate=null;best=dp(18);
        for(ArrayList<CadRecord> line:displayedLines)for(int i=1;i<line.size();i++){
            CadRecord a=line.get(i-1),b=line.get(i);
            double distance=segmentDistance(tap,map.screenPoint(new MapPoint(a.latitude,a.longitude)),map.screenPoint(new MapPoint(b.latitude,b.longitude)));
            if(distance<best){best=distance;candidate=line.get(0);}
        }
        if(candidate!=null){
            selectedCableKey=candidate.layer+"|"+candidate.id;
            selectedRecord=candidate;selectedMeasurement=null;
            selectionStatus.setText("케이블 선택 · 기기 위 강조 표시 · 길게 누르기/우클릭으로 속성");
            renderMarkers();
        } else {
            boolean hadCable=!selectedCableKey.isEmpty();
            selectedCableKey="";
            selectedRecord=null;selectedMeasurement=null;selectionStatus.setText("객체를 선택하세요.");
            if(hadCable)renderMarkers();
        }
    }

    private void showSelectionMenu(){
        if(measurements.active()){Toast.makeText(this,"Esc 또는 측정 종료로 먼저 측정을 완료하세요.",Toast.LENGTH_SHORT).show();return;}
        if(selectedMeasurement!=null){
            final long id=selectedMeasurement.id;
            new AlertDialog.Builder(this).setTitle("거리 측정선 · "+formatMeters(selectedMeasurement.meters))
                .setItems(new String[]{"삭제"},(dialog,which)->{
                    measurements.delete(id);selectedMeasurement=null;drawMeasurements();selectionStatus.setText("측정선을 삭제했습니다.");
                }).setNegativeButton("닫기",null).show();return;
        }
        if(selectedRecord!=null){showDetails(selectedRecord,new MapPoint(selectedRecord.latitude,selectedRecord.longitude));return;}
        Toast.makeText(this,"먼저 객체 또는 측정선을 선택하세요.",Toast.LENGTH_SHORT).show();
    }

    @Override public boolean dispatchKeyEvent(android.view.KeyEvent event){
        if(event.getKeyCode()==android.view.KeyEvent.KEYCODE_ESCAPE){
            if(event.getAction()==android.view.KeyEvent.ACTION_DOWN && measurements.active()){
                escapeConsumed=true;finishMeasurement();return true;
            }
            if(escapeConsumed){if(event.getAction()==android.view.KeyEvent.ACTION_UP)escapeConsumed=false;return true;}
        }
        return super.dispatchKeyEvent(event);
    }

    private void showNearest() {
        if (currentLocation == null) {
            centerOnFix = false;
            requestLocation();
            status.setText("현재 위치를 확인한 후 가까운 시설을 다시 눌러주세요.");
            return;
        }
        if (visibleRecords.isEmpty()) { showAll(); return; }

        ArrayList<Integer> order = new ArrayList<>();
        MapPoint current = new MapPoint(currentLocation);
        for (int i=0; i<visiblePoints.size(); i++) if(recordVisible(visibleRecords.get(i))) order.add(i);
        Collections.sort(order, (a,b) -> Double.compare(
                visiblePoints.get(a).distanceToAsDouble(current),
                visiblePoints.get(b).distanceToAsDouble(current)));

        int count = Math.min(8, order.size());
        String[] names = new String[count];
        for (int i=0; i<count; i++) {
            int idx = order.get(i);
            CadRecord r = visibleRecords.get(idx);
            names[i] = r.category + " · " + r.title() + " · " + distance(visiblePoints.get(idx));
        }

        new AlertDialog.Builder(this)
                .setTitle("가까운 시설/장비")
                .setItems(names, (dialog, which) -> {
                    int idx = order.get(which);
                    showDetails(visibleRecords.get(idx), visiblePoints.get(idx));
                })
                .setNegativeButton("닫기", null)
                .show();
    }

    private boolean hasLocationPermission() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private void requestLocation() {
        if (!hasLocationPermission()) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION}, 2001);
            return;
        }
        stopLocation();
        try {
            boolean fine = checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED;
            Location newest = null;
            for (String provider : new String[]{LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER}) {
                if (LocationManager.GPS_PROVIDER.equals(provider) && !fine) continue;
                if (!locationManager.getAllProviders().contains(provider) || !locationManager.isProviderEnabled(provider)) continue;
                Location cached = locationManager.getLastKnownLocation(provider);
                if (cached != null && android.os.SystemClock.elapsedRealtimeNanos()-cached.getElapsedRealtimeNanos()<120_000_000_000L && (newest == null || cached.getTime() > newest.getTime())) newest = cached;
                locationManager.requestLocationUpdates(provider, 3000, 3, listener);
                requestingLocation = true;
            }
            if (newest != null) updateLocation(newest);
        } catch (SecurityException error) {
            status.setText("위치 권한을 확인해주세요.");
        }
    }

    private void stopLocation() {
        if (locationManager != null && requestingLocation) {
            try { locationManager.removeUpdates(listener); } catch (SecurityException ignored) {}
            requestingLocation = false;
        }
    }

    private void updateLocation(Location location) {
        currentLocation = location;
        MapPoint point = new MapPoint(location);
        if (mapReady) map.setCurrentLocation(point, "정확도 약 ±" + Math.round(location.getAccuracy()) + "m");
        if (centerOnFix && mapReady) {
            map.center(point, true);
            centerOnFix = false;
        }
    }

    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 2001) {
            if (hasLocationPermission()) requestLocation();
            else status.setText("위치 권한 없이 CAD 서버 지도를 표시합니다.");
        }
    }
}
