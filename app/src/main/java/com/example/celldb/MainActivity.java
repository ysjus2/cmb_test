package com.example.celldb;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.*;
import android.graphics.Color;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.*;

public class MainActivity extends Activity {

    private static final int REQ_LOCATION = 1001;
    private static final int REQ_EXPORT = 1002;
    private static final int REQ_IMPORT = 1003;
    private static final String PREFS = "cell_db_prefs";
    private static final String KEY_DB = "db_json";

    private EditText cellName, cellNumber, upperOffice, upPort, downPort, address, poleNumber, longitude, latitude, note;
    private Spinner cellType;
    private TextView status, countText;
    private LinearLayout recordsBox;
    private ArrayList<CellRecord> records = new ArrayList<>();
    private int editIndex = -1;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        loadRecords();
        buildUi();
        renderRecords();
        requestLocationAndFetch();
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density + 0.5f);
    }

    private TextView label(String text) {
        TextView v = new TextView(this);
        v.setText(text);
        v.setTextSize(13);
        v.setTextColor(Color.DKGRAY);
        v.setPadding(0, dp(8), 0, dp(4));
        return v;
    }

    private EditText input(String hint) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setTextSize(16);
        e.setSingleLine(true);
        e.setPadding(dp(12), dp(10), dp(12), dp(10));
        e.setBackgroundResource(android.R.drawable.edit_text);
        return e;
    }

    private Button btn(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setMinHeight(dp(48));
        return b;
    }

    private void addField(LinearLayout parent, String title, EditText e) {
        parent.addView(label(title));
        parent.addView(e, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(246,247,249));

        TextView header = new TextView(this);
        header.setText("셀 위치 DB");
        header.setTextColor(Color.WHITE);
        header.setTextSize(20);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(16), dp(14), dp(16), dp(14));
        header.setBackgroundColor(Color.rgb(15,23,42));
        root.addView(header, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        ScrollView scroll = new ScrollView(this);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(12), dp(8), dp(12), dp(24));
        scroll.addView(content);
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        status = new TextView(this);
        status.setText("위치정보 확인 중...");
        status.setTextSize(14);
        status.setPadding(dp(12), dp(12), dp(12), dp(12));
        status.setBackgroundColor(Color.rgb(238,242,255));
        content.addView(status);

        Button locationBtn = btn("현재 위치 다시 가져오기");
        locationBtn.setOnClickListener(v -> requestLocationAndFetch());
        content.addView(locationBtn);

        Button mapBtn = btn("ONU 지도 보기");
        mapBtn.setOnClickListener(v -> startActivity(new Intent(this, MapActivity.class)));
        content.addView(mapBtn);

        cellName = input("예: 역삼-01");
        cellNumber = input("예: C-0001");
        upperOffice = input("상위국사");
        upPort = input("상향포트");
        downPort = input("하향포트");
        address = input("주소");
        poleNumber = input("전주번호");
        longitude = input("127.xxxxxxx");
        latitude = input("37.xxxxxxx");
        note = input("비고");

        longitude.setInputType(android.text.InputType.TYPE_CLASS_NUMBER |
                android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL |
                android.text.InputType.TYPE_NUMBER_FLAG_SIGNED);
        latitude.setInputType(longitude.getInputType());

        addField(content, "셀명", cellName);
        addField(content, "셀번호", cellNumber);
        addField(content, "상위국사", upperOffice);
        addField(content, "상향포트", upPort);
        addField(content, "하향포트", downPort);
        addField(content, "주소", address);
        addField(content, "전주번호", poleNumber);
        addField(content, "경도", longitude);
        addField(content, "위도", latitude);

        content.addView(label("셀구분"));
        cellType = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(
                this, android.R.layout.simple_spinner_dropdown_item,
                new String[]{"일반", "아파트"});
        cellType.setAdapter(adapter);
        content.addView(cellType);

        addField(content, "비고", note);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        Button save = btn("저장");
        Button clear = btn("초기화");
        row.addView(save, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row.addView(clear, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        content.addView(row);

        save.setOnClickListener(v -> saveCurrent());
        clear.setOnClickListener(v -> clearForm());

        LinearLayout csvRow = new LinearLayout(this);
        csvRow.setOrientation(LinearLayout.HORIZONTAL);
        Button export = btn("CSV 추출");
        Button importBtn = btn("CSV 불러오기");
        csvRow.addView(export, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        csvRow.addView(importBtn, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        content.addView(csvRow);

        export.setOnClickListener(v -> exportCsv());
        importBtn.setOnClickListener(v -> importCsv());

        countText = new TextView(this);
        countText.setTextSize(16);
        countText.setPadding(0, dp(16), 0, dp(8));
        content.addView(countText);

        recordsBox = new LinearLayout(this);
        recordsBox.setOrientation(LinearLayout.VERTICAL);
        content.addView(recordsBox);

        setContentView(root);
    }

    private void setStatus(String s) {
        status.setText(s);
    }

    private void requestLocationAndFetch() {
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
            }, REQ_LOCATION);
        } else {
            fetchLocation();
        }
    }

    @SuppressWarnings("MissingPermission")
    private void fetchLocation() {
        LocationManager lm = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        boolean gps = lm.isProviderEnabled(LocationManager.GPS_PROVIDER);
        boolean net = lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER);

        if (!gps && !net) {
            setStatus("휴대폰 위치 기능이 꺼져 있습니다. 위치를 켜주세요.");
            Intent i = new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS);
            startActivity(i);
            return;
        }

        setStatus("현재 위치 확인 중...");

        Location best = null;
        if (gps) best = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER);
        if (net) {
            Location n = lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER);
            if (best == null || (n != null && n.getAccuracy() < best.getAccuracy())) best = n;
        }
        if (best != null) applyLocation(best);

        final LocationManager manager = lm;
        LocationListener listener = new LocationListener() {
            @Override public void onLocationChanged(Location loc) {
                applyLocation(loc);
                try { manager.removeUpdates(this); } catch (Exception ignored) {}
            }
            @Override public void onProviderEnabled(String provider) {}
            @Override public void onProviderDisabled(String provider) {}
            @Override public void onStatusChanged(String provider, int status, Bundle extras) {}
        };

        try {
            if (gps) {
                lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, 0, 0, listener);
            } else if (net) {
                lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, 0, 0, listener);
            }
        } catch (SecurityException e) {
            setStatus("위치 권한이 필요합니다.");
        }
    }

    private void applyLocation(Location loc) {
        latitude.setText(String.format(Locale.US, "%.7f", loc.getLatitude()));
        longitude.setText(String.format(Locale.US, "%.7f", loc.getLongitude()));
        setStatus("현재 위치 확인 완료 · 정확도 약 ±" + Math.round(loc.getAccuracy()) + "m");
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_LOCATION) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                fetchLocation();
            } else {
                setStatus("위치 권한이 거부되었습니다. 설정에서 위치 권한을 허용해주세요.");
            }
        }
    }

    private CellRecord formToRecord() {
        String name = cellName.getText().toString().trim();
        String number = cellNumber.getText().toString().trim();
        String lat = latitude.getText().toString().trim();
        String lon = longitude.getText().toString().trim();

        if (name.isEmpty() || number.isEmpty()) {
            Toast.makeText(this, "셀명과 셀번호를 입력해주세요.", Toast.LENGTH_SHORT).show();
            return null;
        }
        try {
            if (!MapActivity.validCoordinates(Double.parseDouble(lat), Double.parseDouble(lon))) {
                throw new IllegalArgumentException("좌표 범위 오류");
            }
        } catch (Exception e) {
            Toast.makeText(this, "위도/경도를 확인해주세요.", Toast.LENGTH_SHORT).show();
            return null;
        }

        CellRecord r = new CellRecord();
        r.cellName = name;
        r.cellNumber = number;
        r.upperOffice = upperOffice.getText().toString().trim();
        r.upPort = upPort.getText().toString().trim();
        r.downPort = downPort.getText().toString().trim();
        r.address = address.getText().toString().trim();
        r.poleNumber = poleNumber.getText().toString().trim();
        r.longitude = lon;
        r.latitude = lat;
        r.cellType = cellType.getSelectedItem().toString();
        r.note = note.getText().toString().trim();
        return r;
    }

    private void saveCurrent() {
        CellRecord r = formToRecord();
        if (r == null) return;

        if (editIndex >= 0 && editIndex < records.size()) {
            records.set(editIndex, r);
            Toast.makeText(this, "수정했습니다.", Toast.LENGTH_SHORT).show();
        } else {
            records.add(r);
            Toast.makeText(this, "휴대폰에 저장했습니다.", Toast.LENGTH_SHORT).show();
        }
        persistRecords();
        clearForm();
        renderRecords();
    }

    private void clearForm() {
        cellName.setText("");
        cellNumber.setText("");
        upperOffice.setText("");
        upPort.setText("");
        downPort.setText("");
        address.setText("");
        poleNumber.setText("");
        note.setText("");
        editIndex = -1;
        // 좌표는 현장에서 연속 입력할 수 있으므로 유지
    }

    private void editRecord(int index) {
        CellRecord r = records.get(index);
        cellName.setText(r.cellName);
        cellNumber.setText(r.cellNumber);
        upperOffice.setText(r.upperOffice);
        upPort.setText(r.upPort);
        downPort.setText(r.downPort);
        address.setText(r.address);
        poleNumber.setText(r.poleNumber);
        longitude.setText(r.longitude);
        latitude.setText(r.latitude);
        cellType.setSelection("아파트".equals(r.cellType) ? 1 : 0);
        note.setText(r.note);
        editIndex = index;
        setStatus("수정 모드: " + r.cellName);
    }

    private void renderRecords() {
        countText.setText("저장된 셀 " + records.size() + "건");
        recordsBox.removeAllViews();

        for (int i = 0; i < records.size(); i++) {
            final int idx = i;
            CellRecord r = records.get(i);

            LinearLayout card = new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(12), dp(10), dp(12), dp(10));
            card.setBackgroundColor(Color.WHITE);

            TextView t = new TextView(this);
            t.setText(r.cellName + "  /  " + r.cellNumber +
                    "\n상위국사: " + r.upperOffice +
                    "\n포트: " + r.upPort + " → " + r.downPort +
                    "\n전주번호: " + r.poleNumber +
                    "\n좌표: " + r.latitude + ", " + r.longitude +
                    "\n셀구분: " + r.cellType +
                    "\n주소: " + r.address +
                    (r.note.isEmpty() ? "" : "\n비고: " + r.note));
            t.setTextSize(14);
            card.addView(t);

            LinearLayout actions = new LinearLayout(this);
            actions.setOrientation(LinearLayout.HORIZONTAL);
            Button edit = btn("수정");
            Button del = btn("삭제");
            actions.addView(edit, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            actions.addView(del, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            card.addView(actions);

            edit.setOnClickListener(v -> editRecord(idx));
            del.setOnClickListener(v -> {
                records.remove(idx);
                persistRecords();
                renderRecords();
            });

            LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            cp.setMargins(0, 0, 0, dp(10));
            recordsBox.addView(card, cp);
        }
    }

    private void persistRecords() {
        try {
            JSONArray a = new JSONArray();
            for (CellRecord r : records) a.put(r.toJson());
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_DB, a.toString()).apply();
        } catch (Exception e) {
            Toast.makeText(this, "저장 오류: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void loadRecords() {
        records.clear();
        String raw = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_DB, "[]");
        try {
            JSONArray a = new JSONArray(raw);
            for (int i = 0; i < a.length(); i++) records.add(CellRecord.fromJson(a.getJSONObject(i)));
        } catch (Exception ignored) {}
    }

    private void exportCsv() {
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("text/csv");
        String date = new SimpleDateFormat("yyyy-MM-dd", Locale.KOREA).format(new Date());
        i.putExtra(Intent.EXTRA_TITLE, "셀위치DB_" + date + ".csv");
        startActivityForResult(i, REQ_EXPORT);
    }

    private void importCsv() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("*/*");
        startActivityForResult(i, REQ_IMPORT);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null || data.getData() == null) return;
        Uri uri = data.getData();

        try {
            if (requestCode == REQ_EXPORT) {
                writeCsv(uri);
                Toast.makeText(this, "CSV를 저장했습니다.", Toast.LENGTH_SHORT).show();
            } else if (requestCode == REQ_IMPORT) {
                readCsv(uri);
                persistRecords();
                renderRecords();
                Toast.makeText(this, "CSV를 불러왔습니다.", Toast.LENGTH_SHORT).show();
            }
        } catch (Exception e) {
            Toast.makeText(this, "파일 처리 오류: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    private void writeCsv(Uri uri) throws Exception {
        OutputStream os = getContentResolver().openOutputStream(uri);
        if (os == null) throw new IOException("파일을 열 수 없습니다.");
        BufferedWriter w = new BufferedWriter(new OutputStreamWriter(os, StandardCharsets.UTF_8));
        w.write('\ufeff');
        w.write("셀명,셀번호,상위국사,상향포트,하향포트,주소,전주번호,경도,위도,셀구분,비고\r\n");
        for (CellRecord r : records) {
            w.write(csv(r.cellName)+","+csv(r.cellNumber)+","+csv(r.upperOffice)+","+csv(r.upPort)+","+
                    csv(r.downPort)+","+csv(r.address)+","+csv(r.poleNumber)+","+csv(r.longitude)+","+
                    csv(r.latitude)+","+csv(r.cellType)+","+csv(r.note)+"\r\n");
        }
        w.flush();
        w.close();
    }

    private void readCsv(Uri uri) throws Exception {
        InputStream is = getContentResolver().openInputStream(uri);
        if (is == null) throw new IOException("파일을 열 수 없습니다.");
        BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8));
        ArrayList<String[]> rows = new ArrayList<>();
        StringBuilder all = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) all.append(line).append("\n");
        br.close();

        rows = parseCsv(all.toString());
        if (rows.size() < 1) return;

        String[] header = rows.get(0);
        Map<String,Integer> idx = new HashMap<>();
        for (int i=0;i<header.length;i++) {
            idx.put(header[i].replace("\uFEFF","").trim(), i);
        }

        ArrayList<CellRecord> imported = new ArrayList<>();
        for (int i=1;i<rows.size();i++) {
            String[] row = rows.get(i);
            if (row.length == 0) continue;
            CellRecord r = new CellRecord();
            r.cellName = val(row, idx.get("셀명"));
            r.cellNumber = val(row, idx.get("셀번호"));
            r.upperOffice = val(row, idx.get("상위국사"));
            r.upPort = val(row, idx.get("상향포트"));
            r.downPort = val(row, idx.get("하향포트"));
            r.address = val(row, idx.get("주소"));
            r.poleNumber = val(row, idx.get("전주번호"));
            r.longitude = val(row, idx.get("경도"));
            r.latitude = val(row, idx.get("위도"));
            r.cellType = val(row, idx.get("셀구분"));
            r.note = val(row, idx.get("비고"));
            if (!r.cellName.isEmpty() || !r.cellNumber.isEmpty()) imported.add(r);
        }
        records = imported;
    }

    private String val(String[] row, Integer i) {
        if (i == null || i < 0 || i >= row.length) return "";
        return row[i];
    }

    private String csv(String s) {
        if (s == null) return "";
        if (s.contains(",") || s.contains("\"") || s.contains("\n") || s.contains("\r")) {
            return "\"" + s.replace("\"", "\"\"") + "\"";
        }
        return s;
    }

    private ArrayList<String[]> parseCsv(String text) {
        ArrayList<String[]> out = new ArrayList<>();
        ArrayList<String> row = new ArrayList<>();
        StringBuilder cell = new StringBuilder();
        boolean quote = false;

        for (int i=0;i<text.length();i++) {
            char c = text.charAt(i);
            if (quote) {
                if (c == '"') {
                    if (i + 1 < text.length() && text.charAt(i+1) == '"') {
                        cell.append('"'); i++;
                    } else quote = false;
                } else cell.append(c);
            } else {
                if (c == '"') quote = true;
                else if (c == ',') { row.add(cell.toString()); cell.setLength(0); }
                else if (c == '\n') {
                    row.add(cell.toString().replace("\r",""));
                    cell.setLength(0);
                    out.add(row.toArray(new String[0]));
                    row = new ArrayList<>();
                } else cell.append(c);
            }
        }
        if (cell.length() > 0 || !row.isEmpty()) {
            row.add(cell.toString().replace("\r",""));
            out.add(row.toArray(new String[0]));
        }
        return out;
    }

    static class CellRecord {
        String cellName="", cellNumber="", upperOffice="", upPort="", downPort="", address="",
                poleNumber="", longitude="", latitude="", cellType="일반", note="";

        JSONObject toJson() throws Exception {
            JSONObject o = new JSONObject();
            o.put("cellName", cellName); o.put("cellNumber", cellNumber); o.put("upperOffice", upperOffice);
            o.put("upPort", upPort); o.put("downPort", downPort); o.put("address", address);
            o.put("poleNumber", poleNumber); o.put("longitude", longitude); o.put("latitude", latitude);
            o.put("cellType", cellType); o.put("note", note);
            return o;
        }

        static CellRecord fromJson(JSONObject o) {
            CellRecord r = new CellRecord();
            r.cellName=o.optString("cellName"); r.cellNumber=o.optString("cellNumber");
            r.upperOffice=o.optString("upperOffice"); r.upPort=o.optString("upPort");
            r.downPort=o.optString("downPort"); r.address=o.optString("address");
            r.poleNumber=o.optString("poleNumber"); r.longitude=o.optString("longitude");
            r.latitude=o.optString("latitude"); r.cellType=o.optString("cellType","일반");
            r.note=o.optString("note");
            return r;
        }
    }
}
