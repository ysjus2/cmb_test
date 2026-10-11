from __future__ import annotations

import gzip
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from server_client_windows import CMBServerClient, ServerError

APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CMB_DXF_Viewer"
CFG = APP_DATA_DIR / "online.json"
CACHE_DIR = APP_DATA_DIR / "online_cache"
SESSION_ENDED_EXIT_CODE = 41


def key():
    k = os.getenv("KAKAO_JS_APP_KEY", "").strip()
    if not k and CFG.exists():
        try:
            k = json.loads(CFG.read_text(encoding="utf-8")).get("kakao_js_key", "").strip()
        except Exception:
            pass
    if k:
        return k

    return ""


class Api:
    def __init__(self):
        self.c = CMBServerClient()
        self.region = ""
        self.user = None
        self.window = None
        self.session_ended = False
        self.cache_state = {"versions": {}, "features": {}, "coverage": []}
        self.last_version_check = 0.0

        self.c.access_token = os.getenv("CMB_AUTH_ACCESS", "").strip()
        self.c.refresh_token = os.getenv("CMB_AUTH_REFRESH", "").strip()
        self.c.on_session_expired = self.expire_session
        raw_user = os.getenv("CMB_AUTH_USER", "").strip()
        if raw_user:
            try:
                self.user = json.loads(raw_user)
            except Exception:
                self.user = None

    def _cache_path(self):
        safe = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in str(self.region or "")
        )
        return CACHE_DIR / f"{safe}.json.gz"

    @staticmethod
    def _feature_key(feature):
        props = feature.get("properties") or {}
        group = str(props.get("group_id") or "").upper()
        ident = str(
            props.get("regional_object_id")
            or props.get("entity_id")
            or props.get("object_id")
            or props.get("source_handle")
            or ""
        )
        if not ident:
            ident = json.dumps(
                feature.get("geometry") or {},
                sort_keys=True,
                ensure_ascii=False,
            )
        return f"{group}|{ident}"

    @staticmethod
    def _geometry_bounds(geometry):
        coords = (geometry or {}).get("coordinates")
        points = []

        def walk(value):
            if (
                isinstance(value, (list, tuple))
                and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))
            ):
                points.append((float(value[0]), float(value[1])))
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(coords)
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def _feature_intersects(cls, feature, west, south, east, north):
        bounds = cls._geometry_bounds(feature.get("geometry") or {})
        if not bounds:
            return False
        fw, fs, fe, fn = bounds
        return fe >= west and fw <= east and fn >= south and fs <= north

    def _load_cache(self):
        self.cache_state = {"versions": {}, "features": {}, "coverage": []}
        path = self._cache_path()
        if not path.exists():
            return
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                raw = json.load(fh)
            features = {}
            for feature in raw.get("features") or []:
                if isinstance(feature, dict):
                    features[self._feature_key(feature)] = feature
            self.cache_state = {
                "versions": {
                    str(k).upper(): str(v)
                    for k, v in (raw.get("versions") or {}).items()
                },
                "features": features,
                "coverage": list(raw.get("coverage") or [])[-200:],
            }
        except Exception:
            self.cache_state = {"versions": {}, "features": {}, "coverage": []}

    def _save_cache(self):
        if not self.region:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._cache_path()
            tmp = path.with_suffix(path.suffix + ".tmp")
            raw = {
                "versions": self.cache_state.get("versions") or {},
                "features": list((self.cache_state.get("features") or {}).values()),
                "coverage": list(self.cache_state.get("coverage") or [])[-200:],
            }
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(raw, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        except Exception:
            pass

    def _apply_versions(self, versions):
        versions = {
            str(k).upper(): str(v)
            for k, v in (versions or {}).items()
            if str(k).strip() and str(v).strip()
        }
        previous = self.cache_state.get("versions") or {}
        changed = {
            group
            for group, version in versions.items()
            if group in previous and previous.get(group) != version
        }
        if changed:
            kept = {}
            for key, feature in (self.cache_state.get("features") or {}).items():
                group = str(
                    ((feature.get("properties") or {}).get("group_id") or "")
                ).upper()
                if group not in changed:
                    kept[key] = feature
            self.cache_state["features"] = kept
            self.cache_state["coverage"] = []
        self.cache_state["versions"] = versions
        if changed:
            self._save_cache()
        return changed

    def _version_signature(self):
        versions = self.cache_state.get("versions") or {}
        return "|".join(f"{k}={versions[k]}" for k in sorted(versions))

    def _cache_covers(self, west, south, east, north):
        signature = self._version_signature()
        for item in self.cache_state.get("coverage") or []:
            if str(item.get("version") or "") != signature:
                continue
            try:
                if (
                    float(item["west"]) <= west
                    and float(item["south"]) <= south
                    and float(item["east"]) >= east
                    and float(item["north"]) >= north
                ):
                    return True
            except Exception:
                continue
        return False

    def _cached_features(self, west, south, east, north):
        return [
            feature
            for feature in (self.cache_state.get("features") or {}).values()
            if self._feature_intersects(feature, west, south, east, north)
        ]

    def _refresh_versions_if_due(self, force=False):
        now = time.monotonic()
        if not force and now - self.last_version_check < 60:
            return set()
        versions = self.c.online_versions(self.region) if self.region else {}
        self.last_version_check = now
        return self._apply_versions(versions)

    def _handle_error(self, exc, fallback=None):
        if isinstance(exc, ServerError) and exc.status == 401:
            self.expire_session()
            result = {"ok": False, "session_ended": True}
            if isinstance(fallback, dict):
                result.update(fallback)
            return result
        result = {"ok": False, "error": str(exc)}
        if isinstance(fallback, dict):
            result.update(fallback)
        return result

    def map_display_settings(self):
        try:
            settings = self.c.map_display_settings() or {}
            radius = int(settings.get("radius_m", 500))
            refresh = int(settings.get("refresh_distance_m", 200))
            return {
                "ok": True,
                "radius_m": max(100, min(3000, radius)),
                "refresh_distance_m": max(25, min(radius, refresh)),
            }
        except Exception as exc:
            return self._handle_error(
                exc,
                {"radius_m": 500, "refresh_distance_m": 200},
            )

    def session_policy(self):
        try:
            policy = self.c.session_policy() or {}
            return {
                "ok": True,
                "idle_minutes": int(policy.get("idle_minutes", 10)),
            }
        except Exception as exc:
            return self._handle_error(exc, {"idle_minutes": 10})

    def touch_session(self):
        try:
            self.c.touch_session()
            return {"ok": True}
        except Exception as exc:
            return self._handle_error(exc)

    def _close_session_window(self):
        self.user = None
        self.region = ""
        self.session_ended = True
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass
        return True

    def expire_session(self):
        # 401/refresh 실패는 현재 Viewer만 종료한다.
        # 다른 Viewer/런처가 공유 중인 서버 세션을 여기서 revoke하지 않는다.
        return self._close_session_window()

    def end_session(self):
        # 사용자가 명시적으로 로그아웃한 경우에만 서버 세션을 revoke한다.
        try:
            self.c.logout()
        except Exception:
            pass
        return self._close_session_window()

    def logout(self):
        return self.end_session()

    def regions(self):
        try:
            raw = self.c.regions() or []
            if isinstance(raw, dict):
                raw = raw.get("items") or raw.get("regions") or []

            items = []
            seen = set()
            for row in raw:
                if not isinstance(row, dict):
                    continue
                region_id = str(row.get("id") or "").strip()
                if not region_id:
                    continue
                key = region_id.casefold()
                if key in seen:
                    continue
                seen.add(key)
                name = str(row.get("name") or region_id).strip()
                items.append({"id": region_id, "name": name or region_id})

            return {
                "ok": True,
                "items": items,
                "count": len(items),
                "level": int((self.user or {}).get("level") or 0),
            }
        except Exception as exc:
            return self._handle_error(
                exc,
                {
                    "items": [],
                    "count": 0,
                    "level": int((self.user or {}).get("level") or 0),
                },
            )

    def select(self, region):
        self.region = str(region or "")
        self.last_version_check = 0.0
        if not self.region:
            self.cache_state = {"versions": {}, "features": {}, "coverage": []}
            return {"ok": True, "bounds": None, "layers": []}
        try:
            # 지역 선택 직후에는 캐시를 먼저 읽고 서버에는 버전만 확인한다.
            # 버전이 동일하면 /layers 응답을 기다리지 않고 바로 캐시 렌더 단계로 넘긴다.
            self._load_cache()
            previous_versions = dict(self.cache_state.get("versions") or {})
            cached_count = len(self.cache_state.get("features") or {})

            current_versions = self.c.online_versions(self.region) or {}
            self.last_version_check = time.monotonic()
            changed = self._apply_versions(current_versions)

            cache_versions_match = bool(previous_versions) and not changed
            cache_ready = cache_versions_match and cached_count > 0

            group_counts = {}
            for feature in (self.cache_state.get("features") or {}).values():
                group = str(((feature.get("properties") or {}).get("group_id") or "")).upper()
                if group:
                    group_counts[group] = group_counts.get(group, 0) + 1

            group_summary = [
                {"group_id": group, "count": count}
                for group, count in sorted(group_counts.items())
            ]

            return {
                "ok": True,
                "bounds": None,
                "layers": [],
                "group_summary": group_summary,
                "cache_ready": cache_ready,
                "cache_count": len(self.cache_state.get("features") or {}),
                "versions_changed": sorted(changed),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def objects(self, west, south, east, north):
        if not self.region:
            return {"features": []}
        try:
            west = float(west)
            south = float(south)
            east = float(east)
            north = float(north)
            limit = 2000
            max_depth = 5

            self._refresh_versions_if_due()
            if self._cache_covers(west, south, east, north):
                return {
                    "features": self._cached_features(west, south, east, north),
                    "cache": "hit",
                }

            def feature_key(feature):
                return self._feature_key(feature)

            def fetch_cell(cw, cs, ce, cn, depth=0):
                raw = self.c.online_objects(
                    self.region,
                    f"{cw},{cs},{ce},{cn}",
                    limit=limit,
                ) or {}
                features = list(raw.get("features") or [])

                if len(features) < limit or depth >= max_depth:
                    return features

                mx = (cw + ce) / 2.0
                my = (cs + cn) / 2.0
                merged = {}
                for cell in (
                    (cw, cs, mx, my),
                    (mx, cs, ce, my),
                    (cw, my, mx, cn),
                    (mx, my, ce, cn),
                ):
                    for feature in fetch_cell(*cell, depth + 1):
                        merged[feature_key(feature)] = feature
                return list(merged.values())

            merged = {}
            mx = (west + east) / 2.0
            my = (south + north) / 2.0
            for cell in (
                (west, south, mx, my),
                (mx, south, east, my),
                (west, my, mx, north),
                (mx, my, east, north),
            ):
                for feature in fetch_cell(*cell):
                    merged[feature_key(feature)] = feature

            feature_store = self.cache_state.setdefault("features", {})
            for feature in merged.values():
                feature_store[self._feature_key(feature)] = feature

            self.cache_state.setdefault("coverage", []).append({
                "west": west,
                "south": south,
                "east": east,
                "north": north,
                "version": self._version_signature(),
            })
            self.cache_state["coverage"] = self.cache_state["coverage"][-200:]
            self._save_cache()

            return {
                "features": self._cached_features(west, south, east, north),
                "cache": "network",
            }
        except Exception as exc:
            handled = self._handle_error(exc, {"features": []})
            return handled


def html(k, local_token):
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
.layerBtn{{border:1px solid #94a3b8;background:#fff;border-radius:5px;padding:0 9px;cursor:pointer}}
.layerBtn.on{{background:#2563eb;color:#fff;border-color:#1d4ed8}}
#status{{font-size:12px;color:#334155;min-width:100px}}
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
    <select id='region' title='로그인 계정에 배정된 도면'><option value=''>권한 도면 선택</option></select>
    <button class='layerBtn on' data-group='FIBER'>광</button>
    <button class='layerBtn' data-group='COAX'>동축</button>
    <button class='layerBtn' data-group='POLE'>전주</button>
    <button class='layerBtn' data-group='CONDUIT'>관로</button>
    <button id='myLocation'>내 위치</button>
    <button id='reload'>새로고침</button>
    <span id='status'>세션 확인 중</span>
  </div>
</div>

<div id='detail'></div>

<script>
const LOCAL_API_TOKEN={json.dumps(local_token)};
async function apiCall(name,payload={{}}){{
  const response=await fetch('/api/'+name,{{
    method:'POST',
    headers:{{
      'Content-Type':'application/json',
      'X-CMB-Local-Token':LOCAL_API_TOKEN
    }},
    body:JSON.stringify(payload||{{}})
  }});
  let data={{}};
  try{{data=await response.json();}}catch(e){{}}
  if(!response.ok){{
    throw new Error((data&&data.error)||('내부 Viewer API 오류 '+response.status));
  }}
  return data;
}}
let map;
let overlays=[];
const overlayGroups=new Map();
let loadGeneration=0;
let selectedOverlay=null;
let lodReferenceSpan=null;
let idleMinutes=10;
let myLat=null,myLng=null;
let lastQueryLat=null,lastQueryLng=null,lastDetailMode=null;
let QUERY_RADIUS_METERS=500;
let QUERY_RECENTER_METERS=200;
let lastActivity=Date.now();
let idleTimer=null;
let authenticated=false;
let lastServerTouch=0;
const MAX_LEVEL=14;
const ZOOM_STEP=1.35;
const MIN_NETWORK_LEVEL=8;
const groupEnabled={{FIBER:true,COAX:false,POLE:false,CONDUIT:false,USER:false}};

function layerLevel(layer){{
  const name=String(layer||'').trim().toUpperCase();
  if(name.startsWith('TS_')||name==='TL_SCCO_SIG') return 999;
  if(['F_CABLE','FOC','FIBER','OPTIC','광케이블','광선로'].some(k=>name.includes(k))) return 0;
  const rules=[
    [['CN_C_CELLBOUND'],1],
    [['CN_C_CELLNO'],2],
    [['CN_C_ONU'],3],
    [['TL_SPRD_RW'],4],
    [['CN_C_CABLE','COAX','동축'],5],
    [['CN_C_AMP'],6],
    [['CN_F_CLOSURE','CN_F_CENTER','CN_F_TERMINAL'],7],
    [['CN_C_POWER','CN_C_TAP','CN_C_PASSIVE','CN_C_CONNECTOR','CN_C_DC_','CN_C_SUBSCRIBERS','CN_C_NMS_'],8],
    [['건물'],9],
    [['CN_M_USER_'],10],
    [['CN_L_POLE_POLE','CN_L_POLE_MANHOLE','CN_L_POLE_HANDHOLE','CN_L_POLE_LINE_'],11]
  ];
  for(const [prefixes,level] of rules){{
    if(prefixes.some(p=>name.startsWith(p))) return level;
  }}
  if(name==='CN_L_POLE') return 11;
  if(name==='0') return 12;
  if(['_ID','TEXT','LABEL','지번'].some(k=>name.includes(k))) return MAX_LEVEL;
  return 13;
}}

function viewportSpan(){{
  if(!map) return null;
  const b=map.getBounds(),sw=b.getSouthWest(),ne=b.getNorthEast();
  const lat=(sw.getLat()+ne.getLat())/2*Math.PI/180;
  const dx=(ne.getLng()-sw.getLng())*Math.cos(lat);
  const dy=(ne.getLat()-sw.getLat());
  return Math.hypot(dx,dy);
}}

function detailLevel(){{
  const span=viewportSpan();
  if(!span||!lodReferenceSpan||span>=lodReferenceSpan) return 0;
  const ratio=lodReferenceSpan/span;
  return Math.min(MAX_LEVEL,Math.max(0,Math.floor(Math.log(ratio)/Math.log(ZOOM_STEP)+1e-8)));
}}

function setStatus(t){{document.getElementById('status').textContent=t||''}}

function noteActivity(){{
  if(!authenticated)return;
  const now=Date.now();
  lastActivity=now;
  if(now-lastServerTouch>=30000){{
    lastServerTouch=now;
    apiCall('touch_session').catch(()=>{{}});
  }}
}}

async function forceIdleLogout(){{
  if(!authenticated)return;
  authenticated=false;
  setStatus('유휴시간 만료 · 최초 로그인 화면으로 이동');
  try{{await apiCall('end_session');}}catch(e){{}}
}}

function startIdleWatch(){{
  if(idleTimer)clearInterval(idleTimer);
  lastActivity=Date.now();
  idleTimer=setInterval(()=>{{
    if(!authenticated)return;
    const limit=Math.max(1,idleMinutes)*60*1000;
    if(Date.now()-lastActivity>=limit)forceIdleLogout();
  }},5000);
}}

async function loadSessionPolicy(){{
  try{{
    const r=await apiCall('session_policy');
    if(r&&r.ok&&Number(r.idle_minutes)>0)idleMinutes=Number(r.idle_minutes);
  }}catch(e){{idleMinutes=10;}}
}}

function registerOverlay(overlay,group){{
  if(!overlay)return overlay;
  const g=String(group||'').toUpperCase();
  overlays.push(overlay);
  overlayGroups.set(overlay,g);
  return overlay;
}}

function clearOverlays(){{
  loadGeneration++;
  overlays.forEach(x=>{{
    try{{x.setMap(null);}}catch(e){{}}
    overlayGroups.delete(x);
  }});
  overlays=[];
  selectedOverlay=null;
}}

function clearGroupOverlays(group){{
  const target=String(group||'').toUpperCase();
  loadGeneration++;
  const kept=[];
  overlays.forEach(x=>{{
    if(overlayGroups.get(x)===target){{
      try{{x.setMap(null);}}catch(e){{}}
      overlayGroups.delete(x);
    }}else{{
      kept.push(x);
    }}
  }});
  overlays=kept;
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
  const a=p.attributes||{{}};
  const f=a.fields||a;
  const dxf=f._cmb_dxf_data||{{}};
  const pole=f._cmb_pole_info||{{}};
  Object.keys(f).sort().forEach(k=>{{
    if(!k.startsWith('_cmb_')) add(k,f[k]);
  }});
  Object.keys(pole).sort().forEach(k=>add('전주/'+k,pole[k]));
  const labels={{insert:'삽입점',location:'위치',center:'중심점',start:'시작점',end:'끝점',rotation:'회전각',angle:'각도',radius:'반지름',xscale:'X 스케일',yscale:'Y 스케일',zscale:'Z 스케일',elevation:'표고',extrusion:'돌출방향',height:'문자높이',text:'문자',name:'이름',closed:'폐합여부'}};
  Object.keys(dxf).sort().forEach(k=>add(labels[String(k).toLowerCase()]||k,dxf[k]));
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

const SYMBOL_LIBRARY={{
  onu:{{shape:'rect',w:32,h:16,fill:'#00bcd4',stroke:'#006064',label:'ONU'}},
  amp:{{shape:'triangle',w:18,h:18,fill:'#ff9800',stroke:'#6d4c41'}},
  pole:{{shape:'circle_x',r:1.8,fill:'#ffffff',stroke:'#5d4037'}},
  tap:{{shape:'hexagon',w:18,h:16,fill:'#ffd54f',stroke:'#795548'}},
  splitter:{{shape:'circle',r:8,fill:'#fff59d',stroke:'#795548'}},
  manhole:{{shape:'double_circle',r:9,fill:'#ffffff',stroke:'#37474f'}},
  power:{{shape:'diamond',w:16,h:16,fill:'#ef5350',stroke:'#7f0000'}},
  closure:{{shape:'rect',w:22,h:12,fill:'#42a5f5',stroke:'#0d47a1'}},
  generic:{{shape:'rect',w:16,h:12,fill:'#eeeeee',stroke:'#424242'}}
}};

function symbolKind(p){{
  const a=p.attributes||{{}};
  const f=a.fields||a;
  if(f._cmb_symbol_kind)return String(f._cmb_symbol_kind);
  const s=((p.layer||'')+' '+(p.block_name||'')+' '+(p.entity_type||'')).toUpperCase();
  if(s.includes('ONU'))return 'onu';
  if(s.includes('AMP')||s.includes('증폭'))return 'amp';
  if(s.includes('MANHOLE')||s.includes('맨홀'))return 'manhole';
  if(s.includes('POLE')||s.includes('전주'))return 'pole';
  if(s.includes('2WAY')||s.includes('3WAY')||s.includes('2분기')||s.includes('3분기'))return 'splitter';
  if(s.includes('TAP'))return 'tap';
  if(s.includes('POWER'))return 'power';
  if(s.includes('CLOSURE')||s.includes('TERMINAL')||s.includes('CENTER'))return 'closure';
  return 'generic';
}}

function rotationDeg(p){{
  const a=p.attributes||{{}};
  const f=a.fields||a;
  const v=Number(f._cmb_rotation_deg ?? 0);
  return Number.isFinite(v)?v:0;
}}

function deviceLabel(p,kind){{
  if(kind==='splitter'){{
    const s=((p.layer||'')+' '+(p.block_name||'')+' '+JSON.stringify(p.attributes||{{}})).toUpperCase();
    if(s.includes('3WAY')||s.includes('3-WAY')||s.includes('3분기'))return '3';
    if(s.includes('2WAY')||s.includes('2-WAY')||s.includes('2분기'))return '2';
  }}
  return (SYMBOL_LIBRARY[kind]||{{}}).label||'';
}}

function rotatePoint(x,y,cx,cy,deg){{
  const a=deg*Math.PI/180,dx=x-cx,dy=y-cy;
  return [cx+dx*Math.cos(a)-dy*Math.sin(a),cy+dx*Math.sin(a)+dy*Math.cos(a)];
}}

function pxToLatLng(x,y){{
  const prj=map.getProjection();
  return prj.coordsFromPoint(new kakao.maps.Point(x,y));
}}

function latLngToPx(latlng){{
  return map.getProjection().pointFromCoords(latlng);
}}

function polygonPoints(kind,cx,cy,deg=0){{
  const d=SYMBOL_LIBRARY[kind]||SYMBOL_LIBRARY.generic;
  let pts=[];
  if(d.shape==='rect'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx-w,cy-h],[cx+w,cy-h],[cx+w,cy+h],[cx-w,cy+h]];
  }} else if(d.shape==='diamond'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx,cy-h],[cx+w,cy],[cx,cy+h],[cx-w,cy]];
  }} else if(d.shape==='triangle'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx,cy-h],[cx+w,cy+h],[cx-w,cy+h]];
  }} else if(d.shape==='hexagon'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx-w*.55,cy-h],[cx+w*.55,cy-h],[cx+w,cy],[cx+w*.55,cy+h],[cx-w*.55,cy+h],[cx-w,cy]];
  }}
  return pts.map(p=>rotatePoint(p[0],p[1],cx,cy,deg));
}}

function raySegmentIntersection(cx,cy,dx,dy,a,b){{
  const sx=b[0]-a[0],sy=b[1]-a[1];
  const det=(-dx*sy+dy*sx);
  if(Math.abs(det)<1e-9)return null;
  const s=(-sy*(a[0]-cx)+sx*(a[1]-cy))/det;
  const t=( dx*(a[1]-cy)-dy*(a[0]-cx))/det;
  if(s>=0&&t>=0&&t<=1)return [cx+s*dx,cy+s*dy];
  return null;
}}

function boundaryPoint(kind,cx,cy,tx,ty,deg=0){{
  let dx=tx-cx,dy=ty-cy;
  const len=Math.hypot(dx,dy)||1;
  dx/=len;dy/=len;
  const d=SYMBOL_LIBRARY[kind]||SYMBOL_LIBRARY.generic;
  if(d.shape==='circle'||d.shape==='circle_x'||d.shape==='double_circle'){{
    return [cx+dx*d.r,cy+dy*d.r];
  }}
  const pts=polygonPoints(kind,cx,cy,deg);
  let best=null,bestDist=1e9;
  for(let i=0;i<pts.length;i++){{
    const hit=raySegmentIntersection(cx,cy,dx,dy,pts[i],pts[(i+1)%pts.length]);
    if(!hit)continue;
    const dist=Math.hypot(hit[0]-cx,hit[1]-cy);
    if(dist<bestDist){{best=hit;bestDist=dist}}
  }}
  return best||[cx,cy];
}}

function drawDevice(center,props){{
  const kind=symbolKind(props);
  const d=SYMBOL_LIBRARY[kind]||SYMBOL_LIBRARY.generic;
  const px=latLngToPx(center);
  const cx=px.x,cy=px.y;
  const parts=[];
  const deg=rotationDeg(props);

  if(d.shape==='circle'||d.shape==='circle_x'||d.shape==='double_circle'){{
    const path=[];
    for(let i=0;i<20;i++){{
      const a=Math.PI*2*i/20;
      path.push(pxToLatLng(cx+Math.cos(a)*d.r,cy+Math.sin(a)*d.r));
    }}
    const poly=new kakao.maps.Polygon({{path:path,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillColor:d.fill,fillOpacity:.95}});
    poly.setMap(map);registerOverlay(poly,props.group_id);parts.push(poly);bindClick(poly,props);
    if(d.shape==='double_circle'){{
      const path2=[];
      for(let i=0;i<20;i++){{
        const a=Math.PI*2*i/20;
        path2.push(pxToLatLng(cx+Math.cos(a)*d.r*.62,cy+Math.sin(a)*d.r*.62));
      }}
      const inner=new kakao.maps.Polygon({{path:path2,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillOpacity:0}});
      inner.setMap(map);registerOverlay(inner,props.group_id);parts.push(inner);bindClick(inner,props);
    }}
    if(d.shape==='circle_x'){{
      const a1=pxToLatLng(cx-d.r*.7,cy-d.r*.7),a2=pxToLatLng(cx+d.r*.7,cy+d.r*.7);
      const b1=pxToLatLng(cx-d.r*.7,cy+d.r*.7),b2=pxToLatLng(cx+d.r*.7,cy-d.r*.7);
      [ [a1,a2],[b1,b2] ].forEach(path2=>{{
        const l=new kakao.maps.Polyline({{path:path2,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1}});
        l.setMap(map);registerOverlay(l,props.group_id);parts.push(l);bindClick(l,props);
      }});
    }}
  }}else{{
    const pts=polygonPoints(kind,cx,cy,deg).map(p=>pxToLatLng(p[0],p[1]));
    const poly=new kakao.maps.Polygon({{path:pts,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillColor:d.fill,fillOpacity:.95}});
    poly.setMap(map);registerOverlay(poly,props.group_id);parts.push(poly);bindClick(poly,props);
  }}

  const a=deg*Math.PI/180;
  const dirLen=Math.max(6,(d.r||Math.max(d.w||0,d.h||0)/2)*.9);
  const dirEnd=pxToLatLng(cx+Math.sin(a)*dirLen,cy-Math.cos(a)*dirLen);
  const dirLine=new kakao.maps.Polyline({{path:[center,dirEnd],strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1}});
  dirLine.setMap(map);registerOverlay(dirLine,props.group_id);parts.push(dirLine);

  const labelText=deviceLabel(props,kind);
  if(labelText){{
    const label=new kakao.maps.CustomOverlay({{
      position:center,
      content:'<div style="font:700 10px Malgun Gothic;color:#00363a;transform:translate(-50%,-50%);pointer-events:none">'+esc(labelText)+'</div>',
      yAnchor:.5,xAnchor:.5
    }});
    label.setMap(map);registerOverlay(label,props.group_id);parts.push(label);
  }}

  return {{kind,center,cx,cy,props,parts,deg}};
}}

function snapCablePath(coords,devices){{
  if(coords.length<2||!devices.length)return coords.map(a=>new kakao.maps.LatLng(a[1],a[0]));
  const pts=coords.map(a=>new kakao.maps.LatLng(a[1],a[0]));
  const px=pts.map(latlngToPx);
  const threshold=26;

  function snapEnd(index,neighborIndex){{
    let best=null,bestDist=1e9;
    for(const dev of devices){{
      const dist=Math.hypot(px[index].x-dev.cx,px[index].y-dev.cy);
      if(dist<threshold&&dist<bestDist){{best=dev;bestDist=dist}}
    }}
    if(!best)return;
    const target=px[neighborIndex];
    const bp=boundaryPoint(best.kind,best.cx,best.cy,target.x,target.y,best.deg||0);
    pts[index]=pxToLatLng(bp[0],bp[1]);
  }}

  snapEnd(0,1);
  snapEnd(pts.length-1,pts.length-2);
  return pts;
}}

function bindClick(overlay,props){{
  kakao.maps.event.addListener(overlay,'click',()=>showDetail(props||{{}}));
}}

function distanceMeters(lat1,lng1,lat2,lng2){{
  const R=6371000;
  const p1=lat1*Math.PI/180,p2=lat2*Math.PI/180;
  const dp=(lat2-lat1)*Math.PI/180;
  const dl=(lng2-lng1)*Math.PI/180;
  const a=Math.sin(dp/2)*Math.sin(dp/2)+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);
  return 2*R*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

async function loadObjects(force=false){{
  const region=document.getElementById('region').value;
  if(!region||!map)return;
  const center=map.getCenter();
  const queryLat=Number(center.getLat());
  const queryLng=Number(center.getLng());
  const mapLevelNow=map.getLevel();
  const detailMode=mapLevelNow<=3;
  // L4 이상부터 네트워크 도면 오버레이를 전부 숨긴다.
  // 이전 L1~L3 서버 요청이 늦게 끝나더라도 loadGeneration 검증으로 다시 그리지 못한다.
  if(!detailMode){{
    clearOverlays();
    lastQueryLat=queryLat;
    lastQueryLng=queryLng;
    lastDetailMode=false;
    setStatus('L'+mapLevelNow+' · 도면 숨김 · L3 이하에서 광/동축/전주/관로 표시');
    return;
  }}

  if(!force && Number.isFinite(lastQueryLat) && Number.isFinite(lastQueryLng)){{
    const moved=distanceMeters(lastQueryLat,lastQueryLng,queryLat,queryLng);
    if(moved<QUERY_RECENTER_METERS && lastDetailMode===detailMode)return;
  }}

  const myGeneration=++loadGeneration;
  const latDelta=QUERY_RADIUS_METERS/111320;
  const lngScale=Math.max(0.2,Math.cos(queryLat*Math.PI/180));
  const lngDelta=QUERY_RADIUS_METERS/(111320*lngScale);
  const west=queryLng-lngDelta;
  const east=queryLng+lngDelta;
  const south=queryLat-latDelta;
  const north=queryLat+latDelta;

  setStatus('지도 중심 '+QUERY_RADIUS_METERS+'m · 불러오는 중...');
  const r=await apiCall('objects',{{west:west,south:south,east:east,north:north}});
  if(myGeneration!==loadGeneration)return;
  if(region!==document.getElementById('region').value)return;
  if(map.getLevel()>3){{clearOverlays();return;}}
  if(r.error){{setStatus(r.error);return}}
  lastQueryLat=queryLat;
  lastQueryLng=queryLng;
  lastDetailMode=detailMode;
  const previousOverlays=overlays;
  overlays=[];
  selectedOverlay=null;
  const allFeatures=r.features||[];
  const mapLevel=map.getLevel();
  const isMaxDetail=mapLevel<=3;
  const features=allFeatures.filter(f=>{{
    const p=f.properties||{{}};
    const layerName=String(p.layer||'').trim().toUpperCase();
    if(layerName.startsWith('TS_')||layerName==='TL_SCCO_SIG') return false;

    const group=String(p.group_id||'').toUpperCase();

    // L1~L3에서 체크된 네트워크 그룹을 표시한다.
    return isMaxDetail && groupEnabled[group]===true;
  }});
  const pointFeatures=features.filter(f=>{{
    if((f.geometry||{{}}).type!=='Point')return false;
    const p=f.properties||{{}},a=p.attributes||{{}},fields=a.fields||a;
    return fields._cmb_is_device!==false;
  }});
  const lineFeatures=features.filter(f=>['LineString','MultiLineString'].includes((f.geometry||{{}}).type));
  const devices=[];

  pointFeatures.forEach(f=>{{
    const g=f.geometry||{{}},p=f.properties||{{}};
    const a=g.coordinates;
    if(!Array.isArray(a)||a.length<2||a[0]===null||a[1]===null||
      !Number.isFinite(Number(a[0]))||!Number.isFinite(Number(a[1])))return;
    try{{devices.push(drawDevice(new kakao.maps.LatLng(Number(a[1]),Number(a[0])),p));}}
    catch(e){{console.warn('Device render failed',e);}}
  }});

  let renderedLines=0;
  const renderedByGroup={{FIBER:0,COAX:0,CONDUIT:0,POLE:0,USER:0}};

  lineFeatures.forEach(f=>{{
    const g=f.geometry||{{}};
    const p=f.properties||{{}};
    const group=String(p.group_id||'').toUpperCase();
    const c=colorFor(group);
    const parts=g.type==='MultiLineString' ? (g.coordinates||[]) : [g.coordinates||[]];

    parts.forEach(before=>{{
      if(!Array.isArray(before))return;

      // 원본 좌표를 먼저 정상화한다.
      const validCoords=before.filter(a=>Array.isArray(a)&&a.length>=2&&
        a[0]!==null&&a[1]!==null&&a[0]!==''&&a[1]!==''&&
        Number.isFinite(Number(a[0]))&&Number.isFinite(Number(a[1]))&&
        Math.abs(Number(a[0]))<=180&&Math.abs(Number(a[1]))<=90)
        .map(a=>[Number(a[0]),Number(a[1])]);
      const originalPath=validCoords.map(a=>new kakao.maps.LatLng(a[1],a[0]));

      if(originalPath.length<2)return;

      // 스냅은 보조 기능이다. 스냅 결과가 잘못되면 반드시 원본 선을 사용한다.
      let path=originalPath;
      try{{
        const snappedPath=snapCablePath(validCoords,devices);
        if(Array.isArray(snappedPath)&&snappedPath.length>=2&&snappedPath.every(a=>
          a&&typeof a.getLat==='function'&&typeof a.getLng==='function'&&
          Number.isFinite(a.getLat())&&Number.isFinite(a.getLng())&&
          Math.abs(a.getLat())<=90&&Math.abs(a.getLng())<=180))path=snappedPath;
      }}catch(e){{
        path=originalPath;
      }}

      const l=new kakao.maps.Polyline({{
        path:path,
        strokeWeight:4,
        strokeColor:c,
        strokeOpacity:.95,
        strokeStyle:'solid'
      }});
      l.setMap(map);
      if(typeof l.setZIndex==='function')l.setZIndex(5);
      registerOverlay(l,group);
      bindClick(l,p);

      renderedLines++;
      if(renderedByGroup[group]===undefined)renderedByGroup[group]=0;
      renderedByGroup[group]++;
    }});
  }});

  previousOverlays.forEach(x=>{{
    try{{x.setMap(null);}}catch(e){{}}
    overlayGroups.delete(x);
  }});
  const visibleGroups=Object.keys(groupEnabled).filter(k=>groupEnabled[k]&&k!=='USER').join('/');
  const rawGroups={{}};
  allFeatures.forEach(f=>{{
    const g=String(((f.properties||{{}}).group_id)||'NONE').toUpperCase();
    rawGroups[g]=(rawGroups[g]||0)+1;
  }});
  const rawText=Object.keys(rawGroups).sort().map(k=>k+':'+rawGroups[k]).join('/');

  const geomStats={{}};
  allFeatures.forEach(f=>{{
    const group=String(((f.properties||{{}}).group_id)||'NONE').toUpperCase();
    const type=String(((f.geometry||{{}}).type)||'');
    if(!geomStats[group])geomStats[group]={{line:0,point:0,other:0}};
    if(type==='LineString'||type==='MultiLineString')geomStats[group].line++;
    else if(type==='Point')geomStats[group].point++;
    else geomStats[group].other++;
  }});
  const cableDiag=['FIBER','COAX','CONDUIT'].map(g=>{{
    const s=geomStats[g]||{{line:0,point:0,other:0}};
    return g+' 선:'+s.line+'/점:'+s.point;
  }}).join(' · ');

  setStatus(
    'L'+map.getLevel()+
    ' · 서버 '+allFeatures.length+'개 ['+rawText+']'+
    ' · '+cableDiag+
    ' · 표시 '+features.length+
    ' · 심볼 '+devices.length+
    ' · 렌더선 '+renderedLines+
    ' [F:'+String(renderedByGroup.FIBER||0)+
    '/C:'+String(renderedByGroup.COAX||0)+
    '/D:'+String(renderedByGroup.CONDUIT||0)+']'
  );
}}

async function loadRegions(){{
  const r=await apiCall('regions');
  if(!r.ok){{setStatus('지역 조회 실패 · '+(r.error||'서버 오류'));return}}
  const sel=document.getElementById('region');
  const items=(r.items||[]).filter(x=>x&&x.id);
  sel.innerHTML='<option value="">권한 지역 선택</option>';
  items.forEach(x=>{{
    const o=document.createElement('option');
    o.value=String(x.id);
    o.text=(x.name&&x.name!==x.id) ? (x.name+' ('+x.id+')') : String(x.id);
    sel.appendChild(o);
  }});
  if(!items.length){{
    setStatus('권한 지역 0개 · 관리자 지역 권한 설정을 확인하세요 · 등급 '+String(r.level||'?'));
    return;
  }}
  setStatus('권한 지역 '+items.length+'개 · 등급 '+String(r.level||'?'));
}}

async function loadMapDisplaySettings(){{
  try{{
    const r=await apiCall('map_display_settings');
    if(r&&r.ok!==false){{
      const radius=Number(r.radius_m||500);
      const refresh=Number(r.refresh_distance_m||200);
      QUERY_RADIUS_METERS=Math.max(100,Math.min(3000,radius));
      QUERY_RECENTER_METERS=Math.max(25,Math.min(QUERY_RADIUS_METERS,refresh));
    }}
  }}catch(e){{}}
}}

async function bootstrapAuth(){{
  try{{
    // 런처가 자식 실행 직전에 /me 검증을 완료한다.
    // pywebview 예약/미노출 함수명 문제를 피하기 위해 별도 bootstrap RPC를 사용하지 않는다.
    authenticated=true;
    setStatus('권한 지역 조회 중');
    await loadRegions();

    // 지역 조회 성공 여부와 무관하게 UI를 막지 않는 부가 기능만 뒤에서 실행한다.
    startIdleWatch();
    loadSessionPolicy().catch(()=>{{}});
    return true;
  }}catch(e){{
    authenticated=false;
    const msg=(e&&e.message)?e.message:'알 수 없는 오류';
    setStatus('지역 조회 오류 · '+msg);
    return false;
  }}
}}

function bindUi(){{
  document.getElementById('reload').onclick=()=>loadObjects(true);
  document.getElementById('myLocation').onclick=()=>centerMyLocation(true);

  document.querySelectorAll('.layerBtn').forEach(btn=>{{
    btn.onclick=()=>{{
      const g=String(btn.dataset.group||'').toUpperCase();
      groupEnabled[g]=!groupEnabled[g];
      btn.classList.toggle('on',groupEnabled[g]);

      if(groupEnabled[g]){{
        loadObjects(true);
      }}else{{
        clearGroupOverlays(g);
        const active=Object.keys(groupEnabled).filter(k=>groupEnabled[k]).join('/');
        setStatus(
          'L'+map.getLevel()+
          ' · '+g+' 즉시 숨김'+
          (active ? ' · 활성 '+active : ' · 활성 그룹 없음')
        );
      }}
    }};
  }});

  document.getElementById('region').onchange=async e=>{{
    clearOverlays();
    document.getElementById('detail').style.display='none';
    const r=await apiCall('select',{{region:e.target.value}});
    if(!r.ok){{setStatus(r.error||'지역 선택 실패');return}}
    const summary=(r.group_summary||[]).map(x=>String(x.group_id)+':'+String(x.count||0)).join(' / ');
    if(r.cache_ready){{
      setStatus('캐시 즉시 표시 준비 · '+String(r.cache_count||0)+'개'+(summary?' · '+summary:''));
    }}else if(summary){{
      setStatus('캐시 갱신 필요 · '+summary);
    }}
    if(!map){{
      setStatus('카카오맵 초기화 대기');
      return;
    }}
    if(Number.isFinite(myLat)&&Number.isFinite(myLng)){{
      map.setCenter(new kakao.maps.LatLng(myLat,myLng));
      map.setLevel(3);
      setTimeout(()=>loadObjects(true),80);
      return;
    }}
    centerMyLocation(true);
  }};

}}

function centerMyLocation(loadAfter){{
  if(!navigator.geolocation){{
    setStatus('현재 위치 기능을 사용할 수 없습니다');
    return;
  }}
  setStatus('현재 위치 확인 중');
  navigator.geolocation.getCurrentPosition(
    pos=>{{
      if(!map)return;
      const lat=Number(pos.coords.latitude);
      const lng=Number(pos.coords.longitude);
      myLat=lat;
      myLng=lng;
      map.setCenter(new kakao.maps.LatLng(lat,lng));
      map.setLevel(3);
      setStatus('현재 위치 · 반경 '+QUERY_RADIUS_METERS+'m');
      if(loadAfter)loadObjects(true);
    }},
    err=>{{
      setStatus('현재 위치 확인 실패');
    }},
    {{enableHighAccuracy:true,timeout:8000,maximumAge:30000}}
  );
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
        level:3
      }});
      kakao.maps.event.addListener(map,'idle',()=>loadObjects());
      kakao.maps.event.addListener(map,'zoom_changed',()=>{{
        if(map.getLevel()>3)clearOverlays();
      }});
      centerMyLocation(false);
      const sel=document.getElementById('region');
      if(sel&&sel.value){{
        sel.dispatchEvent(new Event('change'));
      }} else {{
        setStatus('현재 위치 확인 후 지역을 선택하세요');
      }}
    }});
  }}catch(err){{
    setStatus('카카오맵 초기화 오류');
  }}
}}

['pointerdown','pointermove','keydown','wheel','touchstart'].forEach(
  eventName=>document.addEventListener(eventName,noteActivity,{{passive:true}})
);
document.addEventListener('visibilitychange',()=>{{
  if(document.visibilityState==='visible')noteActivity();
}});
bindUi();
initMap();

let authBootstrapped=false;
async function runBootstrapOnce(){{
  if(authBootstrapped)return;
  authBootstrapped=true;
  await loadMapDisplaySettings();
  await bootstrapAuth();
}}
runBootstrapOnce();
</script>
</body>
</html>"""


def run_online_viewer():
    k = key()
    if not k:
        return 2

    import webview

    api = Api()

    # 런처가 자식 실행 직전에 검증한 세션이 없으면 Viewer를 열지 않는다.
    if not api.c.access_token:
        api.session_ended = True
        return SESSION_ENDED_EXIT_CODE

    local_token = secrets.token_urlsafe(32)
    page = html(k, local_token).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            if not self.path.startswith("/api/"):
                self._json(404, {"ok": False, "error": "API 경로 없음"})
                return

            if self.headers.get("X-CMB-Local-Token", "") != local_token:
                self._json(403, {"ok": False, "error": "로컬 Viewer 인증 실패"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8")) if body else {}
                name = self.path[len("/api/"):].split("?", 1)[0]

                if name == "regions":
                    result = api.regions()
                elif name == "select":
                    result = api.select(data.get("region"))
                elif name == "objects":
                    result = api.objects(
                        data.get("west"),
                        data.get("south"),
                        data.get("east"),
                        data.get("north"),
                    )
                elif name == "map_display_settings":
                    result = api.map_display_settings()
                elif name == "session_policy":
                    result = api.session_policy()
                elif name == "touch_session":
                    result = api.touch_session()
                elif name == "end_session":
                    result = api.end_session()
                else:
                    self._json(404, {"ok": False, "error": "지원하지 않는 API"})
                    return

                if isinstance(result, dict) and result.get("error") and result.get("ok") is False:
                    self._json(400, result)
                else:
                    self._json(200, result if result is not None else {"ok": True})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        window = webview.create_window(
            "CMB 온라인 Viewer",
            url="http://127.0.0.1:8765/",
            width=1450,
            height=900,
            min_size=(900, 600),
        )
        api.window = window
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.shutdown()
        server.server_close()

    return SESSION_ENDED_EXIT_CODE if api.session_ended else 0

