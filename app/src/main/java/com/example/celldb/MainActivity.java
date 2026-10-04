package com.example.celldb;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.*;
import java.util.*;

public class MainActivity extends Activity {
    private static final int REQ_XLSX = 3001;
    private final String[] categories = {"CELL","FACILITY","EQUIPMENT","FIBER","COAX"};

    private CadDatabase db;
    private Spinner category;
    private EditText id, name, subtype, longitude, latitude, note, sequence;
    private LinearLayout listBox;
    private TextView summary;
    private CadRecord editing;
    private final java.util.concurrent.ExecutorService worker=java.util.concurrent.Executors.newSingleThreadExecutor();
    private boolean destroyed;
    private Button importBtn;
    private int refreshGeneration;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        db = new CadDatabase(this);
        buildUi();
        refresh();
    }

    private int dp(int v){ return Math.round(v * getResources().getDisplayMetrics().density); }

    private Button button(String text){
        Button b=new Button(this);
        b.setText(text);
        b.setMinHeight(dp(48));
        return b;
    }

    private EditText input(String hint){
        EditText e=new EditText(this);
        e.setHint(hint);
        e.setSingleLine(true);
        e.setPadding(dp(10),dp(8),dp(10),dp(8));
        return e;
    }

    private void buildUi(){
        LinearLayout root=new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setOnApplyWindowInsetsListener((view,insets)->{
            view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets;
        });
        root.setBackgroundColor(Color.rgb(246,247,249));

        TextView header=new TextView(this);
        header.setText("CAD 네트워크 데이터 관리");
        header.setTextColor(Color.WHITE);
        header.setTextSize(20);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(16),dp(14),dp(16),dp(14));
        header.setBackgroundColor(Color.rgb(15,23,42));
        root.addView(header);

        LinearLayout top=new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        importBtn=button("CAD Excel 불러오기");
        Button mapBtn=button("지도 보기");
        top.addView(importBtn,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
        top.addView(mapBtn,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
        root.addView(top);

        importBtn.setOnClickListener(v -> {
            Intent i=new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            i.setType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet");
            startActivityForResult(i,REQ_XLSX);
        });
        mapBtn.setOnClickListener(v -> finish());

        ScrollView scroll=new ScrollView(this);
        LinearLayout body=new LinearLayout(this);
        body.setOrientation(LinearLayout.VERTICAL);
        body.setPadding(dp(12),dp(8),dp(12),dp(24));
        scroll.addView(body);
        root.addView(scroll,new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,0,1f));

        summary=new TextView(this);
        summary.setTextSize(14);
        summary.setPadding(dp(8),dp(8),dp(8),dp(8));
        body.addView(summary);

        category=new Spinner(this);
        category.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,categories));
        body.addView(category);
        category.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            public void onItemSelected(android.widget.AdapterView<?> p, android.view.View v, int pos, long id){ if(editing==null) refresh(); }
            public void onNothingSelected(android.widget.AdapterView<?> p){}
        });

        id=input("ID (시설ID / 장비ID / 선로ID / 셀번호)");
        name=input("구분 또는 이름");
        subtype=input("블록명 / 케이블ID / 셀구분");
        longitude=input("경도");
        latitude=input("위도");
        note=input("비고");
        sequence=input("선로점 순번 (광/동축 선로)");
        sequence.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        longitude.setInputType(android.text.InputType.TYPE_CLASS_NUMBER|android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL|android.text.InputType.TYPE_NUMBER_FLAG_SIGNED);
        latitude.setInputType(longitude.getInputType());

        body.addView(label("ID")); body.addView(id);
        body.addView(label("이름/구분")); body.addView(name);
        body.addView(label("세부유형")); body.addView(subtype);
        body.addView(label("경도")); body.addView(longitude);
        body.addView(label("위도")); body.addView(latitude);
        body.addView(label("비고")); body.addView(note);
        body.addView(label("선로점 순번 (광/동축)")); body.addView(sequence);

        LinearLayout actions=new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        Button save=button("등록 / 저장");
        Button clear=button("초기화");
        actions.addView(save,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
        actions.addView(clear,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
        body.addView(actions);
        save.setOnClickListener(v -> saveRecord());
        clear.setOnClickListener(v -> clearForm());

        listBox=new LinearLayout(this);
        listBox.setOrientation(LinearLayout.VERTICAL);
        body.addView(listBox);

        setContentView(root);
    }

    private TextView label(String text){
        TextView t=new TextView(this);
        t.setText(text);
        t.setTextSize(13);
        t.setPadding(0,dp(8),0,dp(3));
        return t;
    }

    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        super.onActivityResult(requestCode,resultCode,data);
        if(requestCode!=REQ_XLSX || resultCode!=RESULT_OK || data==null || data.getData()==null) return;
        Uri uri=data.getData();
        importBtn.setEnabled(false);
        worker.execute(()->{
            try {
                ArrayList<CadRecord> imported=XlsxCadImporter.read(this,uri);
                if(destroyed) return;
                db.replaceCadRows(imported);
                runOnUiThread(()->{
                    if(destroyed) return;
                    importBtn.setEnabled(true);
                    Toast.makeText(this,"CAD 데이터 "+imported.size()+"건을 불러왔습니다.",Toast.LENGTH_LONG).show();
                    refresh();
                });
            } catch(Exception e) {
                runOnUiThread(()->{
                    if(destroyed) return;
                    importBtn.setEnabled(true);
                    Toast.makeText(this,"Excel 불러오기 오류: "+e.getMessage(),Toast.LENGTH_LONG).show();
                });
            }
        });
    }

    @Override protected void onDestroy(){ destroyed=true; worker.shutdownNow(); super.onDestroy(); }

    private void saveRecord(){
        String cat=(String)category.getSelectedItem();
        String rid=id.getText().toString().trim();
        if(rid.isEmpty()){
            Toast.makeText(this,"ID를 입력해주세요.",Toast.LENGTH_SHORT).show();
            return;
        }

        CadRecord r=new CadRecord();
        if(editing!=null) { r.fields.putAll(editing.fields); r.layer=editing.layer; r.sequence=editing.sequence; }
        r.category=cat;
        r.id=rid;
        r.name=name.getText().toString().trim();
        r.subtype=subtype.getText().toString().trim();
        r.source = editing==null ? CadRecord.SOURCE_MANUAL :
                (CadRecord.SOURCE_CAD.equals(editing.source) ? CadRecord.SOURCE_EDITED : editing.source);
        try{
            r.longitude=Double.parseDouble(longitude.getText().toString().trim());
            r.latitude=Double.parseDouble(latitude.getText().toString().trim());
        }catch(Exception e){
            Toast.makeText(this,"경도/위도를 확인해주세요.",Toast.LENGTH_SHORT).show();
            return;
        }
        if(!r.hasCoordinates()) {
            Toast.makeText(this,"경도는 -180~180, 위도는 -90~90 범위로 입력해주세요.",Toast.LENGTH_LONG).show(); return;
        }
        if("FIBER".equals(cat)||"COAX".equals(cat)) {
            try { r.sequence=Integer.parseInt(sequence.getText().toString().trim()); }
            catch(Exception error) { Toast.makeText(this,"선로점 순번을 입력해주세요.",Toast.LENGTH_LONG).show(); return; }
            if(r.sequence<0) { Toast.makeText(this,"선로점 순번은 0 이상이어야 합니다.",Toast.LENGTH_LONG).show(); return; }
            r.fields.put("순번",Integer.toString(r.sequence));
        }
        r.fields.put("비고",note.getText().toString().trim());
        r.fields.put("경도",Double.toString(r.longitude));
        r.fields.put("위도",Double.toString(r.latitude));
        if("CELL".equals(cat)) {
            r.fields.put("셀번호",r.id); r.fields.put("셀명",r.name); r.fields.put("셀구분",r.subtype);
        } else if("FACILITY".equals(cat)||"EQUIPMENT".equals(cat)) {
            r.fields.put("FACILITY".equals(cat)?"시설ID":"장비ID",r.id);
            r.fields.put("구분",r.name); r.fields.put("블록명",r.subtype);
        } else {
            r.fields.put("선로ID",r.id); r.fields.put("케이블명",r.name); r.fields.put("케이블ID",r.subtype);
        }

        String oldKey=editing==null ? "__NEW__"+UUID.randomUUID() : editing.stableKey();
        try{
            db.upsert(r,oldKey);
            Toast.makeText(this,editing==null?"등록했습니다.":"수정했습니다.",Toast.LENGTH_SHORT).show();
            clearForm();
            refresh();
        }catch(Exception e){
            Toast.makeText(this,"저장 오류: "+e.getMessage(),Toast.LENGTH_LONG).show();
        }
    }

    private void edit(CadRecord r){
        editing=r;
        int pos=Arrays.asList(categories).indexOf(r.category);
        if(pos>=0) category.setSelection(pos);
        id.setText(r.id);
        name.setText(r.name);
        subtype.setText(r.subtype);
        longitude.setText(r.hasCoordinates()?Double.toString(r.longitude):"");
        latitude.setText(r.hasCoordinates()?Double.toString(r.latitude):"");
        note.setText(r.fields.containsKey("비고") ? r.fields.get("비고") : "");
        sequence.setText(("FIBER".equals(r.category)||"COAX".equals(r.category)) ? Integer.toString(r.sequence) : "");
        Toast.makeText(this,"수정 모드: "+r.title(),Toast.LENGTH_SHORT).show();
    }

    private void clearForm(){
        editing=null;
        id.setText(""); name.setText(""); subtype.setText("");
        longitude.setText(""); latitude.setText(""); note.setText(""); sequence.setText("");
    }

    private void delete(CadRecord r){
        new AlertDialog.Builder(this)
                .setTitle("삭제")
                .setMessage(r.title()+" 항목을 삭제하시겠습니까?")
                .setNegativeButton("취소",null)
                .setPositiveButton("삭제",(d,w)->{
                    try{ db.deleteByKey(r.stableKey()); refresh(); }
                    catch(Exception e){ Toast.makeText(this,"삭제 오류: "+e.getMessage(),Toast.LENGTH_LONG).show(); }
                }).show();
    }

    private void refresh(){
        if(listBox==null) return;
        final int generation=++refreshGeneration;
        worker.execute(()->{
            ArrayList<CadRecord> all=db.loadAll();
            runOnUiThread(()->{if(!destroyed && generation==refreshGeneration)renderList(all);});
        });
    }

    private void renderList(ArrayList<CadRecord> all){
        LinkedHashMap<String,Integer> counts=new LinkedHashMap<>();
        for(String c:categories) counts.put(c,0);
        for(CadRecord r:all) counts.put(r.category,(counts.containsKey(r.category)?counts.get(r.category):0)+1);

        summary.setText("전체 "+all.size()+"건  ·  CELL "+counts.get("CELL")
                +" / 시설 "+counts.get("FACILITY")
                +" / 장비 "+counts.get("EQUIPMENT")
                +" / 광선로 "+counts.get("FIBER")
                +" / 동축 "+counts.get("COAX"));

        String selected=(String)category.getSelectedItem();
        listBox.removeAllViews();
        int shown=0;
        for(CadRecord r:all){
            if(!selected.equals(r.category)) continue;
            shown++;
            LinearLayout card=new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(dp(10),dp(8),dp(10),dp(8));
            card.setBackgroundColor(Color.WHITE);

            TextView t=new TextView(this);
            t.setText(r.title()+"\n"+r.subtype
                    +(r.hasCoordinates()?"\n"+r.latitude+", "+r.longitude:"")
                    +"\n출처: "+r.source);
            card.addView(t);

            LinearLayout row=new LinearLayout(this);
            Button edit=button("수정");
            Button del=button("삭제");
            row.addView(edit,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
            row.addView(del,new LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f));
            card.addView(row);
            edit.setOnClickListener(v -> edit(r));
            del.setOnClickListener(v -> delete(r));

            LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.setMargins(0,0,0,dp(8));
            listBox.addView(card,lp);

            if(shown>=200){
                TextView more=new TextView(this);
                more.setText("목록은 성능을 위해 200건까지만 표시합니다. 지도에는 전체 데이터가 사용됩니다.");
                more.setPadding(0,dp(8),0,dp(8));
                listBox.addView(more);
                break;
            }
        }
    }
}
