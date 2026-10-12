package com.example.celldb;
import android.graphics.*;

/** CMB-authored high-visibility geometric symbol library; optimized for small mobile map sizes. */
final class CadSymbolIcon {
    private CadSymbolIcon(){}

    static Bitmap create(String raw){
        if(raw==null)return null;
        String[] parts=raw.split(":");
        String type=parts[0];
        float rotation=0;
        try{if(parts.length>1)rotation=Float.parseFloat(parts[1]);}catch(Exception ignored){}
        if(Float.isNaN(rotation)||Float.isInfinite(rotation))rotation=0;

        Bitmap b=Bitmap.createBitmap(64,64,Bitmap.Config.ARGB_8888);
        Canvas c=new Canvas(b);
        Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setStrokeWidth(2.2f);
        p.setStrokeJoin(Paint.Join.ROUND);
        p.setStrokeCap(Paint.Cap.ROUND);

        switch(type){
            case "AMP":{
                c.rotate(-rotation,32,32);
                Path t=new Path();t.moveTo(56,32);t.lineTo(10,10);t.lineTo(10,54);t.close();
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(255,143,0));c.drawPath(t,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(109,59,0));c.drawPath(t,p);
                break;
            }
            case "ONU":{
                c.rotate(-rotation,32,32);
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(18,201,120));c.drawRect(7,20,57,44,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(7,92,60));c.drawRect(7,20,57,44,p);
                drawCenteredText(c,p,"ONU",32,32,15,Color.rgb(5,59,43));
                break;
            }
            case "POLE":{
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(109,76,65));p.setStrokeWidth(2f);
                c.drawCircle(32,32,5f,p);
                float cross=3.5f;
                c.drawLine(32-cross,32-cross,32+cross,32+cross,p);
                c.drawLine(32-cross,32+cross,32+cross,32-cross,p);
                break;
            }
            case "FBR":{
                c.rotate(-rotation,32,32);
                Path r=new Path();
                r.moveTo(23,18);r.lineTo(41,18);r.lineTo(50,21);r.lineTo(57,32);
                r.lineTo(50,43);r.lineTo(41,46);r.lineTo(23,46);r.lineTo(14,43);
                r.lineTo(7,32);r.lineTo(14,21);r.close();
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(33,150,243));c.drawPath(r,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(13,71,161));c.drawPath(r,p);
                break;
            }
            case "PWR":
            case "PWR_PS":{
                c.rotate(-rotation,32,32);
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(229,57,53));c.drawRect(11,11,53,53,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(127,0,0));c.drawRect(11,11,53,53,p);
                p.setStyle(Paint.Style.FILL);p.setColor(Color.WHITE);c.drawCircle(32,32,17.5f,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(127,0,0));c.drawCircle(32,32,17.5f,p);
                drawCenteredText(c,p,"PS",32,32,13,Color.rgb(127,0,0));
                break;
            }
            case "TAP":{
                Path h=new Path();
                for(int i=0;i<6;i++){
                    double a=Math.PI*i/3;
                    float x=32+13*(float)Math.cos(a),y=32+13*(float)Math.sin(a);
                    if(i==0)h.moveTo(x,y);else h.lineTo(x,y);
                }
                h.close();
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(255,201,40));c.drawPath(h,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(109,76,0));c.drawPath(h,p);
                break;
            }
            case "SPL2":{
                drawCircleLabel(c,p,"2");
                break;
            }
            case "SPL3":{
                drawCircleLabel(c,p,"3");
                break;
            }
            case "SPL":{
                drawCircleLabel(c,p,"");
                break;
            }
            case "SPL_DC":{
                drawCircleLabel(c,p,"DC");
                break;
            }
            case "PI":{
                c.rotate(-rotation,32,32);
                p.setStyle(Paint.Style.FILL);p.setColor(Color.WHITE);c.drawRect(12,21,52,43,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(66,66,66));c.drawRect(12,21,52,43,p);
                drawCenteredText(c,p,"I",32,32,15,Color.rgb(33,33,33));
                break;
            }
            case "MH":{
                p.setColor(Color.rgb(66,66,66));p.setStyle(Paint.Style.FILL);c.drawCircle(32,32,12,p);
                p.setColor(Color.rgb(245,245,245));c.drawCircle(32,32,9.5f,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(66,66,66));c.drawCircle(32,32,6.5f,p);
                break;
            }
            case "MH_RECT":{
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(245,245,245));c.drawRect(20,20,44,44,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(66,66,66));c.drawRect(20,20,44,44,p);
                break;
            }
            case "CAB":{
                c.rotate(-rotation,32,32);
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(238,238,238));c.drawRect(10,20,54,44,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(66,66,66));c.drawRect(10,20,54,44,p);
                break;
            }
            default:{
                p.setStyle(Paint.Style.FILL);p.setColor(Color.rgb(238,238,238));c.drawCircle(32,32,12,p);
                p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(66,66,66));c.drawCircle(32,32,12,p);
            }
        }
        return b;
    }

    private static void drawCircleLabel(Canvas c,Paint p,String label){
        p.setStyle(Paint.Style.FILL);p.setColor(Color.WHITE);c.drawCircle(32,32,12,p);
        p.setStyle(Paint.Style.STROKE);p.setColor(Color.rgb(66,66,66));c.drawCircle(32,32,12,p);
        if(label!=null&&!label.isEmpty())drawCenteredText(c,p,label,32,32,13,Color.rgb(33,33,33));
    }

    private static void drawCenteredText(Canvas c,Paint p,String text,float x,float y,float size,int color){
        p.setStyle(Paint.Style.FILL);p.setColor(color);p.setTextSize(size);
        p.setTypeface(Typeface.DEFAULT_BOLD);p.setTextAlign(Paint.Align.CENTER);
        Paint.FontMetrics fm=p.getFontMetrics();
        c.drawText(text,x,y-(fm.ascent+fm.descent)/2,p);
    }
}
