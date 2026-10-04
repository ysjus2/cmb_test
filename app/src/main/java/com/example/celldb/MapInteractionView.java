package com.example.celldb;

import android.content.Context;
import android.view.*;
import android.widget.FrameLayout;

/** Observe context gestures without taking away map pan/pinch gestures. */
final class MapInteractionView extends FrameLayout {
    private final GestureDetector detector;
    private final Runnable context;
    private boolean contextGesture;
    MapInteractionView(Context owner,Runnable context) {
        super(owner);this.context=context;
        detector=new GestureDetector(owner,new GestureDetector.SimpleOnGestureListener(){
            @Override public boolean onDown(MotionEvent event){return true;}
            @Override public void onLongPress(MotionEvent event){
                contextGesture=true;
                MotionEvent cancel=MotionEvent.obtain(event);cancel.setAction(MotionEvent.ACTION_CANCEL);
                MapInteractionView.super.dispatchTouchEvent(cancel);cancel.recycle();context.run();
            }
        });
    }
    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        if(event.getActionMasked()==MotionEvent.ACTION_DOWN)contextGesture=false;
        if(event.getActionMasked()==MotionEvent.ACTION_DOWN&&(event.getButtonState()&MotionEvent.BUTTON_SECONDARY)!=0){
            contextGesture=true;context.run();return true;
        }
        if(!contextGesture)detector.onTouchEvent(event);
        if(contextGesture)return true;
        return super.dispatchTouchEvent(event);
    }
    @Override public boolean dispatchGenericMotionEvent(MotionEvent event){
        if(event.getActionMasked()==MotionEvent.ACTION_BUTTON_PRESS && event.getActionButton()==MotionEvent.BUTTON_SECONDARY){context.run();return true;}
        return super.dispatchGenericMotionEvent(event);
    }
}
