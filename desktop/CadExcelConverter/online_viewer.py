from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tkinter as tk
from tkinter import simpledialog

from server_client_windows import CMBServerClient

CFG = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CMB_DXF_Viewer" / "online.json"


def key():
    k = os.getenv("KAKAO_JS_APP_KEY", "").strip()
    if not k and CFG.exists():
        try:
            k = json.loads(CFG.read_text(encoding="utf-8")).get("kakao_js_key", "").strip()
        except Exception:
            pass
    if k:
        return k

    root = tk.Tk()
    root.withdraw()
    k = simpledialog.askstring(
        "카카오맵",
        "Kakao JavaScript Key를 입력해주세요.",
        parent=root,
    ) or ""
    root.destroy()

    if k:
        CFG.parent.mkdir(parents=True, exist_ok=True)
        CFG.write_text(
            json.dumps({"kakao_js_key": k}, ensure_ascii=False),
            encoding="utf-8",
        )
    return k


class Api:
    def __init__(self):
        self.c = CMBServerClient()
        self.region = ""
        self.user = None

    def login(self, username, password):
        try:
            self.user = self.c.login(username, password)
            return {"ok": True, "user": self.user}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def logout(self):
        try:
            self.c.logout()
        except Exception:
            pass
        self.user = None
        self.region = ""
        return True

    def regions(self):
        try:
            return {"ok": True, "items": self.c.online_regions() or []}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "items": []}

    def select(self, region):
        self.region = str(region or "")
        if not self.region:
            return {"ok": True, "bounds": None, "layers": []}
        try:
            info = self.c.online_layers(self.region) or {}
            return {
                "ok": True,
                "bounds": info.get("bounds"),
                "layers": info.get("layers") or [],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def objects(self, west, south, east, north):
        if not self.region:
            return {"features": []}
        try:
            return self.c.online_objects(
                self.region,
                f"{west},{south},{east},{north}",
            ) or {"features": []}
        except Exception as exc:
            return {"features": [], "error": str(exc)}


def html(k):
    return f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<style>
html,body,#map{{width:100%;height:100%;margin:0;font-family:'Malgun Gothic',sans-serif}}
#top{{position:absolute;z-index:10;top:10px;left:10px;right:10px;display:flex;gap:8px;align-items:center;pointer-events:none}}
.card{{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:7px 9px;box-shadow:0 2px 8px rgba(0,0,0,.16);pointer-events:auto}}
#tools{{display:flex;gap:6px;align-items:center}}
#tools select,#tools button{{height:30px}}
#status{{font-size:12px;color:#334155;min-width:100px}}
#login{{position:absolute;z-index:20;inset:0;background:rgba(15,23,42,.38);display:flex;align-items:center;justify-content:center}}
#loginBox{{width:320px;background:#fff;border-radius:10px;padding:18px;box-shadow:0 8px 28px rgba(0,0,0,.3)}}
#loginBox h3{{margin:0 0 14px}}
#loginBox input{{width:100%;box-sizing:border-box;height:36px;margin:5px 0;padding:0 8px}}
#loginBox button{{width:100%;height:36px;margin-top:8px}}
#error{{color:#b91c1c;font-size:12px;min-height:18px;margin-top:8px}}
#detail{{position:absolute;z-index:8;top:60px;right:10px;max-width:360px;background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:8px;display:none;max-height:50vh;overflow:auto;font-size:12px}}
.row{{display:grid;grid-template-columns:max-content 1fr;gap:4px 9px;margin:2px 0}}
.key{{color:#64748b}}
</style>
<script src='https://dapi.kakao.com/v2/maps/sdk.js?appkey={k}&autoload=false'></script>
</head>
<body>
<div id='map'></div>

<div id='top'>
  <div class='card' id='tools'>
    <b>CMB 온라인 Viewer</b>
    <select id='region'><option value=''>지역 선택</option></select>
    <button id='reload'>새로고침</button>
    <button id='logout'>로그아웃</button>
    <span id='status'>로그인 필요</span>
  </div>
</div>

<div id='detail'></div>

<div id='login'>
  <div id='loginBox'>
    <h3>CMB 서버 로그인</h3>
    <input id='user' autocomplete='username' placeholder='아이디'>
    <input id='pass' type='password' autocomplete='current-password' placeholder='비밀번호'>
    <button id='loginBtn'>로그인</button>
    <div id='error'></div>
  </div>
</div>

<script>
let map;
let overlays=[];
let selectedOverlay=null;

function setStatus(t){{document.getElementById('status').textContent=t||''}}

function clearOverlays(){{
  overlays.forEach(x=>x.setMap(null));
  overlays=[];
  selectedOverlay=null;
}}

function showDetail(p){{
  const d=document.getElementById('detail');
  const rows=[];
  const add=(k,v)=>{{if(v!==null&&v!==undefined&&String(v).trim()!=='') rows.push([k,String(v)])}};
  add('그룹',p.group_id);
  add('레이어',p.layer);
  add('객체종류',p.entity_type);
  add('블록',p.block_name);
  add('객체 ID',p.regional_object_id||p.entity_id);
  const f=((p.attributes||{{}}).fields)||{{}};
  Object.keys(f).sort().forEach(k=>add(k,f[k]));
  if(!rows.length){{d.style.display='none';return}}
  d.innerHTML=rows.map(x=>'<div class="row"><div class="key">'+esc(x[0])+'</div><div>'+esc(x[1])+'</div></div>').join('');
  d.style.display='block';
}}

function esc(v){{
  return String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function colorFor(group){{
  group=(group||'').toUpperCase();
  if(group==='FIBER')return '#1e88e5';
  if(group==='COAX')return '#f57c00';
  if(group==='POLE')return '#6d4c41';
  if(group==='CONDUIT')return '#00acc1';
  return '#8e24aa';
}}

function bindClick(overlay,props){{
  kakao.maps.event.addListener(overlay,'click',()=>showDetail(props||{{}}));
}}

async function loadObjects(){{
  const region=document.getElementById('region').value;
  if(!region||!map)return;
  const b=map.getBounds(),sw=b.getSouthWest(),ne=b.getNorthEast();
  setStatus('불러오는 중...');
  const r=await pywebview.api.objects(sw.getLng(),sw.getLat(),ne.getLng(),ne.getLat());
  if(r.error){{setStatus(r.error);return}}
  clearOverlays();
  const features=r.features||[];
  features.forEach(f=>{{
    const g=f.geometry||{{}};
    const p=f.properties||{{}};
    const c=colorFor(p.group_id);
    if(g.type==='Point'){{
      const a=g.coordinates;
      const m=new kakao.maps.Marker({{position:new kakao.maps.LatLng(a[1],a[0])}});
      m.setMap(map);overlays.push(m);bindClick(m,p);
    }} else if(g.type==='LineString'){{
      const path=g.coordinates.map(a=>new kakao.maps.LatLng(a[1],a[0]));
      const l=new kakao.maps.Polyline({{
        path:path,strokeWeight:4,strokeColor:c,strokeOpacity:.9
      }});
      l.setMap(map);overlays.push(l);bindClick(l,p);
    }}
  }});
  setStatus(features.length+'개');
}}

async function loadRegions(){{
  const r=await pywebview.api.regions();
  if(!r.ok){{setStatus(r.error||'지역 조회 실패');return}}
  const sel=document.getElementById('region');
  sel.innerHTML='<option value="">지역 선택</option>';
  (r.items||[]).forEach(x=>{{
    const o=document.createElement('option');
    o.value=x.id;
    o.text=x.name||x.id;
    sel.appendChild(o);
  }});
  setStatus((r.items||[]).length+'개 지역');
}}

async function login(){{
  const u=document.getElementById('user').value.trim();
  const p=document.getElementById('pass').value;
  const e=document.getElementById('error');
  e.textContent='';
  if(!u||!p){{e.textContent='아이디와 비밀번호를 입력해주세요.';return}}
  const r=await pywebview.api.login(u,p);
  if(!r.ok){{e.textContent=r.error||'로그인 실패';return}}
  document.getElementById('pass').value='';
  document.getElementById('login').style.display='none';
  await loadRegions();
}}

function bindUi(){{
  document.getElementById('loginBtn').onclick=login;
  document.getElementById('pass').addEventListener('keydown',e=>{{if(e.key==='Enter')login()}});
  document.getElementById('reload').onclick=()=>loadObjects();

  document.getElementById('region').onchange=async e=>{{
    clearOverlays();
    document.getElementById('detail').style.display='none';
    const r=await pywebview.api.select(e.target.value);
    if(!r.ok){{setStatus(r.error||'지역 선택 실패');return}}
    if(!map){{
      setStatus('카카오맵 초기화 대기');
      return;
    }}
    const b=r.bounds||null;
    if(b&&b.west!=null&&b.south!=null&&b.east!=null&&b.north!=null){{
      const bounds=new kakao.maps.LatLngBounds();
      bounds.extend(new kakao.maps.LatLng(b.south,b.west));
      bounds.extend(new kakao.maps.LatLng(b.north,b.east));
      map.setBounds(bounds);
    }}
    await loadObjects();
  }};

  document.getElementById('logout').onclick=async()=>{{
    await pywebview.api.logout();
    clearOverlays();
    document.getElementById('region').innerHTML='<option value="">지역 선택</option>';
    document.getElementById('detail').style.display='none';
    document.getElementById('login').style.display='flex';
    setStatus('로그인 필요');
  }};
}}

function initMap(){{
  try{{
    if(!(window.kakao&&kakao.maps)){{
      setStatus('카카오 JavaScript SDK 로드 실패');
      return;
    }}
    kakao.maps.load(()=>{{
      map=new kakao.maps.Map(document.getElementById('map'),{{
        center:new kakao.maps.LatLng(35.1595,126.8526),
        level:8
      }});
      kakao.maps.event.addListener(map,'idle',()=>loadObjects());
      setStatus('로그인 필요');
    }});
  }}catch(err){{
    setStatus('카카오맵 초기화 오류');
    document.getElementById('error').textContent=String(err);
  }}
}}

bindUi();
initMap();
</script>
</body>
</html>"""


def run_online_viewer():
    k = key()
    if not k:
        return 2

    import webview

    page = html(k).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        webview.create_window(
            "CMB 온라인 Viewer",
            url="http://127.0.0.1:8765/",
            js_api=Api(),
            width=1450,
            height=900,
            min_size=(900, 600),
        )
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.shutdown()
        server.server_close()

    return 0
