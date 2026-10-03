package com.example.celldb.network;

import android.graphics.Color;

import com.example.celldb.R;
import com.example.celldb.network.NetworkModels.GeoPoint;
import com.example.celldb.network.NetworkModels.LineItem;
import com.example.celldb.network.NetworkModels.NetworkData;
import com.example.celldb.network.NetworkModels.PointItem;

import com.kakao.vectormap.KakaoMap;
import com.kakao.vectormap.LatLng;
import com.kakao.vectormap.label.*;
import com.kakao.vectormap.route.*;

import java.util.ArrayList;
import java.util.List;

public final class KakaoNetworkRenderer {
    public interface PointClick { void onClick(PointItem point); }
    private final KakaoMap map;

    private final LodLabelLayer cellLayer;
    private final LodLabelLayer facilityLayer;
    private final LodLabelLayer equipmentLayer;
    private final RouteLineLayer fiberLayer;
    private final RouteLineLayer coaxLayer;

    private final LabelStyles cellStyle;
    private final LabelStyles facilityStyle;
    private final LabelStyles equipmentStyle;

    private final RouteLineStylesSet fiberStyles;
    private final RouteLineStylesSet coaxStyles;

    public KakaoNetworkRenderer(KakaoMap kakaoMap, PointClick onClick) {
        this.map = kakaoMap;

        LabelManager lm = map.getLabelManager();
        cellLayer = lm.addLodLayer(LabelLayerOptions.from("cellLayer").setLodRadius(24));
        facilityLayer = lm.addLodLayer(LabelLayerOptions.from("facilityLayer").setLodRadius(18));
        equipmentLayer = lm.addLodLayer(LabelLayerOptions.from("equipmentLayer").setLodRadius(18));
        cellLayer.setClickable(true);
        facilityLayer.setClickable(true);
        equipmentLayer.setClickable(true);
        map.setOnLodLabelClickListener((clickedMap, layer, label) -> {
            if (label.getTag() instanceof PointItem) onClick.onClick((PointItem) label.getTag());
            return label.getTag() instanceof PointItem;
        });

        cellStyle = lm.addLabelStyles(LabelStyles.from(LabelStyle.from(R.drawable.map_cell)));
        facilityStyle = lm.addLabelStyles(LabelStyles.from(LabelStyle.from(R.drawable.map_facility)));
        equipmentStyle = lm.addLabelStyles(LabelStyles.from(LabelStyle.from(R.drawable.map_equipment)));

        fiberLayer = map.getRouteLineManager().addLayer("fiberLayer", 1001);
        coaxLayer = map.getRouteLineManager().addLayer("coaxLayer", 1000);

        fiberStyles = map.getRouteLineManager().addStylesSet(RouteLineStylesSet.from("fiberStyle",
                RouteLineStyles.from(RouteLineStyle.from(5, Color.rgb(0, 120, 255)))));
        coaxStyles = map.getRouteLineManager().addStylesSet(RouteLineStylesSet.from("coaxStyle",
                RouteLineStyles.from(RouteLineStyle.from(5, Color.rgb(255, 120, 0)))));
    }

    public void render(NetworkData data) {
        clear();
        addPoints(cellLayer, cellStyle, data.cells);
        addPoints(facilityLayer, facilityStyle, data.facilities);
        addPoints(equipmentLayer, equipmentStyle, data.equipment);
        addLines(fiberLayer, fiberStyles, data.fiber);
        addLines(coaxLayer, coaxStyles, data.coax);
    }

    private void addPoints(LodLabelLayer layer, LabelStyles style, List<PointItem> items) {
        ArrayList<LabelOptions> options = new ArrayList<>(items.size());
        int index = 0;
        for (PointItem p : items) {
            LabelOptions o = LabelOptions.from(p.category + "-" + index++, LatLng.from(p.lat, p.lon))
                    .setStyles(style)
                    .setClickable(true)
                    .setTag(p);
            options.add(o);
        }
        if (!options.isEmpty()) layer.addLodLabels(options);
    }

    private void addLines(RouteLineLayer layer, RouteLineStylesSet styles, List<LineItem> lines) {
        for (LineItem line : lines) {
            ArrayList<LatLng> pts = new ArrayList<>(line.points.size());
            for (GeoPoint p : line.points) pts.add(LatLng.from(p.lat, p.lon));
            if (pts.size() < 2) continue;

            RouteLineSegment segment = RouteLineSegment.from(pts)
                    .setStyles(styles.getStyles(0));
            RouteLineOptions opts = RouteLineOptions.from(line.id, segment)
                    .setStylesSet(styles)
                    .setTag(line);
            layer.addRouteLine(opts);
        }
    }

    public void clear() {
        cellLayer.removeAll();
        facilityLayer.removeAll();
        equipmentLayer.removeAll();
        fiberLayer.removeAll();
        coaxLayer.removeAll();
    }

    public void setCellVisible(boolean v) { cellLayer.setVisible(v); }
    public void setFacilityVisible(boolean v) { facilityLayer.setVisible(v); }
    public void setEquipmentVisible(boolean v) { equipmentLayer.setVisible(v); }
    public void setFiberVisible(boolean v) { fiberLayer.setVisible(v); }
    public void setCoaxVisible(boolean v) { coaxLayer.setVisible(v); }
}
