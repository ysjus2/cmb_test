"""Extract existing pole identification from the original pole INSERT only.

The individual NO is the INSERT's ID attribute (CN_L_Pole_ID).
The five-character management grid is an EXMAP_POLE XDATA 1000 string.
No geometry-based guess, nearby poles, or Polemap polygon inference is used.
"""
import re

GRID = re.compile(r"^[0-9]{4}[A-Z]$")
FULL = re.compile(r"^[0-9]{4}[A-Z][A-Z0-9]{3,27}$")
LOCAL = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,63}$")
POLES = {
    "CN_L_POLE_POLE-JOINT",
    "CN_L_POLE_POLE-JOINT-TRS",
    "CN_L_POLE_POLE-CATV",
    "CN_L_POLE_POLE-STEEL",
    "CN_L_POLE_POLE-CONCRETE",
}

def _id_value(e):
    attrs = getattr(e, "attributes", {}) or {}
    raw = str(attrs.get("ID") or "").strip().upper()
    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1].strip()
    return raw

def _grid_values(e):
    result = set()
    for appid, values in (getattr(e, "xdata", None) or []):
        if str(appid).strip().upper() != "EXMAP_POLE":
            continue
        for item in values or []:
            raw = str(item).strip()
            # The viewer preserves XDATA as "1000: VALUE" strings.
            match = re.fullmatch(r"1000:\s*(.*)", raw, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip().upper()
                if GRID.fullmatch(candidate):
                    result.add(candidate)
    return result

def resolve_pole_numbers(scene):
    resolved = {}
    reasons = {"id_missing_or_invalid":0, "grid_missing":0, "grid_ambiguous":0}
    samples = {k:[] for k in reasons}
    total = 0
    for e in scene.entities:
        if str(e.layer or "").upper() not in POLES or str(e.entity_type or "").upper() != "INSERT":
            continue
        total += 1
        local = _id_value(e)
        if FULL.fullmatch(local):
            resolved[e.handle] = local
            continue
        if not local or local == "-" or not LOCAL.fullmatch(local):
            reason="id_missing_or_invalid"
        else:
            grids = _grid_values(e)
            if len(grids)==0: reason="grid_missing"
            elif len(grids)!=1: reason="grid_ambiguous"
            else:
                resolved[e.handle] = next(iter(grids)) + local
                continue
        reasons[reason] += 1
        if len(samples[reason]) < 5:
            samples[reason].append({
                "handle":str(e.handle),"layer":str(e.layer),
                "id": local,"grids":sorted(_grid_values(e))
            })
    stats={"pole_objects":total,"resolved":len(resolved),
           "unresolved":total-len(resolved),"reasons":reasons,"samples":samples,
           "method":"INSERT.ID + INSERT.XDATA.EXMAP_POLE.1000"}
    return resolved, stats
