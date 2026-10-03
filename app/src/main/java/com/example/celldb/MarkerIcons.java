package com.example.celldb;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;

final class MarkerIcons {
    private MarkerIcons() { }

    // Kakao applies device density internally; bitmap dimensions are logical dp.
    static Bitmap create(int color, String text, boolean current) {
        int width = current ? 40 : 48;
        int height = current ? 40 : 56;
        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        Canvas canvas = new Canvas(bitmap);
        Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        paint.setColor(color);
        canvas.drawCircle(width / 2f, current ? 20 : 24, current ? 19 : 22, paint);
        if (!current) {
            Path tail = new Path();
            tail.moveTo(14, 39); tail.lineTo(24, 55); tail.lineTo(34, 39); tail.close();
            canvas.drawPath(tail, paint);
        }
        paint.setColor(Color.WHITE);
        paint.setTextAlign(Paint.Align.CENTER);
        paint.setTextSize(current ? 10 : 12);
        paint.setFakeBoldText(true);
        canvas.drawText(text, width / 2f, current ? 24 : 28, paint);
        return bitmap;
    }
}
