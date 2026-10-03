package com.example.celldb;

import org.json.JSONObject;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;

final class CadRecord {
    static final String SOURCE_CAD = "CAD";
    static final String SOURCE_MANUAL = "MANUAL";
    static final String SOURCE_EDITED = "EDITED";

    String category = "";
    String id = "";
    String subtype = "";
    String name = "";
    String layer = "";
    double longitude = Double.NaN;
    double latitude = Double.NaN;
    int sequence = 0;
    String source = SOURCE_CAD;
    final LinkedHashMap<String, String> fields = new LinkedHashMap<>();

    boolean hasCoordinates() {
        return !Double.isNaN(latitude) && !Double.isInfinite(latitude)
                && !Double.isNaN(longitude) && !Double.isInfinite(longitude)
                && latitude >= -90 && latitude <= 90 && longitude >= -180 && longitude <= 180;
    }

    String stableKey() {
        String base = category + "|" + id;
        if ("FIBER".equals(category) || "COAX".equals(category)) base += "|" + sequence;
        return base;
    }

    String title() {
        if (!name.isEmpty() && !id.isEmpty()) return name + " / " + id;
        if (!id.isEmpty()) return category + " / " + id;
        return category;
    }

    JSONObject toJson() throws Exception {
        JSONObject o = new JSONObject();
        o.put("category", category);
        o.put("id", id);
        o.put("subtype", subtype);
        o.put("name", name);
        o.put("layer", layer);
        if (hasCoordinates()) {
            o.put("longitude", longitude);
            o.put("latitude", latitude);
        }
        o.put("sequence", sequence);
        o.put("source", source);
        JSONObject f = new JSONObject();
        for (Map.Entry<String,String> e : fields.entrySet()) f.put(e.getKey(), e.getValue());
        o.put("fields", f);
        return o;
    }

    static CadRecord fromJson(JSONObject o) {
        CadRecord r = new CadRecord();
        r.category = o.optString("category", "");
        r.id = o.optString("id", "");
        r.subtype = o.optString("subtype", "");
        r.name = o.optString("name", "");
        r.layer = o.optString("layer", "");
        r.longitude = o.has("longitude") ? o.optDouble("longitude", Double.NaN) : Double.NaN;
        r.latitude = o.has("latitude") ? o.optDouble("latitude", Double.NaN) : Double.NaN;
        r.sequence = o.optInt("sequence", 0);
        r.source = o.optString("source", SOURCE_CAD);
        JSONObject f = o.optJSONObject("fields");
        if (f != null) {
            Iterator<String> keys = f.keys();
            while (keys.hasNext()) {
                String k = keys.next();
                r.fields.put(k, f.optString(k, ""));
            }
        }
        return r;
    }
}
