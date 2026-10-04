package com.example.celldb;

import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

final class CadDatabase {
    private static final String FILE_NAME = "cad_records.json";
    private final Context context;
    private ArrayList<CadRecord> cached;
    private long cachedTime=-1, cachedLength=-1;

    CadDatabase(Context context) { this.context = context.getApplicationContext(); }

    synchronized ArrayList<CadRecord> loadAll() {
        ArrayList<CadRecord> out = new ArrayList<>();
        File file = new File(context.getFilesDir(), FILE_NAME);
        boolean backup=new File(file.getPath()+".bak").exists();
        if (!file.exists() && !backup) return out;
        if(!backup && cached!=null && cachedTime==file.lastModified() && cachedLength==file.length())return new ArrayList<>(cached);
        try {
            try (android.util.JsonReader reader=new android.util.JsonReader(new InputStreamReader(new android.util.AtomicFile(file).openRead(),StandardCharsets.UTF_8))) {
                reader.beginArray();
                while(reader.hasNext()) {
                    CadRecord r=new CadRecord();reader.beginObject();
                    while(reader.hasNext()) {
                        String key=reader.nextName();
                        switch(key) {
                            case "category":r.category=reader.nextString();break;
                            case "id":r.id=reader.nextString();break;
                            case "subtype":r.subtype=reader.nextString();break;
                            case "name":r.name=reader.nextString();break;
                            case "layer":r.layer=reader.nextString();break;
                            case "longitude":r.longitude=reader.nextDouble();break;
                            case "latitude":r.latitude=reader.nextDouble();break;
                            case "sequence":r.sequence=reader.nextInt();break;
                            case "source":r.source=reader.nextString();break;
                            case "fields":
                                reader.beginObject();while(reader.hasNext()){String name=reader.nextName();r.fields.put(name,reader.nextString());}reader.endObject();break;
                            default:reader.skipValue();
                        }
                    }
                    reader.endObject();out.add(r);
                }
                reader.endArray();
            }
            cached=new ArrayList<>(out);cachedTime=file.lastModified();cachedLength=file.length();
        } catch (Exception ignored) { out.clear(); }
        return out;
    }

    synchronized void saveAll(List<CadRecord> records) throws Exception {
        File dest=new File(context.getFilesDir(),FILE_NAME);
        android.util.AtomicFile atomic=new android.util.AtomicFile(dest);
        FileOutputStream stream=atomic.startWrite();
        try {
            Writer writer=new BufferedWriter(new OutputStreamWriter(stream,StandardCharsets.UTF_8));
            writer.write('[');boolean first=true;
            for(CadRecord r:records){if(!first)writer.write(',');writer.write(r.toJson().toString());first=false;}
            writer.write(']');writer.flush();atomic.finishWrite(stream);
        } catch(Exception e) {
            atomic.failWrite(stream);throw e;
        }
        cached=new ArrayList<>(records);cachedTime=dest.lastModified();cachedLength=dest.length();
    }

    synchronized void replaceCadRows(List<CadRecord> imported) throws Exception {
        ArrayList<CadRecord> current = loadAll();
        LinkedHashMap<String,CadRecord> keptOverrides = new LinkedHashMap<>();
        ArrayList<CadRecord> manual = new ArrayList<>();
        for (CadRecord r : current) {
            if (CadRecord.SOURCE_EDITED.equals(r.source)) keptOverrides.put(r.stableKey(), r);
            else if (CadRecord.SOURCE_MANUAL.equals(r.source)) manual.add(r);
        }

        LinkedHashMap<String,CadRecord> merged = new LinkedHashMap<>();
        for (CadRecord r : imported) {
            CadRecord override = keptOverrides.remove(r.stableKey());
            merged.put(r.stableKey(), override != null ? override : r);
        }
        for (CadRecord r : keptOverrides.values()) merged.put(r.stableKey(), r);
        for (CadRecord r : manual) merged.put("MANUAL|" + UUID.randomUUID(), r);
        saveAll(new ArrayList<>(merged.values()));
    }

    synchronized void upsert(CadRecord updated, String oldKey) throws Exception {
        ArrayList<CadRecord> all = loadAll();
        boolean replaced = false;
        for (int i=0; i<all.size(); i++) {
            if (all.get(i).stableKey().equals(oldKey)) {
                all.set(i, updated);
                replaced = true;
                break;
            }
        }
        if (!replaced) all.add(updated);
        saveAll(all);
    }

    synchronized void deleteByKey(String key) throws Exception {
        ArrayList<CadRecord> all = loadAll();
        for (int i=all.size()-1; i>=0; i--) if (all.get(i).stableKey().equals(key)) all.remove(i);
        saveAll(all);
    }
}
