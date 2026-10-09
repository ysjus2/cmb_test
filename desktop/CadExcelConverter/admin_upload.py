from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from pyproj import Transformer
from drawing_identity import drawing_code
from server_client_windows import CMBServerClient

GROUPS=("FIBER","COAX","POLE","CONDUIT","USER")

def classify_entity(e):
    u=(str(e.layer or "")+" "+str(e.block_name or "")).upper()
    if any(k in u for k in ("F_CABLE","FIBER","FOC","OPTIC","CLOSURE","ONU","광")): return "FIBER"
    if any(k in u for k in ("C_CABLE","COAX","RG06","RG11","PFC","AMP","TAP","PASSIVE","POWER","CONNECTOR","동축","증폭","분기")): return "COAX"
    if any(k in u for k in ("POLE","전주","POLE_CATV","POLE-CATV")): return "POLE"
    if any(k in u for k in ("CONDUIT","MANHOLE","HANDHOLE","관로","맨홀","핸드홀")): return "CONDUIT"
    if "USER" in u or "CN_M_USER" in u: return "USER"
    return None

def _points(e):
    for kind,data in e.primitives:
        if kind in {"line","polyline","polygon"} and len(data)>=2: return [(float(x),float(y)) for x,y in data]
        if kind in {"insert","point"}: return [(float(data[0]),float(data[1]))]
    if e.bbox:
        x1,y1,x2,y2=e.bbox; return [((x1+x2)/2,(y1+y2)/2)]
    return []

def build_payload(scene,source_path,group,epsg):
    t=Transformer.from_crs(f"EPSG:{int(epsg)}","EPSG:4326",always_xy=True)
    objects=[]
    for e in scene.entities:
        if classify_entity(e)!=group: continue
        pts=_points(e)
        geo=[]
        for x,y in pts:
            lon,lat=t.transform(x,y)
            if math.isfinite(lon) and math.isfinite(lat): geo.append([lon,lat])
        if not geo: continue
        objects.append({
            "source_handle":e.handle,
            "regional_object_id":f"{drawing_code(source_path)}_{e.handle}" if e.handle else "",
            "layer":e.layer,"entity_type":e.entity_type,"block_name":e.block_name,
            "geometry":{"type":"Point" if len(geo)==1 else "LineString","coordinates":geo[0] if len(geo)==1 else geo},
            "attributes":dict(e.attributes or {}),"xdata":dict(e.xdata or [])
        })
    p=Path(source_path)
    return {"schema":"cmb-network-package-v1","region_code":drawing_code(source_path),"group":group,
            "source_epsg":int(epsg),"source_file":p.name,"source_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
            "object_count":len(objects),"objects":objects}

class AdminUploadWindow(tk.Toplevel):
    def __init__(self,master,scene,source_path,source_epsg):
        super().__init__(master);self.scene=scene;self.source_path=source_path;self.epsg=source_epsg
        self.client=CMBServerClient();self.title("관리자 · 서버 도면 업로드");self.geometry("780x560")
        root=ttk.Frame(self,padding=12);root.pack(fill="both",expand=True)
        ttk.Label(root,text="관리자 서버 도면 업로드",font=("Malgun Gothic",16,"bold")).pack(anchor="w")
        ttk.Label(root,text=f"지역 {drawing_code(source_path)} · {Path(source_path).name} · EPSG:{source_epsg}").pack(anchor="w",pady=(3,10))
        self.tree=ttk.Treeview(root,columns=("g","n","d"),show="headings",height=8)
        for k,t,w in (("g","그룹",100),("n","객체수",90),("d","범위",500)): self.tree.heading(k,text=t);self.tree.column(k,width=w)
        self.tree.pack(fill="x")
        desc={"FIBER":"광케이블 + 광 관련 기기","COAX":"동축케이블 + AMP/TAP/PASSIVE/POWER 등 동축기기",
              "POLE":"전주 + 자가주","CONDUIT":"관로 + 맨홀 + 핸드홀","USER":"사용자 작성 건물/지형/관리구역"}
        counts={g:0 for g in GROUPS}
        for e in scene.entities:
            g=classify_entity(e)
            if g: counts[g]+=1
        for g in GROUPS:self.tree.insert("", "end",iid=g,values=(g,f"{counts[g]:,}",desc[g]))
        self.tree.selection_set("FIBER")
        row=ttk.Frame(root);row.pack(fill="x",pady=12)
        ttk.Button(row,text="선택 그룹 서버 업로드",command=self.upload_selected).pack(side="left")
        ttk.Button(row,text="전체 5그룹 순차 업로드",command=self.upload_all).pack(side="left",padx=6)
        ttk.Button(row,text="서버 상태 확인",command=self.health).pack(side="left")
        self.status=tk.StringVar(value="서버: https://192.168.246.54:8443")
        ttk.Label(root,textvariable=self.status,anchor="w").pack(fill="x")
    def health(self):
        try:self.status.set("서버 응답: "+json.dumps(self.client.health(),ensure_ascii=False))
        except Exception as e:messagebox.showerror("서버",str(e),parent=self)
    def _upload(self,g):
        payload=build_payload(self.scene,self.source_path,g,self.epsg)
        result=self.client.upload_group(payload)
        self.status.set(f"{g} 업로드 완료 · revision {result.get('revision')} · {result.get('object_count')}개")
        return result
    def upload_selected(self):
        sel=self.tree.selection()
        if not sel:return
        try:self._upload(sel[0])
        except Exception as e:messagebox.showerror("업로드 오류",str(e),parent=self)
    def upload_all(self):
        try:
            for g in GROUPS:self._upload(g)
            messagebox.showinfo("업로드","5개 그룹 업로드가 완료되었습니다.",parent=self)
        except Exception as e:messagebox.showerror("업로드 오류",str(e),parent=self)
