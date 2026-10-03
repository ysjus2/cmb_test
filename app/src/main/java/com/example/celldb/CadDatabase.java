package com.example.celldb;

import android.content.Context;
import org.json.JSONArray;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

final class CadDatabase {
    private static final String FILE_NAME = "cad_records.json";
    private final Context context;

    CadDatabase(Context context) { this.context = context.getApplicationContext(); }

    synchronized ArrayList<CadRecord> loadAll() {
        ArrayList<CadRecord> out = new ArrayList<>();
        File file = new File(context.getFilesDir(), FILE_NAME);
        if (!file.exists()) return out;
        try {
            byte[] bytes = new byte[(int) file.length()];
            try (InputStream in = new FileInputStream(file)) {
                int off = 0, n;
                while (off < bytes.length && (n = in.read(bytes, off, bytes.length - off)) > 0) off += n;
            }
            JSONArray a = new JSONArray(new String(bytes, StandardCharsets.UTF_8));
            for (int i=0; i<a.length(); i++) out.add(CadRecord.fromJson(a.getJSONObject(i)));
        } catch (Exception ignored) { }
        return out;
    }

    synchronized void saveAll(List<CadRecord> records) throws Exception {
        JSONArray a = new JSONArray();
        for (CadRecord r : records) a.put(r.toJson());
        File temp = new File(context.getFilesDir(), FILE_NAME + ".tmp");
        try (OutputStream out = new FileOutputStream(temp)) {
            out.write(a.toString().getBytes(StandardCharsets.UTF_8));
            out.flush();
        }
        File dest = new File(context.getFilesDir(), FILE_NAME);
        if (dest.exists() && !dest.delete()) throw new IOException("기존 DB를 교체할 수 없습니다.");
        if (!temp.renameTo(dest)) throw new IOException("DB 저장을 완료할 수 없습니다.");
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
