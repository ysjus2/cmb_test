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
    private final boolean[] layers = {true,true,true};
    private ArrayList<CadRecord> allRecords = new ArrayList<>();


    private final String[] categories = LayerGroups.IDS;
    private final Map<String,CadRecord> networkRecords = new HashMap<>();


    private TextView regionStatus;
    private TextView selectionStatus;
    private Button measureButton;
    private final DistanceMeasurement measurements=new DistanceMeasurement();
    private CadRecord selectedRecord;
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
    private String drawingLevel="overview";
    private long viewportChangedAt;
    private boolean foreground;
    private long lastServerFetch;
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
        title.setText("CAD 서버 지도 · 설정 ▼");header=title;
        title.setTextSize(21);
        title.setTextColor(Color.WHITE);
        title.setBackgroundColor(Color.rgb(15, 23, 42));
        title.setPadding(dp(16), dp(12), dp(16), dp(12));
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
        status.setPadding(dp(12), dp(2), dp(12), dp(2));status.setTextSize(11);status.setMaxLines(1);
        root.addView(status);

        LinearLayout actions = new LinearLayout(this);
        addButton(actions, "내 위치", () -> { centerOnFix = true; requestLocation(); });
        addButton(actions, "전체 보기", this::showAll);
        addButton(actions, "가까운 시설", this::showNearest);
        menu.addView(actions);
        LinearLayout tools=new LinearLayout(this);
        measureButton=new Button(this);measureButton.setText("거리 측정");measureButton.setTextSize(13);
        measureButton.setOnClickListener(v->{
            if(measurements.active())finishMeasurement();
            else {measurements.start();selectedRecord=null;selectedMeasurement=null;measureButton.setText("측정 종료");
                selectionStatus.setText("지도를 눌러 측정점을 추가하세요 · Esc 또는 측정 종료로 완료");drawMeasurements();}
        });
        tools.addView(measureButton,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
        addButton(tools,"선택 메뉴",this::showSelectionMenu);menu.addView(tools);
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
        HorizontalScrollView scroll = new HorizontalScrollView(this);
        LinearLayout toggles = new LinearLayout(this);
        String[] names = LayerGroups.NAMES;
        for (int i=0;i<names.length;i++) {
            final int index=i;
            CheckBox check = new CheckBox(this);
            check.setText(names[i]); check.setTextSize(12);
            layers[i]=getSharedPreferences("network_prefs",MODE_PRIVATE).getBoolean("group_"+categories[i],true);
            check.setChecked(layers[i]);
            check.setOnCheckedChangeListener((button,checked) -> {
                layers[index]=checked;
                getSharedPreferences("network_prefs",MODE_PRIVATE).edit().putBoolean("group_"+categories[index],checked).apply();
                loadMarkers();
            });
            toggles.addView(check);
        }
        scroll.addView(toggles); menu.addView(scroll);
        Button settings = new Button(this);
        settings.setText("설정 · 레이어 편집");
        settings.setOnClickListener(v -> showLayerSettings());
        menu.addView(settings);

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

        showLoginScreen();
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
        for(android.view.View view:new android.view.View[]{header,settingsPanel,status,connectionStatus,regionStatus,mapArea,mapAttribution,connectionBadge})detach(view);
        mapScreen.removeAllViews();settingsPanel.setVisibility(android.view.View.GONE);
        if(landscape()){
            mapScreen.setOrientation(LinearLayout.HORIZONTAL);
            LinearLayout rail=new LinearLayout(this);rail.setOrientation(LinearLayout.VERTICAL);
            header.setText("설정\n▶");header.setTextSize(13);header.setGravity(Gravity.CENTER);header.setPadding(dp(4),dp(12),dp(4),dp(12));
            rail.addView(header,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));
            connectionBadge.setTextColor(connectionStatus.getCurrentTextColor());rail.addView(connectionBadge);
            mapScreen.addView(rail,new LinearLayout.LayoutParams(dp(48),ViewGroup.LayoutParams.MATCH_PARENT));
            settingsContent.addView(connectionStatus,0);settingsContent.addView(status,1);settingsContent.addView(regionStatus,2);
            mapScreen.addView(settingsPanel,new LinearLayout.LayoutParams(Math.min(dp(300),(int)(getResources().getDisplayMetrics().widthPixels*0.4)),ViewGroup.LayoutParams.MATCH_PARENT));
            LinearLayout drawing=new LinearLayout(this);drawing.setOrientation(LinearLayout.VERTICAL);
            drawing.addView(mapArea,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));drawing.addView(mapAttribution);
            mapScreen.addView(drawing,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.MATCH_PARENT,1));
        }else{
            mapScreen.setOrientation(LinearLayout.VERTICAL);
            header.setText("CAD 서버 지도 · 설정 ▼");header.setTextSize(21);header.setGravity(Gravity.START);header.setPadding(dp(16),dp(12),dp(16),dp(12));
            mapScreen.addView(header,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT));mapScreen.addView(settingsPanel,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(250)));
            mapScreen.addView(status);mapScreen.addView(connectionStatus);mapScreen.addView(regionStatus);
            mapScreen.addView(mapArea,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1));mapScreen.addView(mapAttribution);
        }
    }

    private void toggleSettingsPanel(){
        boolean opening=settingsPanel.getVisibility()!=android.view.View.VISIBLE;
        if(!landscape())settingsPanel.getLayoutParams().height=Math.min(dp(300),(int)(getResources().getDisplayMetrics().heightPixels*0.45));
        settingsPanel.setVisibility(opening?android.view.View.VISIBLE:android.view.View.GONE);
        header.setText(landscape()?(opening?"설정\n◀":"설정\n▶"):(opening?"CAD 서버 지도 · 설정 ▲":"CAD 서버 지도 · 설정 ▼"));
        settingsPanel.requestLayout();
    }

    @Override public void onConfigurationChanged(android.content.res.Configuration configuration){
        super.onConfigurationChanged(configuration);layoutMapScreen();
        if(server!=null&&mapReady){
            viewportKey="";pendingViewportKey="";
            map.getView().postDelayed(()->{if(!destroyed&&server!=null)showAll();},250);
        }
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

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
        if(server==null){serverButton.setEnabled(true);showLoginScreen();}
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
        if(LayerGroups.excluded(r.layer)) return "";
        return layerPrefs().getString("assignment_"+LayerGroups.key(r),LayerGroups.defaultGroup(r.layer,r.category));
    }

    private boolean recordVisible(CadRecord r) {
        String group=group(r);
        if(!DrawingLevel.groupVisible(drawingLevel,group)||!DrawingLevel.recordVisible(drawingLevel,r))return false;
        for(int i=0;i<categories.length;i++) if(categories[i].equals(group))
            return layers[i] && layerPrefs().getBoolean("sublayer_"+LayerGroups.key(r),true);
        return false;
    }

    private void showLayerSettings() {
        new AlertDialog.Builder(this).setTitle("설정 · 레이어 편집")
            .setItems(LayerGroups.NAMES,(dialog,which)->editGroupLayers(categories[which],LayerGroups.NAMES[which]))
            .setNegativeButton("닫기",null).show();
    }

    private void editGroupLayers(String selectedGroup,String title) {
        TreeMap<String,CadRecord> representatives=new TreeMap<>();
        Map<String,Integer> counts=new HashMap<>();
        for(CadRecord r:allRecords) {
            if(!selectedGroup.equals(group(r)))continue;
            String key=LayerGroups.key(r); representatives.put(key,r);
            counts.put(key,counts.containsKey(key)?counts.get(key)+1:1);
        }
        if(server!=null){
            representatives.clear();counts.clear();
            for(int i=0;i<serverLayers.length();i++){
                org.json.JSONObject info=serverLayers.optJSONObject(i);if(info==null)continue;
                CadRecord r=new CadRecord();r.layer=info.optString("layer");
                String sourceGroup=info.optString("group_id");r.category=sourceGroup.equals("POLE")?"FACILITY":sourceGroup;
                if(selectedGroup.equals(group(r))){representatives.put(r.layer,r);counts.put(r.layer,info.optInt("object_count"));}
            }
        }
        android.widget.ScrollView scroll=new android.widget.ScrollView(this);
        LinearLayout body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(12),dp(8),dp(12),dp(8));scroll.addView(body);
        TextView help=new TextView(this);
        help.setText("체크한 레이어만 표시합니다. 그룹을 껐다 켜도 선택 상태가 유지됩니다. 아래 목록에서 소속 그룹을 변경할 수 있습니다.");
        body.addView(help);
        if(representatives.isEmpty()){TextView empty=new TextView(this);empty.setText("불러온 레이어가 없습니다.");body.addView(empty);}
        for(Map.Entry<String,CadRecord> entry:representatives.entrySet()) {
            String key=entry.getKey();
            CheckBox check=new CheckBox(this);check.setText(key+" · "+counts.get(key)+"행");
            check.setChecked(layerPrefs().getBoolean("sublayer_"+key,true));
            check.setOnCheckedChangeListener((button,checked)->layerPrefs().edit().putBoolean("sublayer_"+key,checked).apply());
            body.addView(check);
            android.widget.Spinner assignment=new android.widget.Spinner(this);
            assignment.setAdapter(new android.widget.ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,LayerGroups.NAMES));
            int initial=Arrays.asList(categories).indexOf(selectedGroup);assignment.setSelection(initial);
            assignment.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){
                public void onItemSelected(android.widget.AdapterView<?> parent,android.view.View view,int position,long id){
                    layerPrefs().edit().putString("assignment_"+key,categories[position]).apply();
                }
                public void onNothingSelected(android.widget.AdapterView<?> parent){}
            });
            body.addView(assignment);
        }
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle(title+" · 레이어 편집").setView(scroll)
            .setPositiveButton("완료",null).create();
        dialog.setOnDismissListener(d->loadMarkers());dialog.show();
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
            if(mapReady && networkRenderer==null) map.addNetworkLine(points,isFiber);
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
        TextView address=new TextView(this);address.setText(ServerApiClient.BASE_URL);body.addView(address);
        getSharedPreferences("server_prefs",MODE_PRIVATE).edit().remove("url").apply();
        android.widget.EditText username=new android.widget.EditText(this);username.setSingleLine(true);username.setHint("앱 계정");username.setText("ysjus");body.addView(username);
        android.widget.EditText password=new android.widget.EditText(this);password.setSingleLine(true);password.setHint("앱 비밀번호");
        password.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);
        password.setSaveEnabled(false);if(android.os.Build.VERSION.SDK_INT>=26)password.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);body.addView(password);
        loginMessage=new TextView(this);loginMessage.setPadding(0,dp(12),0,dp(12));body.addView(loginMessage);
        Button login=new Button(this);login.setText("로그인");body.addView(login);
        loginScreen.addView(body);screen.addView(loginScreen);
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
        logoutButton.setEnabled(false);connectionStatus.setText("● 로그아웃 · 서버 연결 안 됨");
        allRecords.clear();selectedRecord=null;renderMarkers();serverButton.setEnabled(true);serverButton.setText("서버 로그인");
        regionStatus.setText("서버 연결 해제 · 시설 도면 없음");
        if(previous!=null)serverWorker.execute(previous::logout);
        loadMarkers();stopLocation();showLoginScreen();
    }

    private void chooseServerDataset(){
        cancelServerRequest();serverDataset="";allRecords.clear();renderMarkers();
        final ServerApiClient client=server;if(client==null)return;final int generation=serverGeneration;
        status.setText("허용 지역을 조회하는 중…");
        serverTask=serverWorker.submit(()->{
            try{
                org.json.JSONArray regions=client.regions();ArrayList<String> titles=new ArrayList<>(),ids=new ArrayList<>();
                for(int i=0;i<regions.length();i++){
                    org.json.JSONObject region=regions.getJSONObject(i);org.json.JSONArray datasets=client.datasets(region.getString("id"));
                    for(int j=0;j<datasets.length();j++){org.json.JSONObject dataset=datasets.getJSONObject(j);titles.add(region.getString("name")+" · "+dataset.getString("id"));ids.add(dataset.getString("id"));}
                }
                runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration)return;
                    if(ids.isEmpty()){status.setText("허용 지역에 게시된 자료가 없습니다.");return;}
                    if(ids.size()==1)selectServerDataset(client,ids.get(0),titles.get(0));
                    else new AlertDialog.Builder(this).setTitle("허용 지역 선택").setItems(titles.toArray(new String[0]),(d,i)->selectServerDataset(client,ids.get(i),titles.get(i))).setNegativeButton("닫기",null).show();
                });
            }catch(Exception error){runOnUiThread(()->{if(!destroyed&&generation==serverGeneration){markServerOffline();status.setText(serverMessage(error));}});}
        });
    }

    private void selectServerDataset(ServerApiClient client,String dataset,String title){
        cancelServerRequest();final int generation=serverGeneration;
        serverTask=serverWorker.submit(()->{
            try{
                org.json.JSONObject metadata=client.layers(dataset);
                runOnUiThread(()->{
                    if(destroyed||generation!=serverGeneration||client!=server)return;
                    markServerOnline();serverDataset=dataset;serverRegion=title;serverLayers=metadata.optJSONArray("layers");
                    if(serverLayers==null)serverLayers=new org.json.JSONArray();
                    regionStatus.setText(title+" · 서버 조회");viewportKey="";pendingViewportKey="";
                    org.json.JSONObject box=metadata.optJSONObject("bounds");
                    if(box!=null){
                        serverBounds.clear();serverBounds.add(new MapPoint(box.optDouble("south"),box.optDouble("west")));serverBounds.add(new MapPoint(box.optDouble("north"),box.optDouble("east")));if(mapReady)map.showAll(serverBounds);
                    }else if(mapReady&&currentLocation!=null)map.center(new MapPoint(currentLocation),true);
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
            for(int j=0;j<categories.length;j++)if(categories[j].equals(assigned)&&layers[j]&&DrawingLevel.groupVisible(drawingLevel,assigned)&&layerPrefs().getBoolean("sublayer_"+LayerGroups.key(r),true))selected.add(r.layer);
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
        allRecords.clear();selectedRecord=null;renderMarkers();viewportKey="";
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
                runOnUiThread(()->{if(!destroyed&&foreground&&server==client&&generation==serverGeneration)markServerOnline();});
            }catch(Exception error){
                runOnUiThread(()->{if(!destroyed&&foreground&&server==client&&generation==serverGeneration)markServerOffline();});
            }
        });
    }

    private void pollServerViewport(){
        if(server==null||serverDataset.isEmpty()||!mapReady)return;
        MapViewport viewport=map.viewport();if(viewport==null)return;
        String level=DrawingLevel.forViewport(viewport);
        if(!level.equals(drawingLevel)){drawingLevel=level;renderMarkers();}
        regionStatus.setText(serverRegion+" · "+DrawingLevel.label(drawingLevel));
        String filter=serverLayerFilter(),key=serverDataset+":"+viewport.key()+":"+filter;
        long now=android.os.SystemClock.uptimeMillis();
        if(!key.equals(pendingViewportKey)){pendingViewportKey=key;viewportChangedAt=now;cancelServerRequest();return;}
        if(key.equals(viewportKey)&&now-lastServerFetch>60000)viewportKey="";
        if(key.equals(viewportKey)||now-viewportChangedAt<400)return;
        viewportKey=key;
        lastServerFetch=now;
        if(!viewport.queryable("overview".equals(drawingLevel)?2:.2)){allRecords.clear();renderMarkers();status.setText("자료를 보려면 지도를 확대하세요.");return;}
        if(filter.isEmpty()){allRecords.clear();renderMarkers();return;}
        cancelServerRequest();final int generation=serverGeneration;final ServerApiClient client=server;final String dataset=serverDataset;
        status.setText("지도 영역의 서버 자료를 조회하는 중…");
        serverTask=serverWorker.submit(()->{
            try{
                ArrayList<CadRecord> rows=client.objects(dataset,viewport,filter);
                runOnUiThread(()->{if(destroyed||generation!=serverGeneration)return;markServerOnline();lastServerFetch=android.os.SystemClock.uptimeMillis();allRecords=rows;renderMarkers();regionStatus.setText(serverRegion+" · "+DrawingLevel.label(drawingLevel));});
            }catch(Exception error){runOnUiThread(()->{
                if(destroyed||generation!=serverGeneration)return;
                markServerOffline();status.setText("서버 조회 실패: "+serverMessage(error));
                serverHandler.postDelayed(()->{if(!destroyed&&generation==serverGeneration)viewportKey="";},5000);
            });}
        });
    }

    private void loadServerDetails(CadRecord record,MapPoint point){
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
        selectedRecord=record;selectedMeasurement=null;
        String pole=CadObjectInfo.pole(record);
        selectionStatus.setText("선택: "+record.title()+(pole.isEmpty()?"":" · 전주 "+pole)+" · 길게 누르기/우클릭으로 속성");
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
        if(candidate!=null)selectRecord(candidate,point);
        else {selectedRecord=null;selectedMeasurement=null;selectionStatus.setText("객체를 선택하세요.");}
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
