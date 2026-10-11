from __future__ import annotations

import hashlib
import json
import math

from converter import load_dxf_document


STYLE_KEYS = (
    "color", "true_color", "lineweight", "linetype", "ltscale",
    "transparency", "thickness",
)


def _number(value, default=None):
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except Exception:
        return default


def _jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "x") and hasattr(value, "y"):
        vals = [float(value.x), float(value.y)]
        if hasattr(value, "z"):
            vals.append(float(value.z))
        return vals
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _dxf_value(entity, name, default=None):
    try:
        return _jsonable(getattr(entity.dxf, name))
    except Exception:
        return default


def _entity_style_from_scene(entity):
    dxf = dict(getattr(entity, "dxf_data", {}) or {})
    style = {}
    for key in STYLE_KEYS:
        value = dxf.get(key)
        if value not in (None, ""):
            style[key] = _jsonable(value)
    if getattr(entity, "color", None):
        style["display_color"] = str(entity.color)
    return style


def _connection_handles(entity):
    links = []
    xdata = dict(getattr(entity, "xdata", []) or [])
    for values in xdata.values():
        for item in values or []:
            text = str(item)
            if text.startswith("1005:"):
                handle = text.split(":", 1)[1].strip().upper()
                if handle and handle != "0":
                    links.append(handle)
    return list(dict.fromkeys(links))


def _serialize_block_entity(entity):
    typ = entity.dxftype()
    base = {
        "type": typ,
        "layer": str(_dxf_value(entity, "layer", "0") or "0"),
    }
    for key in STYLE_KEYS:
        value = _dxf_value(entity, key)
        if value not in (None, ""):
            base[key] = value

    if typ == "LINE":
        base["start"] = _dxf_value(entity, "start")
        base["end"] = _dxf_value(entity, "end")
    elif typ == "LWPOLYLINE":
        base["points"] = [[float(x), float(y), float(sw), float(ew), float(b)]
                          for x, y, sw, ew, b in entity.get_points("xyseb")]
        base["closed"] = bool(getattr(entity, "closed", False))
    elif typ == "POLYLINE":
        base["points"] = [[float(v.dxf.location.x), float(v.dxf.location.y)]
                          for v in entity.vertices]
        base["closed"] = bool(getattr(entity, "is_closed", False))
    elif typ == "CIRCLE":
        base["center"] = _dxf_value(entity, "center")
        base["radius"] = _number(_dxf_value(entity, "radius"), 0.0)
    elif typ == "ARC":
        base["center"] = _dxf_value(entity, "center")
        base["radius"] = _number(_dxf_value(entity, "radius"), 0.0)
        base["start_angle"] = _number(_dxf_value(entity, "start_angle"), 0.0)
        base["end_angle"] = _number(_dxf_value(entity, "end_angle"), 0.0)
    elif typ in {"TEXT", "ATTDEF"}:
        base["insert"] = _dxf_value(entity, "insert")
        base["text"] = str(_dxf_value(entity, "text", "") or "")
        base["height"] = _number(_dxf_value(entity, "height"), 1.0)
        base["rotation"] = _number(_dxf_value(entity, "rotation"), 0.0)
        if typ == "ATTDEF":
            base["tag"] = str(_dxf_value(entity, "tag", "") or "")
            base["prompt"] = str(_dxf_value(entity, "prompt", "") or "")
    elif typ == "MTEXT":
        base["insert"] = _dxf_value(entity, "insert")
        try:
            base["text"] = str(entity.plain_text() or "")
        except Exception:
            base["text"] = str(_dxf_value(entity, "text", "") or "")
        base["char_height"] = _number(_dxf_value(entity, "char_height"), 1.0)
        base["rotation"] = _number(_dxf_value(entity, "rotation"), 0.0)
    elif typ == "INSERT":
        base["name"] = str(_dxf_value(entity, "name", "") or "")
        base["insert"] = _dxf_value(entity, "insert")
        base["rotation"] = _number(_dxf_value(entity, "rotation"), 0.0)
        base["xscale"] = _number(_dxf_value(entity, "xscale"), 1.0)
        base["yscale"] = _number(_dxf_value(entity, "yscale"), 1.0)
        base["zscale"] = _number(_dxf_value(entity, "zscale"), 1.0)
    elif typ == "POINT":
        base["location"] = _dxf_value(entity, "location")
    else:
        return None
    return base


def build_symbol_library(source_path, scene, group, classify_entity):
    used = {
        str(e.block_name or "")
        for e in scene.entities
        if classify_entity(e) == group and str(e.entity_type or "").upper() == "INSERT"
        and str(e.block_name or "")
    }
    if not used:
        return []

    doc = load_dxf_document(source_path)
    definitions = {}
    queue = list(used)
    seen = set()

    while queue:
        name = queue.pop(0)
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            block = doc.blocks.get(name)
        except Exception:
            continue

        entities = []
        nested = []
        for item in block:
            row = _serialize_block_entity(item)
            if row is None:
                continue
            entities.append(row)
            if row.get("type") == "INSERT" and row.get("name"):
                nested.append(row["name"])

        payload = {"name": name, "entities": entities}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")
        symbol_hash = hashlib.sha256(canonical).hexdigest()
        definitions[name] = {
            "symbol_id": symbol_hash[:24],
            "symbol_hash": symbol_hash,
            "name": name,
            "definition": payload,
        }
        for child in nested:
            if child not in seen:
                queue.append(child)

    return list(definitions.values())


def enrich_payload_v2(scene, source_path, group, payload, classify_entity):
    by_handle = {str(e.handle or ""): e for e in scene.entities if str(e.handle or "")}

    for obj in payload.get("objects") or []:
        handle = str(obj.get("source_handle") or "")
        entity = by_handle.get(handle)
        if entity is None:
            continue
        attrs = dict(obj.get("attributes") or {})
        attrs["_cmb_backup_schema"] = 2
        attrs["_cmb_original_handle"] = handle
        attrs["_cmb_style"] = _entity_style_from_scene(entity)
        attrs["_cmb_connections"] = _connection_handles(entity)
        attrs["_cmb_rotation_deg"] = _number(
            (getattr(entity, "dxf_data", {}) or {}).get("rotation"),
            attrs.get("_cmb_rotation_deg", 0.0),
        )
        attrs["_cmb_xscale"] = _number(
            (getattr(entity, "dxf_data", {}) or {}).get("xscale"),
            attrs.get("_cmb_xscale", 1.0),
        )
        attrs["_cmb_yscale"] = _number(
            (getattr(entity, "dxf_data", {}) or {}).get("yscale"),
            attrs.get("_cmb_yscale", 1.0),
        )
        attrs["_cmb_zscale"] = _number(
            (getattr(entity, "dxf_data", {}) or {}).get("zscale"),
            attrs.get("_cmb_zscale", 1.0),
        )
        if entity.block_name:
            attrs["_cmb_symbol_name"] = str(entity.block_name)
        obj["attributes"] = attrs

    symbols = build_symbol_library(source_path, scene, group, classify_entity)
    payload["package_schema"] = "cmb-network-package-v2"
    payload["symbol_library"] = symbols
    payload["symbol_count"] = len(symbols)
    return payload
