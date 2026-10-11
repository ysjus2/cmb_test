from __future__ import annotations

import json
import math
import re


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _float(value, default=0.0):
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _int(value, default=None):
    try:
        return int(float(value))
    except Exception:
        return default


def _safe_layer(name):
    text = str(name or "SERVER").replace("/", "_").strip()[:240]
    return text or "SERVER"


def _style_dxfattrs(style, layer):
    style = _as_dict(style)
    out = {"layer": layer}
    color = _int(style.get("color"))
    if color is not None and 0 <= color <= 256:
        out["color"] = color
    true_color = _int(style.get("true_color"))
    if true_color is not None and 0 <= true_color <= 0xFFFFFF:
        out["true_color"] = true_color
    lineweight = _int(style.get("lineweight"))
    if lineweight is not None:
        out["lineweight"] = lineweight
    ltscale = _float(style.get("ltscale"), None)
    if ltscale is not None:
        out["ltscale"] = ltscale
    return out


def _point(value, default=(0.0, 0.0, 0.0)):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        z = _float(value[2], 0.0) if len(value) > 2 else 0.0
        return (_float(value[0]), _float(value[1]), z)
    return default


def _symbol_rows(symbol_payload):
    if isinstance(symbol_payload, dict):
        rows = symbol_payload.get("symbols") or symbol_payload.get("items") or []
    else:
        rows = symbol_payload or []
    return [r for r in rows if isinstance(r, dict)]


def install_symbol_library(doc, symbol_payload):
    rows = _symbol_rows(symbol_payload)
    definitions = {}
    symbol_ids = {}
    for row in rows:
        definition = row.get("definition") or {}
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except Exception:
                definition = {}
        name = str(row.get("name") or definition.get("name") or "").strip()
        if name and isinstance(definition, dict):
            definitions[name] = definition
            sid = str(row.get("symbol_id") or "").strip()
            if sid:
                symbol_ids[name] = sid

    block_name_map = {}
    for name in definitions:
        actual = name
        try:
            if actual not in doc.blocks:
                doc.blocks.new(name=actual)
        except Exception:
            actual = "CMB_" + re.sub(r"[^A-Za-z0-9_]+", "_", name)[:120]
            if actual not in doc.blocks:
                doc.blocks.new(name=actual)
        block_name_map[name] = actual

    def add_entity(block, row):
        typ = str(row.get("type") or "").upper()
        layer = _safe_layer(row.get("layer") or "0")
        if layer not in doc.layers:
            try:
                doc.layers.add(layer)
            except Exception:
                layer = "0"
        attrs = _style_dxfattrs(row, layer)

        if typ == "LINE":
            return block.add_line(_point(row.get("start")), _point(row.get("end")), dxfattribs=attrs)
        if typ == "LWPOLYLINE":
            pts = row.get("points") or []
            e = block.add_lwpolyline(pts, format="xyseb", dxfattribs=attrs)
            e.closed = bool(row.get("closed"))
            return e
        if typ == "POLYLINE":
            pts = [tuple(_point(p)[:2]) for p in row.get("points") or []]
            e = block.add_polyline2d(pts, dxfattribs=attrs)
            try:
                e.close(bool(row.get("closed")))
            except Exception:
                pass
            return e
        if typ == "CIRCLE":
            return block.add_circle(_point(row.get("center")), _float(row.get("radius")), dxfattribs=attrs)
        if typ == "ARC":
            return block.add_arc(
                _point(row.get("center")),
                _float(row.get("radius")),
                _float(row.get("start_angle")),
                _float(row.get("end_angle")),
                dxfattribs=attrs,
            )
        if typ == "TEXT":
            attrs.update({
                "insert": _point(row.get("insert")),
                "height": _float(row.get("height"), 1.0),
                "rotation": _float(row.get("rotation")),
            })
            return block.add_text(str(row.get("text") or ""), dxfattribs=attrs)
        if typ == "MTEXT":
            attrs.update({
                "insert": _point(row.get("insert")),
                "char_height": _float(row.get("char_height"), 1.0),
            })
            e = block.add_mtext(str(row.get("text") or ""), dxfattribs=attrs)
            try:
                e.dxf.rotation = _float(row.get("rotation"))
            except Exception:
                pass
            return e
        if typ == "ATTDEF":
            return block.add_attdef(
                tag=str(row.get("tag") or "ATTR"),
                insert=_point(row.get("insert")),
                text=str(row.get("text") or ""),
                height=_float(row.get("height"), 1.0),
                dxfattribs={**attrs, "rotation": _float(row.get("rotation"))},
            )
        if typ == "INSERT":
            child = str(row.get("name") or "").strip()
            actual = block_name_map.get(child, child)
            if actual and actual in doc.blocks:
                return block.add_blockref(
                    actual,
                    _point(row.get("insert")),
                    dxfattribs={
                        **attrs,
                        "rotation": _float(row.get("rotation")),
                        "xscale": _float(row.get("xscale"), 1.0),
                        "yscale": _float(row.get("yscale"), 1.0),
                        "zscale": _float(row.get("zscale"), 1.0),
                    },
                )
        if typ == "POINT":
            return block.add_point(_point(row.get("location")), dxfattribs=attrs)
        return None

    for name, definition in definitions.items():
        block = doc.blocks.get(block_name_map[name])
        for row in definition.get("entities") or []:
            if isinstance(row, dict):
                try:
                    add_entity(block, row)
                except Exception:
                    pass

    return {
        "by_name": block_name_map,
        "by_id": {
            symbol_ids[name]: actual
            for name, actual in block_name_map.items()
            if name in symbol_ids
        },
    }


def _decode_xdata(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        try:
            return dict(value)
        except Exception:
            return {}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return dict(parsed)
        except Exception:
            pass
    return {}


def _xdata_tag(item, handle_map):
    if isinstance(item, (list, tuple)) and len(item) == 2:
        code, value = item
    else:
        text = str(item)
        if ":" not in text:
            return None
        code, value = text.split(":", 1)
    try:
        code = int(code)
    except Exception:
        return None
    value = str(value).strip()
    if code == 1005:
        value = handle_map.get(value.upper(), value)
    elif code in (1040, 1041, 1042):
        try:
            value = float(value)
        except Exception:
            pass
    elif 1070 <= code <= 1071:
        try:
            value = int(float(value))
        except Exception:
            pass
    return (code, value)


def _apply_xdata(doc, entity, xdata, handle_map, connections=None):
    data = _decode_xdata(xdata)
    if not data and connections:
        data = {"EXMAP_NODELINK": [f"1005:{h}" for h in connections]}

    for appid, values in data.items():
        if not appid:
            continue
        try:
            if appid not in doc.appids:
                doc.appids.new(str(appid))
        except Exception:
            pass
        tags = []
        for item in values or []:
            tag = _xdata_tag(item, handle_map)
            if tag is not None:
                tags.append(tag)
        if tags:
            try:
                entity.set_xdata(str(appid), tags)
            except Exception:
                pass


def export_network_preserving_dxf(path, features, symbol_payload, target_epsg=5174):
    import ezdxf
    from pyproj import Transformer

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    symbol_maps = install_symbol_library(doc, symbol_payload)
    block_name_map = symbol_maps.get("by_name") or {}
    block_id_map = symbol_maps.get("by_id") or {}

    transform = Transformer.from_crs(
        "EPSG:4326",
        f"EPSG:{int(target_epsg)}",
        always_xy=True,
    )

    created = []
    original_to_new = {}

    for feature in features:
        p = feature.get("properties") or {}
        attrs = _as_dict(p.get("attributes"))
        layer = _safe_layer(p.get("layer") or "SERVER")
        if layer not in doc.layers:
            try:
                doc.layers.add(layer)
            except Exception:
                layer = "SERVER"

        style = _as_dict(attrs.get("_cmb_style"))
        dxfattrs = _style_dxfattrs(style, layer)
        g = feature.get("geometry") or {}
        typ = g.get("type")
        coords = g.get("coordinates") or []
        entity = None

        original_handle = str(
            attrs.get("_cmb_original_handle")
            or p.get("source_handle")
            or ""
        ).strip().upper()

        if typ == "Point" and len(coords) >= 2:
            x, y = transform.transform(float(coords[0]), float(coords[1]))
            symbol_name = str(
                attrs.get("_cmb_symbol_name")
                or p.get("block_name")
                or ""
            ).strip()
            symbol_id = str(attrs.get("_cmb_symbol_id") or "").strip()
            actual_symbol = block_id_map.get(symbol_id) or block_name_map.get(symbol_name)
            if actual_symbol and actual_symbol in doc.blocks:
                entity = msp.add_blockref(
                    actual_symbol,
                    (x, y),
                    dxfattribs={
                        **dxfattrs,
                        "rotation": _float(attrs.get("_cmb_rotation_deg")),
                        "xscale": _float(attrs.get("_cmb_xscale"), 1.0),
                        "yscale": _float(attrs.get("_cmb_yscale"), 1.0),
                        "zscale": _float(attrs.get("_cmb_zscale"), 1.0),
                    },
                )
                user_attrs = {
                    str(k): str(v)
                    for k, v in attrs.items()
                    if not str(k).startswith("_cmb_") and v not in (None, "")
                    and not isinstance(v, (dict, list, tuple))
                }
                if user_attrs:
                    try:
                        entity.add_auto_attribs(user_attrs)
                    except Exception:
                        pass
            else:
                entity = msp.add_point((x, y), dxfattribs=dxfattrs)

        elif typ == "LineString" and len(coords) >= 2:
            pts = [transform.transform(float(x), float(y)) for x, y in coords]
            entity = msp.add_lwpolyline(pts, dxfattribs=dxfattrs)

        elif typ == "MultiLineString":
            # 하나의 source handle이 여러 part를 가질 경우 첫 part를 대표 연결 객체로 사용한다.
            parts = []
            for part in coords:
                if len(part) < 2:
                    continue
                pts = [transform.transform(float(x), float(y)) for x, y in part]
                parts.append(msp.add_lwpolyline(pts, dxfattribs=dxfattrs))
            entity = parts[0] if parts else None

        if entity is None:
            continue

        created.append((feature, entity))
        if original_handle and getattr(entity.dxf, "handle", None):
            original_to_new[original_handle] = str(entity.dxf.handle)

    for feature, entity in created:
        p = feature.get("properties") or {}
        attrs = _as_dict(p.get("attributes"))
        connections = [
            str(v).strip().upper()
            for v in _as_list(attrs.get("_cmb_connections"))
            if str(v).strip()
        ]
        _apply_xdata(
            doc,
            entity,
            p.get("xdata"),
            original_to_new,
            connections,
        )

    doc.saveas(path)
