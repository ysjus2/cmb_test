"""Resolve complete POLE numbers using source CAD Polemap boundaries and labels.

Strict matching: no closest-pole guesses. A POLE is resolved only when its
insertion point belongs to exactly one labeled management polygon.
"""
import math
import re

GRID = re.compile(r"^[0-9]{4}[A-Z]$")
FULL = re.compile(r"^[0-9]{4}[A-Z][A-Z0-9]{3,27}$")
LOCAL = re.compile(r"^[A-Z0-9]{3,27}$")
BOUND = "CN_L_POLEMAP_BOUND"
LABEL = "CN_L_POLEMAP_IDXMAIN"

POLES = {
    "CN_L_POLE_POLE-JOINT",
    "CN_L_POLE_POLE-JOINT-TRS",
    "CN_L_POLE_POLE-CATV",
    "CN_L_POLE_POLE-STEEL",
    "CN_L_POLE_POLE-CONCRETE",
}

def _anchor(e):
    for kind, p in (getattr(e, "primitives", None) or []):
        if kind in ("insert", "point", "text") and len(p) >= 2:
            return float(p[0]), float(p[1])
    return None

def _polygon(e):
    for kind, data in (getattr(e, "primitives", None) or []):
        if kind in ("polyline", "polygon") and len(data) >= 4:
            pts = [(float(x), float(y)) for x,y in data]
            if pts[0] != pts[-1]:
                # Do not turn an unclosed line into a management zone.
                continue
            return pts
    return None

def _inside(point, polygon):
    x,y = point
    inside = False
    for i in range(len(polygon)-1):
        a,b=polygon[i],polygon[i+1]
        x1,y1=a; x2,y2=b
        if ((y1 > y) != (y2 > y)):
            cross = x1+(y-y1)*(x2-x1)/(y2-y1)
            if cross > x: inside = not inside
    return inside

def _box(polygon):
    return (min(p[0] for p in polygon), min(p[1] for p in polygon),
            max(p[0] for p in polygon), max(p[1] for p in polygon))

def _in_box(p,b):
    return b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]

def _local(e):
    attrs = getattr(e, "attributes", {}) or {}
    for val in (attrs.get("_cmb_pole_no"), attrs.get("NO"),
                attrs.get("ID"), attrs.get("전주번호")):
        t = str(val or "").strip().upper().strip("() ")
        if FULL.fullmatch(t): return t
    c = []
    for key,val in attrs.items():
        if not any(tok in str(key).upper() for tok in ("NO","ID","POLE","전주","번호")): continue
        t=str(val or "").strip().upper().strip("() ")
        if LOCAL.fullmatch(t) and not GRID.fullmatch(t) and t not in c: c.append(t)
    return c[0] if len(c)==1 else None

def resolve_pole_numbers(scene):
    polygons=[]
    for e in scene.entities:
        if str(e.layer or "").upper() != BOUND: continue
        points=_polygon(e)
        if points: polygons.append({"pts":points,"box":_box(points),"labels":set()})
    labels=0; ambiguities=0
    for e in scene.entities:
        if str(e.layer or "").upper()!=LABEL: continue
        value=str(getattr(e,"text","") or "").strip().upper()
        if not GRID.fullmatch(value): continue
        p=_anchor(e)
        if p is None: continue
        matches=[z for z in polygons if _in_box(p,z["box"]) and _inside(p,z["pts"])]
        if len(matches)==1:
            matches[0]["labels"].add(value); labels+=1
        else:
            ambiguities+=1
    valid=[z for z in polygons if len(z["labels"])==1]
    resolved={}; failed=0; already=0
    for e in scene.entities:
        if str(e.layer or "").upper() not in POLES or str(e.entity_type).upper()!="INSERT":continue
        token=_local(e)
        if token is None: failed+=1;continue
        if FULL.fullmatch(token): resolved[e.handle]=token;already+=1;continue
        p=_anchor(e)
        if p is None:failed+=1;continue
        matches=[z for z in valid if _in_box(p,z["box"]) and _inside(p,z["pts"])]
        if len(matches)!=1: failed+=1;continue
        grid=next(iter(matches[0]["labels"]))
        resolved[e.handle]=grid+token
    stats={"boundaries":len(polygons),"labeled_boundaries":len(valid),
           "labels_mapped":labels,"labels_ambiguous":ambiguities,
           "resolved":len(resolved),"already_full":already,"unresolved":failed}
    return resolved,stats
