from __future__ import annotations
import json,os
from pathlib import Path
import tkinter as tk
from tkinter import simpledialog,messagebox
from server_client_windows import CMBServerClient,BASE_URL

CFG=Path(os.getenv("LOCALAPPDATA") or Path.home())/"CMB_DXF_Viewer"/"online.json"

def key():
    k=os.getenv("KAKAO_JS_APP_KEY","").strip()
    if not k and CFG.exists():
        try:k=json.loads(CFG.read_text(encoding="utf-8")).get("kakao_js_key","").strip()
        except:pass
    if k:return k
    r=tk.Tk();r.withdraw()
    k=simpledialog.askstring("카카오맵","Kakao JavaScript Key를 입력해주세요.",parent=r) or ""
    r.destroy()
    if k:
        CFG.parent.mkdir(parents=True,exist_ok=True);CFG.write_text(json.dumps({"kakao_js_key":k}),encoding="utf-8")
    return k

class Api:
    def __init__(self):self.c=CMBServerClient();self.dataset=""
    def datasets(self):
        out=[]
        for r in self.c.regions() or []:
            for d in self.c.region_datasets(r["id"]) or []: out.append({"id":d["id"],"name":r.get("name",r["id"])})
        return out
    def select(self,d):self.dataset=d;return True
    def objects(self,w,s,e,n):
        if not self.dataset:return {"features":[]}
        return self.c.objects(self.dataset,f"{w},{s},{e},{n}")

def html(k):
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<style>html,body,#map{{width:100%;height:100%;margin:0}}#p{{position:absolute;z-index:5;top:10px;left:10px;background:#fff;padding:8px;border-radius:6px}}</style>
<script src='https://dapi.kakao.com/v2/maps/sdk.js?appkey={k}&autoload=false'></script></head><body>
<div id='map'></div><div id='p'><b>CMB 온라인 Viewer</b> <select id='ds'></select> <span id='st'></span></div>
<script>
let map,ovs=[];
function clear(){{ovs.forEach(x=>x.setMap(null));ovs=[]}}
async function load(){{
 let b=map.getBounds(),sw=b.getSouthWest(),ne=b.getNorthEast(),r=await pywebview.api.objects(sw.getLng(),sw.getLat(),ne.getLng(),ne.getLat());
 clear();(r.features||[]).forEach(f=>{{let g=f.geometry||{{}},p=f.properties||{{}},grp=(p.group_id||'').toUpperCase(),c=grp==='FIBER'?'#1e88e5':grp==='COAX'?'#f57c00':grp==='POLE'?'#6d4c41':grp==='CONDUIT'?'#00acc1':'#8e24aa';
 if(g.type==='Point'){{let a=g.coordinates,m=new kakao.maps.Marker({{position:new kakao.maps.LatLng(a[1],a[0])}});m.setMap(map);ovs.push(m)}}
 if(g.type==='LineString'){{let path=g.coordinates.map(a=>new kakao.maps.LatLng(a[1],a[0])),l=new kakao.maps.Polyline({{path:path,strokeWeight:4,strokeColor:c,strokeOpacity:.9}});l.setMap(map);ovs.push(l)}}}});
 document.getElementById('st').textContent=(r.features||[]).length+'개';
}}
kakao.maps.load(async()=>{{map=new kakao.maps.Map(document.getElementById('map'),{{center:new kakao.maps.LatLng(35.1595,126.8526),level:8}});
 let ds=document.getElementById('ds'),items=await pywebview.api.datasets();ds.innerHTML='<option value="">지역 선택</option>';items.forEach(x=>{{let o=document.createElement('option');o.value=x.id;o.text=x.name;ds.appendChild(o)}});
 ds.onchange=async()=>{{await pywebview.api.select(ds.value);load()}};kakao.maps.event.addListener(map,'idle',()=>load());}});
</script></body></html>"""

def run_online_viewer():
    k=key()
    if not k:return 2
    import webview
    webview.create_window("CMB 온라인 Viewer",html=html(k),js_api=Api(),width=1450,height=900,min_size=(900,600))
    webview.start(gui="edgechromium",debug=False)
    return 0
