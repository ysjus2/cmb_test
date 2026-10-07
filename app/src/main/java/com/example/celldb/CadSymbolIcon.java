package com.example.celldb;
import android.graphics.*;
/** CMB-authored geometric symbols; relative size is based on a 48dp device. */
final class CadSymbolIcon {
    static Bitmap create(String raw){
        if(raw==null)return null;
        String[] parts=raw.split(":");String type=parts[0];float rotation=0;
        try{if(parts.length>1)rotation=Float.parseFloat(parts[1]);}catch(Exception ignored){}
        if(Float.isNaN(rotation)||Float.isInfinite(rotation))rotation=0;
        Bitmap b=Bitmap.createBitmap(64,64,Bitmap.Config.ARGB_8888);
        Canvas c=new Canvas(b);Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(Color.rgb(25,70,130));p.setStrokeWidth(1.8f);p.setStyle(Paint.Style.STROKE);
        switch(type){
            case "AMP":
                c.rotate(-rotation,32,32);Path t=new Path();t.moveTo(56,32);t.lineTo(8,8);t.lineTo(8,56);t.close();p.setStyle(Paint.Style.FILL);c.drawPath(t,p);break;
            case "ONU":
                c.rotate(-rotation,32,32);p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(0,137,123));c.drawRect(8,20,56,44,p);
                p.setColor(Color.WHITE);p.setTextSize(15);p.setTypeface(Typeface.DEFAULT_BOLD);p.setTextAlign(Paint.Align.CENTER);
                Paint.FontMetrics fm=p.getFontMetrics();c.drawText("ONU",32,32-(fm.ascent+fm.descent)/2,p);break;
            case "POLE":c.drawCircle(32,32,4.8f,p);float cross=4.8f/(float)Math.sqrt(2);c.drawLine(32-cross,32-cross,32+cross,32+cross,p);c.drawLine(32-cross,32+cross,32+cross,32-cross,p);break;
            case "CAB":c.rotate(-rotation,32,32);c.drawRect(8,20,56,44,p);break;
            case "MH_RECT":c.drawRect(20,20,44,44,p);break;
            case "TAP":Path h=new Path();for(int i=0;i<6;i++){double a=Math.PI*i/3;float x=32+12*(float)Math.cos(a),y=32+12*(float)Math.sin(a);if(i==0)h.moveTo(x,y);else h.lineTo(x,y);}h.close();c.drawPath(h,p);break;
            default:c.drawCircle(32,32,12,p);
        }
        return b;
    }
}
