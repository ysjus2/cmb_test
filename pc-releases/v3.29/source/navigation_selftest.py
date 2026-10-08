import math
from types import SimpleNamespace
from viewer import DXFViewer


def camera():
    v=DXFViewer.__new__(DXFViewer)
    v.scale=0.8;v.ox=400-156000*v.scale;v.oy=400+174000*v.scale
    v.pan_start=None;v.redraw=lambda:None
    return v


def main():
    v=camera();v._pan_start(SimpleNamespace(x=400,y=400))
    event=SimpleNamespace(x=420,y=410)
    v._pan_move(event);v._zoom_at(event.x,event.y,1.15)
    before=v.screen_to_world(event.x,event.y);origin=(v.ox,v.oy)
    v._pan_move(event)
    assert math.dist(before,v.screen_to_world(event.x,event.y))<1e-7
    assert (v.ox,v.oy)==origin
    v._pan_move(SimpleNamespace(x=440,y=420))
    assert abs(v.ox-origin[0]-20)<1e-7 and abs(v.oy-origin[1]-10)<1e-7
    # Repeated alternating drag and zoom must leave the same world point at the cursor.
    for i in range(80):
        e=SimpleNamespace(x=440+i,y=420+i//2)
        v._pan_move(e);world=v.screen_to_world(e.x,e.y)
        v._zoom_at(e.x,e.y,1.15 if i%2==0 else 1/1.15);v._pan_move(e)
        assert math.dist(world,v.screen_to_world(e.x,e.y))<1e-6
    v=camera();start=(v.scale,v.ox,v.oy)
    assert v._wheel(SimpleNamespace(x=400,y=400,delta=0))=='break'
    assert (v.scale,v.ox,v.oy)==start
    v._wheel(SimpleNamespace(x=400,y=400,delta=15))
    assert abs(v.scale/start[0]-1.15**0.125)<1e-12
    v._wheel(SimpleNamespace(x=400,y=400,delta=-15))
    assert abs(v.scale-start[0])<1e-12
    v.pan_start=(1,1,0,0);v.scene=SimpleNamespace(bbox=(150000,170000,160000,180000))
    v.canvas=SimpleNamespace(winfo_width=lambda:1000,winfo_height=lambda:800)
    v.update_idletasks=lambda:None;v._visible_fit_bbox=lambda:v.scene.bbox
    v.fit_view();assert v.pan_start is None
    origin=(v.scale,v.ox,v.oy);v._pan_move(SimpleNamespace(x=900,y=900))
    assert (v.scale,v.ox,v.oy)==origin
    print('Navigation test OK: zoom during drag does not jump; 80 mixed gestures stable; fine wheel/zero delta and fit reset verified')

if __name__=='__main__':main()
