package com.example.celldb;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Point;
import android.graphics.RectF;
import android.graphics.Region;
import android.view.MotionEvent;
import org.json.JSONArray;
import org.json.JSONObject;
import org.osmdroid.util.GeoPoint;
import org.osmdroid.views.MapView;
import org.osmdroid.views.overlay.Overlay;
import java.util.ArrayList;
import java.util.Set;

/** CMB-authored geometry in geographic coordinates, never a fixed-size bitmap. */
final class CmbGeoSymbolOverlay extends Overlay {
    private final ArrayList<GeoPoint> ring;
    private final ArrayList<ArrayList<GeoPoint>> links=new ArrayList<>();
    private final ArrayList<Boolean> fiber=new ArrayList<>();
    private final ArrayList<ArrayList<GeoPoint>> marks=new ArrayList<>();
    private final String type;
    private final boolean filled;
    private final Runnable onClick;
    private final float density;
    private final GeoPoint center;
    CmbGeoSymbolOverlay(MapPoint point,JSONObject layout,Set<String> visibleCables,float density,Runnable onClick) throws Exception {
        if(!"cmb-authored-v1".equals(layout.getString("source")))throw new IllegalArgumentException("Unsupported authored layout");
        ring=coordinates(layout.getJSONArray("ring"),128);
        if(ring.size()<4)throw new IllegalArgumentException("Incomplete symbol ring");
        this.filled=layout.getBoolean("filled");this.density=density;this.onClick=onClick;
        type=layout.optString("type","");
        JSONArray strokes=layout.optJSONArray("marks");
        if(strokes!=null){
            if(strokes.length()>4)throw new IllegalArgumentException("Too many symbol strokes");
            for(int i=0;i<strokes.length();i++)marks.add(coordinates(strokes.getJSONArray(i),8));
        }
        center=new GeoPoint(point.getLatitude(),point.getLongitude());
        JSONArray bridges=layout.getJSONArray("links");
        if(bridges.length()>64)throw new IllegalArgumentException("Too many symbol connections");
        for(int i=0;i<bridges.length();i++){
            JSONObject link=bridges.getJSONObject(i);
            if(!visibleCables.contains(link.getString("cable_layer")+"|"+link.getString("cable_entity")))continue;
            ArrayList<GeoPoint> points=coordinates(link.getJSONArray("coordinates"),2);
            if(points.size()!=2)throw new IllegalArgumentException("Invalid bridge");
            links.add(points);fiber.add(link.optBoolean("fiber"));
        }
    }
    private static ArrayList<GeoPoint> coordinates(JSONArray raw,int max) throws Exception {
        if(raw.length()>max)throw new IllegalArgumentException("Geometry too large");
        ArrayList<GeoPoint> result=new ArrayList<>();
        for(int i=0;i<raw.length();i++){
            JSONArray xy=raw.getJSONArray(i);double lon=xy.getDouble(0),lat=xy.getDouble(1);
            if(!Double.isFinite(lon)||!Double.isFinite(lat)||lon < -180||lon>180||lat < -90||lat>90)
                throw new IllegalArgumentException("Invalid coordinates");
            result.add(new GeoPoint(lat,lon));
        }
        return result;
    }
    private Path path(MapView map,ArrayList<GeoPoint> points,boolean closed){
        Path path=new Path();Point pixel=new Point();
        for(int i=0;i<points.size();i++){
            map.getProjection().toPixels(points.get(i),pixel);
            if(i==0)path.moveTo(pixel.x,pixel.y);else path.lineTo(pixel.x,pixel.y);
        }
        if(closed)path.close();return path;
    }
    @Override public void draw(Canvas canvas,MapView map,boolean shadow){
        if(shadow)return;
        Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(5*density);paint.setStrokeCap(Paint.Cap.ROUND);
        for(int i=0;i<links.size();i++){
            paint.setColor(fiber.get(i)?Color.rgb(30,136,229):Color.rgb(245,124,0));
            canvas.drawPath(path(map,links.get(i),false),paint);
        }
        paint.setColor("ONU".equals(type)?Color.rgb(0,137,123):Color.rgb(25,70,130));paint.setStrokeWidth(1.8f*density);
        paint.setStyle(filled?Paint.Style.FILL:Paint.Style.STROKE);
        canvas.drawPath(path(map,ring,true),paint);
        paint.setStyle(Paint.Style.STROKE);
        for(ArrayList<GeoPoint> stroke:marks)canvas.drawPath(path(map,stroke,false),paint);
        if("ONU".equals(type)&&ring.size()==5)drawOnuLabel(canvas,map,paint);
    }
    private void drawOnuLabel(Canvas canvas,MapView map,Paint paint){
        Point a=map.getProjection().toPixels(ring.get(0),null),b=map.getProjection().toPixels(ring.get(1),null),c=map.getProjection().toPixels(ring.get(2),null);
        float width=(float)Math.hypot(b.x-a.x,b.y-a.y),height=(float)Math.hypot(c.x-b.x,c.y-b.y);
        if(width<1||height<1)return;
        Point middle=map.getProjection().toPixels(center,null);
        paint.setStyle(Paint.Style.FILL);paint.setColor(Color.WHITE);paint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        paint.setTextSize(height*.65f);
        float measured=paint.measureText("ONU");
        if(measured>width*.8f)paint.setTextSize(paint.getTextSize()*width*.8f/measured);
        paint.setTextAlign(Paint.Align.CENTER);Paint.FontMetrics metrics=paint.getFontMetrics();
        canvas.save();canvas.translate(middle.x,middle.y);
        canvas.rotate((float)Math.toDegrees(Math.atan2(b.y-a.y,b.x-a.x)));
        canvas.drawText("ONU",0,-(metrics.ascent+metrics.descent)/2,paint);canvas.restore();
    }
    @Override public boolean onSingleTapConfirmed(MotionEvent event,MapView map){
        Path outline=path(map,ring,true);RectF bounds=new RectF();outline.computeBounds(bounds,true);
        Region clip=new Region((int)Math.floor(bounds.left)-1,(int)Math.floor(bounds.top)-1,(int)Math.ceil(bounds.right)+1,(int)Math.ceil(bounds.bottom)+1);
        Region hit=new Region();hit.setPath(outline,clip);
        Point pixel=map.getProjection().toPixels(center,null);
        if(hit.contains((int)event.getX(),(int)event.getY())||Math.hypot(event.getX()-pixel.x,event.getY()-pixel.y)<=12*density){onClick.run();return true;}
        return false;
    }
}
