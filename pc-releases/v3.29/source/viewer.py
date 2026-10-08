from __future__ import annotations

import math
import re
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk, messagebox

from ezdxf.path import make_path
from ezdxf.colors import aci2rgb
from pyproj import Transformer

from converter import load_dxf_document
from essenpoly_recovery import recover_linker_polylines
from essenpoly_recovery import recover_essenpoly_polylines

@dataclass
class VisualEntity:
    index: int
    entity_type: str
    layer: str
    handle: str
    text: str = ""
    block_name: str = ""
    primitives: list = field(default_factory=list)
    bbox: tuple | None = None
    color: str = "#d4d7dc"
    attributes: dict = field(default_factory=dict)
    xdata: list = field(default_factory=list)
    dxf_data: dict = field(default_factory=dict)
    pole_info: dict = field(default_factory=dict)

@dataclass
class Scene:
    entities: list[VisualEntity]
    bbox: tuple
    unsupported: dict
    diagnostics: list = field(default_factory=list)

def _expand_bbox(box, x, y):
    if box is None:
        return [x, y, x, y]
    box[0] = min(box[0], x)
    box[1] = min(box[1], y)
    box[2] = max(box[2], x)
    box[3] = max(box[3], y)
    return box

def _points_bbox(points):
    box = None
    for x, y in points:
        box = _expand_bbox(box, x, y)
    return tuple(box) if box else None

def _primitive_bbox(primitive):
    kind, data = primitive
    if kind in {"polyline", "line", "polygon"}:
        return _points_bbox(data)
    if kind == "circle":
        cx, cy, r = data
        return (cx-r, cy-r, cx+r, cy+r)
    if kind == "arc":
        cx, cy, r, _a1, _a2 = data
        return (cx-r, cy-r, cx+r, cy+r)
    if kind in {"point", "text", "insert"}:
        x, y = data[:2]
        return (x, y, x, y)
    return None

def _merge_bbox(a, b):
    if b is None:
        return a
    if a is None:
        return list(b)
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]

def _flatten_path(entity):
    try:
        path = make_path(entity)
        pts = [(float(v.x), float(v.y)) for v in path.flattening(distance=0.5, segments=8)]
        return pts if len(pts) >= 2 else []
    except Exception:
        return []

def _entity_primitives(entity, inherited_layer=None, depth=0):
    typ = entity.dxftype()
    layer = str(getattr(entity.dxf, "layer", inherited_layer or "0") or "0")
    if layer == "0" and inherited_layer:
        layer = inherited_layer
    primitives = []

    try:
        if typ == "LINE":
            a, b = entity.dxf.start, entity.dxf.end
            primitives.append(("line", [(float(a.x), float(a.y)), (float(b.x), float(b.y))]))
        elif typ == "LWPOLYLINE":
            pts = [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
            if len(pts) >= 2:
                if bool(getattr(entity, "closed", False)) and pts[0] != pts[-1]:
                    pts.append(pts[0])
                primitives.append(("polyline", pts))
        elif typ == "POLYLINE":
            pts = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
            if len(pts) >= 2:
                if bool(getattr(entity, "is_closed", False)) and pts[0] != pts[-1]:
                    pts.append(pts[0])
                primitives.append(("polyline", pts))
        elif typ == "CIRCLE":
            c = entity.dxf.center
            primitives.append(("circle", (float(c.x), float(c.y), float(entity.dxf.radius))))
        elif typ == "ARC":
            c = entity.dxf.center
            primitives.append(("arc", (
                float(c.x), float(c.y), float(entity.dxf.radius),
                float(entity.dxf.start_angle), float(entity.dxf.end_angle)
            )))
        elif typ == "POINT":
            p = entity.dxf.location
            primitives.append(("point", (float(p.x), float(p.y))))
        elif typ == "TEXT":
            p = entity.dxf.insert
            primitives.append(("text", (float(p.x), float(p.y), str(entity.dxf.text or ""))))
        elif typ == "MTEXT":
            p = entity.dxf.insert
            primitives.append(("text", (float(p.x), float(p.y), str(entity.plain_text() or ""))))
        elif typ == "INSERT":
            p = entity.dxf.insert
            name = str(getattr(entity.dxf, "name", "") or "")
            primitives.append(("insert", (float(p.x), float(p.y), name)))
            if depth < 4:
                try:
                    for virtual in entity.virtual_entities():
                        v_layer, v_prims = _entity_primitives(virtual, layer, depth + 1)
                        primitives.extend(v_prims)
                except Exception:
                    pass
        elif typ in {"SPLINE", "ELLIPSE"}:
            pts = _flatten_path(entity)
            if pts:
                primitives.append(("polyline", pts))
        elif typ in {"SOLID", "TRACE", "3DFACE"}:
            pts = []
            for name in ("vtx0", "vtx1", "vtx2", "vtx3"):
                try:
                    p = getattr(entity.dxf, name)
                    pts.append((float(p.x), float(p.y)))
                except Exception:
                    pass
            if len(pts) >= 3:
                pts.append(pts[0])
                primitives.append(("polyline", pts))
        elif typ == "HATCH":
            try:
                for boundary in entity.paths:
                    if hasattr(boundary, "vertices"):
                        pts = [(float(v[0]), float(v[1])) for v in boundary.vertices]
                        if len(pts) >= 2:
                            pts.append(pts[0])
                            primitives.append(("polyline", pts))
            except Exception:
                pass
        elif typ == "RAY":
            p = entity.dxf.start
            d = entity.dxf.unit_vector
            x1, y1 = float(p.x), float(p.y)
            primitives.append(("line", [(x1, y1), (x1 + float(d.x) * 1000, y1 + float(d.y) * 1000)]))
        elif typ == "XLINE":
            p = entity.dxf.start
            d = entity.dxf.unit_vector
            x, y = float(p.x), float(p.y)
            dx, dy = float(d.x) * 1000, float(d.y) * 1000
            primitives.append(("line", [(x-dx, y-dy), (x+dx, y+dy)]))
    except Exception:
        pass

    return layer, primitives


def _rgb_hex(rgb):
    try:
        return f"#{int(rgb.r):02x}{int(rgb.g):02x}{int(rgb.b):02x}"
    except Exception:
        try:
            r, g, b = rgb
            return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
        except Exception:
            return "#d4d7dc"

def _contrast_color(hex_color):
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        # CAD dark background에서 너무 어두운 색은 화면 표시용으로만 밝게 보정.
        if (r + g + b) < 105:
            return "#c7cbd1"
    except Exception:
        pass
    return hex_color

def _is_optical_cable_layer(layer_name):
    name = str(layer_name or "")
    upper = name.upper()
    return (
        "F_CABLE" in upper
        or "FOC" in upper
        or "FIBER" in upper
        or "OPTIC" in upper
        or "광케이블" in name
        or "광선로" in name
    )

def _is_cable_layer(layer_name):
    name = str(layer_name or "")
    upper = name.upper()
    return _is_optical_cable_layer(name) or "CABLE" in upper or "케이블" in name or "선로" in name

def _display_color_for_layer(doc, layer_name, aci=None, true_color=None):
    # Cable colors carry field meaning (especially coax power state), so cable
    # layers must keep the original CAD color without brightness substitution.
    raw = None
    try:
        if true_color is not None:
            value = int(true_color)
            raw = f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}"
    except Exception:
        raw = None
    if raw is None:
        try:
            if aci is not None:
                value = abs(int(aci))
                if 1 <= value <= 255:
                    raw = _rgb_hex(aci2rgb(value))
        except Exception:
            raw = None
    if raw is None:
        try:
            layer = doc.layers.get(layer_name)
            value = abs(int(layer.dxf.color))
            if 1 <= value <= 255:
                raw = _rgb_hex(aci2rgb(value))
        except Exception:
            raw = None
    if raw is None:
        raw = "#d4d7dc"
    return raw if _is_cable_layer(layer_name) else _contrast_color(raw)

def _resolve_entity_color(doc, entity, layer_name, inherited=None):
    try:
        true_color = getattr(entity.dxf, "true_color", None)
        if true_color is not None:
            value = int(true_color)
            raw = f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}"
            return raw if _is_cable_layer(layer_name) else _contrast_color(raw)
    except Exception:
        pass

    try:
        color = int(getattr(entity.dxf, "color", 256))
    except Exception:
        color = 256

    if color == 0 and inherited:
        return inherited
    if 1 <= color <= 255:
        try:
            raw = _rgb_hex(aci2rgb(color))
            return raw if _is_cable_layer(layer_name) else _contrast_color(raw)
        except Exception:
            pass

    try:
        layer = doc.layers.get(layer_name)
        layer_color = abs(int(layer.dxf.color))
        if 1 <= layer_color <= 255:
            raw = _rgb_hex(aci2rgb(layer_color))
            return raw if _is_cable_layer(layer_name) else _contrast_color(raw)
    except Exception:
        pass
    return inherited or "#d4d7dc"


def _stringify_value(value):
    try:
        if hasattr(value, "x") and hasattr(value, "y"):
            z = getattr(value, "z", None)
            if z is None:
                return f"{float(value.x):.6f}, {float(value.y):.6f}"
            return f"{float(value.x):.6f}, {float(value.y):.6f}, {float(z):.6f}"
    except Exception:
        pass
    return str(value)

def _collect_entity_details(doc, ent):
    attributes = {}
    if ent.dxftype() == "INSERT":
        try:
            for a in getattr(ent, "attribs", []):
                attributes[str(a.dxf.tag)] = str(a.dxf.text)
        except Exception:
            pass

    xdata = []
    try:
        for appid in doc.appids:
            name = str(appid.dxf.name)
            try:
                tags = ent.get_xdata(name)
            except Exception:
                continue
            values = [f"{tag.code}: {_stringify_value(tag.value)}" for tag in tags]
            if values:
                xdata.append((name, values))
    except Exception:
        pass

    dxf_data = {}
    try:
        for key, value in ent.dxfattribs().items():
            dxf_data[str(key)] = _stringify_value(value)
    except Exception:
        pass
    return attributes, xdata, dxf_data


_POLE_KEYWORDS = (
    "전주", "전주번호", "전주명", "주번호", "지지물",
    "pole", "pole_no", "poleno", "poleid", "pole_id"
)

_POLE_CODE_RE = re.compile(r"(?<![0-9A-Za-z])\d{4}[Xx]\d{3}(?![0-9A-Za-z])")
_ADDRESS_KEYWORDS = (
    "주소", "도로명", "지번", "address", "addr", "road", "jibun",
)

def _extract_address_info(entity):
    found = {}

    def add(key, value):
        k = str(key or "").strip()
        v = str(value or "").strip()
        if not v:
            return
        blob = (k + " " + v).lower()
        if any(word.lower() in blob for word in _ADDRESS_KEYWORDS):
            found[k or "주소"] = v

    for key, value in (entity.attributes or {}).items():
        add(key, value)
    for appid, values in (entity.xdata or []):
        for value in values:
            add(appid, value)
    for key, value in (entity.dxf_data or {}).items():
        add(key, value)
    add("TEXT", entity.text)
    return found

def _extract_pole_info(attributes, xdata, dxf_data, text="", block_name=""):
    found = {}

    def check_pair(key, value):
        k = str(key or "").strip()
        v = str(value or "").strip()
        blob = (k + " " + v).lower()
        if any(word.lower() in blob for word in _POLE_KEYWORDS):
            label = k or "전주"
            if v:
                found[label] = v

    for key, value in (attributes or {}).items():
        check_pair(key, value)

    for appid, values in (xdata or []):
        for value in values:
            check_pair(appid, value)

    for key, value in (dxf_data or {}).items():
        check_pair(key, value)

    if text:
        check_pair("TEXT", text)
    if block_name:
        check_pair("BLOCK", block_name)

    # 현장 전주번호가 0000X000 형태로만 저장된 경우 키워드가 없어도 직접 인식한다.
    blobs = []
    blobs.extend(str(v) for v in (attributes or {}).values())
    for appid, values in (xdata or []):
        blobs.append(str(appid))
        blobs.extend(str(v) for v in values)
    blobs.extend(str(v) for v in (dxf_data or {}).values())
    blobs.extend([str(text or ""), str(block_name or "")])
    for blob in blobs:
        for match in _POLE_CODE_RE.findall(blob):
            found.setdefault("전주번호", match.upper())

    return found

from geometry_complete import render_entity

_legacy_entity_primitives = _entity_primitives

def _entity_primitives(entity, inherited_layer=None, depth=0, issues=None, parts=None):
    return render_entity(entity, inherited_layer, depth, _legacy_entity_primitives,
                         parts if parts is not None else [], issues if issues is not None else [])

_original_display_color_for_layer = _display_color_for_layer


def _display_color_for_layer(doc, layer_name, aci=None, true_color=None):
    # Explicit CAD entity colors always win over the conduit display default.
    if true_color is not None or aci not in (None, 0, 256):
        return _original_display_color_for_layer(doc, layer_name, aci, true_color)
    try:
        layer = doc.layers.get(layer_name)
        layer_rgb = getattr(layer.dxf, 'true_color', None)
        if layer_rgb is not None:
            value = int(layer_rgb)
            return f'#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}'
        layer_aci = abs(int(layer.dxf.color))
    except Exception:
        layer_aci = 7
    if str(layer_name).upper() == 'CN_L_POLE_LINE_CONDUIT' and layer_aci in (0, 7, 256):
        return '#00ffff'  # CAD cyan: conduit display color requested by the user.
    return _original_display_color_for_layer(doc, layer_name, aci, true_color)

def build_scene(input_path, log=None, progress=None):
    log = log or (lambda msg: None)
    progress = progress or (lambda percent, task: None)
    progress(3, "Viewer DXF 읽기")
    doc = load_dxf_document(input_path, log)
    source = list(doc.modelspace())
    total = max(1, len(source))
    entities, unsupported = [], {}
    scene_box = None
    geometry_issues = []
    pending_children = []

    for i, ent in enumerate(source):
        block_parts = []
        layer, primitives = _entity_primitives(ent, issues=geometry_issues, parts=block_parts)
        typ = ent.dxftype()
        if not primitives:
            unsupported[typ] = unsupported.get(typ, 0) + 1
        box = None
        for prim in primitives:
            box = _merge_bbox(box, _primitive_bbox(prim))
        if box is not None:
            scene_box = _merge_bbox(scene_box, box)
        text = ""
        block_name = ""
        try:
            if typ == "TEXT":
                text = str(ent.dxf.text or "")
            elif typ == "MTEXT":
                text = str(ent.plain_text() or "")
            elif typ == "INSERT":
                block_name = str(ent.dxf.name or "")
                attrs = [f"{a.dxf.tag}={a.dxf.text}" for a in getattr(ent, "attribs", [])]
                text = " | ".join(attrs)
        except Exception:
            pass
        display_color = _resolve_entity_color(doc, ent, layer)
        attributes, xdata, dxf_data = _collect_entity_details(doc, ent)
        pole_info = _extract_pole_info(attributes, xdata, dxf_data, text, block_name)
        entities.append(VisualEntity(
            index=i,
            entity_type=typ,
            layer=layer,
            handle=str(getattr(ent.dxf, "handle", "") or ""),
            text=text,
            block_name=block_name,
            primitives=primitives,
            bbox=tuple(box) if box else None,
            color=display_color,
            attributes=attributes,
            xdata=xdata,
            dxf_data=dxf_data,
            pole_info=pole_info,
        ))
        for part_index, (child, child_layer, child_prims) in enumerate(block_parts):
            if child_layer == layer:
                continue
            child_box = None
            for prim in child_prims:
                child_box = _merge_bbox(child_box, _primitive_bbox(prim))
            child_attrs, child_xdata, child_dxf = _collect_entity_details(doc, child)
            child_dxf['PARENT_HANDLE'] = str(getattr(ent.dxf, 'handle', '') or '')
            child_dxf['PARENT_BLOCK'] = block_name
            if child.dxftype() == 'ATTRIB':
                child_attrs[str(child.dxf.tag)] = str(child.dxf.text)
            pending_children.append(VisualEntity(
                index=0, entity_type=child.dxftype(), layer=child_layer,
                handle=f'{getattr(ent.dxf, "handle", "")}/child/{part_index}',
                text=str(getattr(child.dxf, 'text', '') or ''), block_name=block_name,
                primitives=child_prims, bbox=tuple(child_box) if child_box else None,
                color=_resolve_entity_color(doc, child, child_layer, display_color),
                attributes=child_attrs, xdata=child_xdata, dxf_data=child_dxf,
            ))
            scene_box = _merge_bbox(scene_box, child_box)
        if i + 1 == total or (i + 1) % max(1, total // 100) == 0:
            progress(10 + int((i + 1) / total * 88), f"Viewer 객체 준비 {i+1:,}/{total:,}")

    for child in pending_children:
        child.index = len(entities)
        entities.append(child)

    # 일부 통신망 CAD는 케이블을 ESSENPOLY 사용자 객체로 저장한다.
    # 손상된 310 바이너리 태그와 별개로 Embedded AcDbPolyline의 10/20 좌표는
    # 정상적으로 남아 있으므로 원본 DXF를 수정하지 않고 Viewer 표시만 복구한다.
    recovered = recover_essenpoly_polylines(input_path)
    by_handle = {e.handle: e for e in entities if e.handle}
    recovered_count = 0
    for item in recovered:
        points = item["points"]
        box = _points_bbox(points)
        if box is None:
            continue
        layer = item["layer"]
        color = _display_color_for_layer(
            doc,
            layer,
            aci=item.get("color_aci"),
            true_color=item.get("true_color"),
        )

        target = by_handle.get(item.get("handle", ""))
        if target is not None and not target.primitives:
            target.layer = layer
            target.primitives = [("polyline", points)]
            target.bbox = tuple(box)
            target.color = color
            target.attributes.update(item.get("attributes", {}))
            if unsupported.get("ESSENPOLY", 0) > 0:
                unsupported["ESSENPOLY"] -= 1
                if unsupported["ESSENPOLY"] <= 0:
                    unsupported.pop("ESSENPOLY", None)
        elif target is None:
            idx = len(entities)
            entity = VisualEntity(
                index=idx,
                entity_type="ESSENPOLY",
                layer=layer,
                handle=item.get("handle", ""),
                primitives=[("polyline", points)],
                bbox=tuple(box),
                color=color,
                attributes=item.get("attributes", {}),
            )
            entities.append(entity)
            if entity.handle:
                by_handle[entity.handle] = entity
        else:
            continue
        scene_box = _merge_bbox(scene_box, box)
        recovered_count += 1

    if recovered_count:
        log(f"ESSENPOLY 케이블/선로 {recovered_count}개 Viewer 복구")

    # Restore original conduit/aerial paths from their embedded geometry.
    linker_items = recover_linker_polylines(input_path)
    linker_targets = {entity.handle: entity for entity in entities if entity.handle}
    linker_count = 0
    for item in linker_items:
        points = item['points']
        box = _points_bbox(points)
        if box is None:
            continue
        target = linker_targets.get(item['handle'])
        layer = item['layer']
        color = _display_color_for_layer(doc, layer, item.get('color_aci'), item.get('true_color'))
        xdata = [(appid, values) for appid, values in item.get('xdata', {}).items()]
        if target is None:
            target = VisualEntity(index=len(entities), entity_type='ASDKESSENLINKER', layer=layer, handle=item['handle'])
            entities.append(target)
            if target.handle:
                linker_targets[target.handle] = target
        else:
            if target.primitives:
                continue
            missing_type = target.entity_type
            if unsupported.get(missing_type, 0):
                unsupported[missing_type] -= 1
                if not unsupported[missing_type]:
                    unsupported.pop(missing_type)
        target.entity_type = 'ASDKESSENLINKER'
        target.layer = layer
        target.primitives = [('polyline', points)]
        target.bbox = box
        target.color = color
        target.attributes.update(item.get('attributes', {}))
        target.xdata = xdata
        scene_box = _merge_bbox(scene_box, box)
        linker_count += 1
    if linker_count:
        log(f'관로/연결선 {linker_count}개 원본 경로 복구')

    if scene_box is None:
        scene_box = [0.0, 0.0, 1.0, 1.0]
    if scene_box[0] == scene_box[2]:
        scene_box[2] += 1.0
    if scene_box[1] == scene_box[3]:
        scene_box[3] += 1.0
    progress(100, "Viewer 준비 완료")
    # Recovered custom objects are no longer missing geometry.
    repaired = {e.handle for e in entities if e.primitives}
    geometry_issues = [issue for issue in geometry_issues if not (issue['type'] in {'ESSENPOLY', 'ASDKESSENLINKER'} and issue['handle'] in repaired)]
    return Scene(entities, tuple(scene_box), unsupported, geometry_issues)

class DXFViewer(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.scene = None
        self.entity_filter = None
        self.network_click = None
        self.route_nodes = {}
        self.route_start_marker = None
        self.visible_layers = set()
        self.scale = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.item_to_entity = {}
        self.entity_items = {}
        self.selected = set()
        self.mode = "select"
        self.measure_points = []
        self.measure_items = []
        self.completed_measurements = []
        self.selected_measurement = None
        self.hover_world = None
        self._right_dragged = False
        self._right_press_xy = None
        self.pan_start = None
        self.source_epsg = 5174
        self.transformer = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
        self.status_var = tk.StringVar(value="DXF를 열어주세요.")
        self.info_var = tk.StringVar(value="")
        self.details_window = None
        self._build()

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))

        button_frame = ttk.Frame(bar)
        button_frame.pack(side="left")
        for text, cmd in [
            ("전체보기", self.fit_view),
            ("선택", lambda: self.set_mode("select")),
            ("거리 측정", lambda: self.set_mode("distance")),
            ("좌표 확인", lambda: self.set_mode("coord")),
            ("상세정보", self.show_details),
            ("선택 해제", self.clear_selection),
            ("측정 지우기", self.clear_measure),
        ]:
            ttk.Button(button_frame, text=text, command=cmd).pack(side="left", padx=(0, 4))

        # 상태/좌표/거리 정보는 Viewer 상단 우측에만 표시한다.
        # 하단 정보창은 제거하여 Canvas 높이를 최대한 확보한다.
        info_frame = ttk.Frame(bar)
        info_frame.pack(side="right", fill="x", expand=True, padx=(12, 0))
        ttk.Label(
            info_frame,
            textvariable=self.status_var,
            anchor="e",
            justify="right",
        ).pack(fill="x")
        ttk.Label(
            info_frame,
            textvariable=self.info_var,
            anchor="e",
            justify="right",
        ).pack(fill="x")

        # 상단 도구바는 전체 폭을 그대로 유지한다.
        # 레이어 도킹 영역과 DXF Canvas는 그 아래 body에서만 좌/우로 나뉜다.
        self.body = tk.PanedWindow(
            self, orient="horizontal", sashwidth=7, sashrelief="raised",
            showhandle=False, bd=0, relief="flat"
        )
        self.body.pack(fill="both", expand=True)

        self.side_host = ttk.Frame(self.body, width=420)
        self.side_host.pack_propagate(False)

        self.canvas_host = ttk.Frame(self.body)
        self.body.add(self.side_host, minsize=220, width=420, stretch="never")
        self.body.add(self.canvas_host, minsize=500, stretch="always")

        self.canvas = tk.Canvas(
            self.canvas_host,
            background="#171a1f",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_event(e, 1.15))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_event(e, 1/1.15))
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        # 우클릭 짧게=컨텍스트 메뉴, 우클릭 드래그=기존 PAN.
        self.canvas.bind("<ButtonPress-3>", self._right_press)
        self.canvas.bind("<B3-Motion>", self._right_move)
        self.canvas.bind("<ButtonRelease-3>", self._right_release)
        self.canvas.bind("<Button-1>", self._left_click)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<Motion>", self._motion)
        self.bind_all("<Escape>", self.handle_escape)
        # 거리 측정 완료는 ESC를 사용한다. Enter는 더 이상 측정 종료 키로 사용하지 않는다.

    def load_scene(self, scene):
        self.scene = scene
        self.visible_layers = {e.layer for e in scene.entities}
        self.selected.clear()
        self.measure_points = []
        self.completed_measurements = []
        self.selected_measurement = None
        self.fit_view()
        unsupported = sum(scene.unsupported.values())
        self.status_var.set(
            f"객체 {len(scene.entities):,}개 · 미표시 {unsupported:,}개 · 휠=확대/축소 · 우/중클릭 드래그=PAN"
        )

    def set_visible_layers(self, layers):
        self.visible_layers = set(layers)
        self.selected = {i for i in self.selected if self.scene and self.scene.entities[i].layer in self.visible_layers}
        self.redraw()

    def set_mode(self, mode):
        if self.network_click is not None and mode != "fiber_route":
            self.network_click = None
            self.route_nodes = {}
            self.route_start_marker = None
        self.mode = mode
        self.measure_points = []
        labels = {"select":"선택", "distance":"거리 측정", "coord":"좌표 확인"}
        self.status_var.set(f"모드: {labels.get(mode, mode)}")
        if mode == "distance":
            self.info_var.set(
                "지점을 계속 클릭하세요. 구간/누적 거리가 표시됩니다. ESC로 현재 마지막 지점까지 측정을 완료합니다."
            )

    def set_source_epsg(self, epsg):
        try:
            epsg = int(epsg)
            self.source_epsg = epsg
            self.transformer = Transformer.from_crs(
                f"EPSG:{epsg}", "EPSG:4326", always_xy=True
            )
        except Exception as e:
            messagebox.showerror("좌표계 오류", f"EPSG:{epsg} 좌표계를 사용할 수 없습니다.\n{e}")

    @staticmethod
    def _detail_value_present(value):
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    @staticmethod
    def _detail_label(key):
        labels = {
            "insert": "삽입점",
            "location": "위치",
            "center": "중심점",
            "start": "시작점",
            "end": "끝점",
            "rotation": "회전각",
            "angle": "각도",
            "radius": "반지름",
            "xscale": "X 스케일",
            "yscale": "Y 스케일",
            "zscale": "Z 스케일",
            "elevation": "표고",
            "extrusion": "돌출방향",
            "height": "문자높이",
            "text": "문자",
            "name": "이름",
            "closed": "폐합여부",
        }
        raw = str(key).strip()
        return labels.get(raw.lower(), raw)

    def show_details(self):
        if not self.scene or not self.selected:
            messagebox.showinfo("상세정보", "먼저 Viewer에서 기기/객체를 선택해주세요.")
            return

        rows = []
        for order, idx in enumerate(sorted(self.selected), 1):
            ent = self.scene.entities[idx]
            if len(self.selected) > 1:
                rows.append((f"[객체 {order}]", ""))

            # 사용자에게 의미 있는 기본 정보만 먼저 표시.
            base = [
                ("TYPE", ent.entity_type),
                ("LAYER", ent.layer),
                ("BLOCK", ent.block_name),
                ("TEXT", ent.text),
                ("HANDLE", ent.handle),
            ]
            for key, value in base:
                if self._detail_value_present(value):
                    rows.append((key, str(value).strip()))

            # 전주 정보는 가장 중요한 업무 정보이므로 위쪽에 별도 표시.
            for key, value in (ent.pole_info or {}).items():
                if self._detail_value_present(value):
                    rows.append((f"전주/{key}", str(value).strip()))

            # 블록 속성: 주소/기기명/설치정보 등 실제 업무 데이터.
            for key, value in (ent.attributes or {}).items():
                if self._detail_value_present(value):
                    rows.append((str(key).strip(), str(value).strip()))

            # XDATA도 값이 있는 항목만 표시.
            for appid, values in (ent.xdata or []):
                for value in values:
                    if self._detail_value_present(value):
                        rows.append((f"XDATA/{appid}", str(value).strip()))

            # DXF 기본 속성은 중복/공란/기본값을 최대한 제외.
            skip_keys = {
                "layer", "handle", "owner", "paperspace", "color",
                "linetype", "ltscale", "invisible", "lineweight",
            }
            existing = {(k.lower(), val) for k, val in rows}
            for key in sorted(ent.dxf_data or {}):
                if key.lower() in skip_keys:
                    continue
                value = ent.dxf_data[key]
                if not self._detail_value_present(value):
                    continue
                text_value = str(value).strip()
                # 빈 컬렉션/None만 제거한다. 0은 좌표·회전·표고 등에서
                # 실제 의미가 있을 수 있으므로 필드명과 함께 그대로 표시한다.
                if text_value in {"None", "()", "[]", "{}"}:
                    continue
                if (key.lower(), text_value) in existing:
                    continue
                rows.append((self._detail_label(key), text_value))

        if not rows:
            messagebox.showinfo("상세정보", "표시할 상세정보가 없습니다.")
            return

        # 내용 길이에 맞춰 창 크기를 자동 계산한다.
        max_key = max(len(k) for k, _ in rows)
        max_val = max(len(val) for _, val in rows)
        width = max(420, min(820, 180 + max_key * 8 + max_val * 7))
        height = max(220, min(650, 70 + len(rows) * 25))

        if self.details_window is not None:
            try:
                if self.details_window.winfo_exists():
                    self.details_window.destroy()
            except Exception:
                pass
            self.details_window = None

        win = tk.Toplevel(self)
        self.details_window = win
        win.title("선택 객체 상세정보")
        win.geometry(f"{width}x{height}")
        win.transient(self.winfo_toplevel())

        def _close_details():
            try:
                win.destroy()
            finally:
                if self.details_window is win:
                    self.details_window = None
        win.protocol("WM_DELETE_WINDOW", _close_details)

        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)

        tree = ttk.Treeview(
            frame,
            columns=("key", "value"),
            show="headings",
            height=min(22, max(5, len(rows))),
        )
        tree.heading("key", text="항목")
        tree.heading("value", text="내용")
        tree.column("key", width=max(110, min(220, max_key * 9 + 30)), stretch=False)
        tree.column("value", width=max(250, min(560, max_val * 8 + 40)), stretch=True)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for key, value in rows:
            tree.insert("", "end", values=(key, value))

    def world_to_screen(self, x, y):
        return x * self.scale + self.ox, -y * self.scale + self.oy

    def screen_to_world(self, sx, sy):
        return (sx - self.ox) / self.scale, -(sy - self.oy) / self.scale

    @staticmethod
    def _percentile(values, p):
        if not values:
            return 0.0
        values = sorted(values)
        if len(values) == 1:
            return values[0]
        pos = (len(values) - 1) * p
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return values[lo]
        frac = pos - lo
        return values[lo] * (1 - frac) + values[hi] * frac

    def _visible_fit_bbox(self):
        if not self.scene:
            return None
        boxes = [
            e.bbox for e in self.scene.entities
            if e.layer in self.visible_layers and e.bbox is not None and (self.entity_filter is None or e.index in self.entity_filter)
        ]
        if not boxes:
            return self.scene.bbox

        # 객체가 충분히 많으면 멀리 떨어진 단독 잡객체가 전체 도면을
        # 한쪽으로 밀지 않도록 객체 중심점의 2~98% 분포를 기준으로 잡는다.
        if len(boxes) >= 30:
            centers_x = [(b[0] + b[2]) / 2 for b in boxes]
            centers_y = [(b[1] + b[3]) / 2 for b in boxes]
            qx1 = self._percentile(centers_x, 0.02)
            qx2 = self._percentile(centers_x, 0.98)
            qy1 = self._percentile(centers_y, 0.02)
            qy2 = self._percentile(centers_y, 0.98)
            filtered = []
            for b in boxes:
                cx = (b[0] + b[2]) / 2
                cy = (b[1] + b[3]) / 2
                if qx1 <= cx <= qx2 and qy1 <= cy <= qy2:
                    filtered.append(b)
            if len(filtered) >= max(10, int(len(boxes) * 0.7)):
                boxes = filtered

        minx = min(b[0] for b in boxes)
        miny = min(b[1] for b in boxes)
        maxx = max(b[2] for b in boxes)
        maxy = max(b[3] for b in boxes)
        return (minx, miny, maxx, maxy)

    def fit_view(self):
        if not self.scene:
            return
        self.update_idletasks()
        w, h = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        bbox = self._visible_fit_bbox() or self.scene.bbox
        minx, miny, maxx, maxy = bbox
        dx, dy = max(maxx-minx, 1e-9), max(maxy-miny, 1e-9)

        # 화면 가장자리와 도면 사이에 약간의 여백을 둔다.
        margin = 36
        self.scale = max(1e-9, min((w-margin*2)/dx, (h-margin*2)/dy))
        cx, cy = (minx+maxx)/2, (miny+maxy)/2
        self.ox = w/2 - cx*self.scale
        self.oy = h/2 + cy*self.scale
        self.pan_start = None
        self.redraw()

    def redraw(self):
        c = self.canvas
        c.delete("all")
        self.item_to_entity.clear()
        self.entity_items.clear()
        if not self.scene:
            c.create_text(30, 30, anchor="nw", fill="#b7c0cc", text="DXF 파일을 열어주세요.", font=("Malgun Gothic", 14))
            return
        for ent in self.scene.entities:
            if self.entity_filter is not None and ent.index not in self.entity_filter:
                continue
            if ent.layer not in self.visible_layers:
                continue
            selected = ent.index in self.selected
            color = "#22a7ff" if selected else ent.color
            width = 3 if selected else 1
            ids = []
            for kind, data in ent.primitives:
                try:
                    if kind in {"line", "polyline"}:
                        coords = []
                        for x, y in data:
                            sx, sy = self.world_to_screen(x, y)
                            coords.extend([sx, sy])
                        if len(coords) >= 4:
                            # 광케이블은 CAD 내부 Polyline 정점 순서의 마지막 점을
                            # 현재 도면의 IN 방향으로 간주해 화살표를 표시한다.
                            # 동축 및 기타 케이블에는 방향 화살표를 표시하지 않는다.
                            if _is_optical_cable_layer(ent.layer):
                                ids.append(c.create_line(
                                    *coords, fill=color, width=max(width, 2),
                                    arrow=tk.LAST, arrowshape=(10, 12, 5),
                                ))
                            else:
                                ids.append(c.create_line(*coords, fill=color, width=width))
                    elif kind == "polygon":
                        coords = []
                        for x, y in data:
                            coords.extend(self.world_to_screen(x, y))
                        if len(coords) >= 6:
                            ids.append(c.create_polygon(*coords, fill=color, outline=color))
                    elif kind == "circle":
                        x, y, r = data
                        x1, y1 = self.world_to_screen(x-r, y-r)
                        x2, y2 = self.world_to_screen(x+r, y+r)
                        ids.append(c.create_oval(x1, y2, x2, y1, outline=color, width=width))
                    elif kind == "arc":
                        x, y, r, a1, a2 = data
                        x1, y1 = self.world_to_screen(x-r, y-r)
                        x2, y2 = self.world_to_screen(x+r, y+r)
                        extent = (a2-a1) % 360
                        ids.append(c.create_arc(x1, y2, x2, y1, start=a1, extent=extent, style="arc", outline=color, width=width))
                    elif kind == "point":
                        x, y = data
                        sx, sy = self.world_to_screen(x, y)
                        ids.append(c.create_line(sx-4, sy, sx+4, sy, fill=color, width=width))
                        ids.append(c.create_line(sx, sy-4, sx, sy+4, fill=color, width=width))
                    elif kind == "text":
                        x, y, text = data
                        sx, sy = self.world_to_screen(x, y)
                        ids.append(c.create_text(sx, sy, anchor="sw", fill=color, text=text, font=("Malgun Gothic", 9)))
                    elif kind == "insert":
                        x, y, name = data
                        sx, sy = self.world_to_screen(x, y)
                        ids.append(c.create_rectangle(sx-3, sy-3, sx+3, sy+3, outline=color, width=width))
                except Exception:
                    pass
            for item in ids:
                self.item_to_entity[item] = ent.index
            self.entity_items[ent.index] = ids
        self._redraw_measure()
        if self.network_click is not None:
            for point in self.route_nodes.values():
                sx, sy = self.world_to_screen(*point)
                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill="#00ffff", outline="#003a46")
            if self.route_start_marker:
                sx, sy = self.world_to_screen(*self.route_start_marker)
                self.canvas.create_oval(sx-7, sy-7, sx+7, sy+7, outline="#54ff54", width=3)

    def _wheel(self, event):
        delta = float(getattr(event, "delta", 0) or 0)
        if not math.isfinite(delta) or delta == 0:
            return "break"
        notches = max(-4.0, min(4.0, delta / 120.0))
        self._zoom_at(event.x, event.y, 1.15 ** notches)
        return "break"

    def _zoom_event(self, event, factor):
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, sx, sy, factor):
        wx, wy = self.screen_to_world(sx, sy)
        self.scale = max(1e-12, min(self.scale * factor, 1e9))
        self.ox = sx - wx*self.scale
        self.oy = sy + wy*self.scale
        # A drag must resume from the new zoom origin, not its pre-zoom origin.
        if self.pan_start is not None:
            self.pan_start = (sx, sy, self.ox, self.oy)
        self.redraw()

    def _pan_start(self, event):
        self.pan_start = (event.x, event.y, self.ox, self.oy)

    def _pan_move(self, event):
        if not self.pan_start:
            return
        x, y, ox, oy = self.pan_start
        self.ox = ox + event.x - x
        self.oy = oy + event.y - y
        self.redraw()

    def _pan_end(self, event):
        self.pan_start = None

    def _nearest_entity(self, x, y):
        candidates = self.canvas.find_overlapping(x-5, y-5, x+5, y+5)
        for item in reversed(candidates):
            if item in self.item_to_entity:
                return self.item_to_entity[item]
        closest = self.canvas.find_closest(x, y)
        if closest and closest[0] in self.item_to_entity:
            return self.item_to_entity[closest[0]]
        return None

    @staticmethod
    def _segment_distance_px(px, py, ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        qx, qy = ax + t * dx, ay + t * dy
        return math.hypot(px - qx, py - qy)

    def _nearest_measurement(self, sx, sy, threshold=8.0):
        best = None
        best_dist = float("inf")
        for idx, measurement in enumerate(self.completed_measurements):
            pts = measurement.get("points", [])
            for a, b in zip(pts, pts[1:]):
                ax, ay = self.world_to_screen(*a)
                bx, by = self.world_to_screen(*b)
                dist = self._segment_distance_px(sx, sy, ax, ay, bx, by)
                if dist < best_dist:
                    best_dist = dist
                    best = idx
        return best if best is not None and best_dist <= threshold else None

    def _right_press(self, event):
        self._right_press_xy = (event.x, event.y)
        self._right_dragged = False
        self._pan_start(event)

    def _right_move(self, event):
        if self._right_press_xy:
            if math.hypot(event.x - self._right_press_xy[0], event.y - self._right_press_xy[1]) >= 4:
                self._right_dragged = True
        if self._right_dragged:
            self._pan_move(event)

    def _right_release(self, event):
        dragged = self._right_dragged
        self._pan_end(event)
        self._right_press_xy = None
        self._right_dragged = False
        if dragged:
            return
        self._show_context_menu(event)

    def _show_context_menu(self, event):
        # 측정선은 사용자 생성 객체이므로 삭제 가능. DXF 원본 객체는 삭제 메뉴를 절대 제공하지 않는다.
        measurement_idx = self._nearest_measurement(event.x, event.y)
        if measurement_idx is not None:
            self.selected_measurement = measurement_idx
            self.selected.clear()
            self.redraw()
            menu = tk.Menu(self.canvas, tearoff=False)
            menu.add_command(label="삭제", command=lambda i=measurement_idx: self._delete_measurement(i))
            menu.tk_popup(event.x_root, event.y_root)
            return

        idx = self._nearest_entity(event.x, event.y)
        if idx is None:
            return
        self.selected_measurement = None
        if idx not in self.selected:
            self.selected = {idx}
        self._show_selected_info()
        self.redraw()
        # DXF 원본 객체는 우클릭 시 속성정보 메뉴만 제공한다.
        # 삭제/전주정보/주소 메뉴는 제공하지 않는다.
        menu = tk.Menu(self.canvas, tearoff=False)
        menu.add_command(label="속성정보", command=self.show_details)
        menu.tk_popup(event.x_root, event.y_root)

    def _delete_measurement(self, index):
        if 0 <= index < len(self.completed_measurements):
            self.completed_measurements.pop(index)
        self.selected_measurement = None
        self.info_var.set("")
        self.redraw()

    def _show_rows_window(self, title, rows):
        if not rows:
            messagebox.showinfo(title, f"{title} 정보가 없습니다.")
            return
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("520x300")
        win.transient(self.winfo_toplevel())
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=("key", "value"), show="headings")
        tree.heading("key", text="항목")
        tree.heading("value", text="내용")
        tree.column("key", width=130, stretch=False)
        tree.column("value", width=340, stretch=True)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for key, value in rows:
            tree.insert("", "end", values=(key, value))

    def show_pole_info(self):
        if not self.scene or not self.selected:
            messagebox.showinfo("전주정보", "먼저 객체를 선택해주세요.")
            return
        rows = []
        for idx in sorted(self.selected):
            ent = self.scene.entities[idx]
            for key, value in (ent.pole_info or {}).items():
                if str(value).strip():
                    rows.append((key, str(value).strip()))
        # 같은 전주번호/항목 중복 제거
        rows = list(dict.fromkeys(rows))
        self._show_rows_window("전주정보", rows)

    def show_address_info(self):
        if not self.scene or not self.selected:
            messagebox.showinfo("주소", "먼저 객체를 선택해주세요.")
            return
        rows = []
        for idx in sorted(self.selected):
            ent = self.scene.entities[idx]
            for key, value in _extract_address_info(ent).items():
                rows.append((key, value))
        rows = list(dict.fromkeys(rows))
        self._show_rows_window("주소", rows)

    def handle_escape(self, event=None):
        if self.network_click is not None:
            self.winfo_toplevel()._reset_network_filter()
            return "break"
        if self.mode == "distance":
            if len(self.measure_points) >= 2:
                self._finish_measurement()
            else:
                self.measure_points = []
                self.redraw()
            self.mode = "select"
            self.status_var.set("모드: 선택")
            return "break"
        self.clear_selection()
        return "break"

    def _left_click(self, event):
        if self.network_click is not None:
            self.network_click(event)
            return
        wx, wy = self.screen_to_world(event.x, event.y)
        if self.mode == "coord":
            try:
                lon, lat = self.transformer.transform(wx, wy)
                self.info_var.set(
                    f"위도={lat:.7f}, 경도={lon:.7f}"
                )
            except Exception as e:
                self.info_var.set(f"좌표 X={wx:.3f}, Y={wy:.3f} / 위경도 변환 오류: {e}")
            return
        if self.mode == "distance":
            self.measure_points.append((wx, wy))
            if len(self.measure_points) == 1:
                self.info_var.set(
                    f"시작점 X={wx:.3f}, Y={wy:.3f} · 다음 지점을 계속 클릭하세요."
                )
            else:
                a, b = self.measure_points[-2], self.measure_points[-1]
                segment = math.hypot(b[0]-a[0], b[1]-a[1])
                total = sum(
                    math.hypot(
                        self.measure_points[i][0] - self.measure_points[i-1][0],
                        self.measure_points[i][1] - self.measure_points[i-1][1],
                    )
                    for i in range(1, len(self.measure_points))
                )
                self.info_var.set(
                    f"구간: {segment:,.3f}  /  누적 총 길이: {total:,.3f}  /  지점 {len(self.measure_points)}개"
                )
            self.redraw()
            return
        measurement_idx = self._nearest_measurement(event.x, event.y)
        if measurement_idx is not None:
            self.selected_measurement = measurement_idx
            self.selected.clear()
            m = self.completed_measurements[measurement_idx]
            self.info_var.set(f'측정거리: {m.get("value", 0.0):,.3f} · 우클릭하면 삭제할 수 있습니다.')
            self.redraw()
            return
        self.selected_measurement = None
        idx = self._nearest_entity(event.x, event.y)
        shift = bool(event.state & 0x0001)
        if idx is None:
            if not shift:
                self.clear_selection()
            return
        if shift:
            if idx in self.selected:
                self.selected.remove(idx)
            else:
                self.selected.add(idx)
        else:
            self.selected = {idx}
        self._show_selected_info()
        self.redraw()

    def _finish_measurement(self):
        if self.mode == "distance":
            if len(self.measure_points) < 2:
                return
            pts = list(self.measure_points)
            segments = [
                math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1])
                for i in range(1, len(pts))
            ]
            total = sum(segments)
            self.completed_measurements.append({
                "type": "distance_path",
                "points": pts,
                "segments": segments,
                "value": total,
                "label": f"{total:,.3f}",
            })
            self.info_var.set(
                f"누적 총 길이: {total:,.3f}  /  구간 {len(segments)}개  /  지점 {len(pts)}개"
            )
            self.measure_points = []
            self.redraw()
            return

    def _double_click(self, event):
        self._finish_measurement()

    def _motion(self, event):
        if not self.scene:
            return
        wx, wy = self.screen_to_world(event.x, event.y)
        self.hover_world = (wx, wy)
        base = self.status_var.get().split(" · X=")[0]
        self.status_var.set(f"{base} · X={wx:.3f} Y={wy:.3f}")
        if self.mode in {"distance", "area"} and self.measure_points:
            self.redraw()

    def _show_selected_info(self):
        if not self.scene or not self.selected:
            self.info_var.set("")
            return
        rows = []
        for idx in sorted(self.selected)[:8]:
            e = self.scene.entities[idx]
            extra = []
            if e.block_name:
                extra.append(f"블록={e.block_name}")
            if e.text:
                extra.append(f"문자={e.text[:80]}")
            if e.attributes:
                extra.append(f"속성={len(e.attributes)}개")
            if e.pole_info:
                extra.append("전주정보")
            if e.xdata:
                extra.append(f"XDATA={len(e.xdata)}개")
            rows.append(f"{e.entity_type} · Layer={e.layer} · Handle={e.handle}" + ((" · " + " · ".join(extra)) if extra else ""))
        if len(self.selected) > 8:
            rows.append(f"... 외 {len(self.selected)-8}개")
        self.info_var.set("\n".join(rows))

    def clear_selection(self):
        self.selected.clear()
        self.info_var.set("")
        self.redraw()

    def clear_measure(self):
        self.measure_points = []
        self.measure_items = []
        self.completed_measurements = []
        self.selected_measurement = None
        self.info_var.set("")
        self.redraw()

    def _draw_measure_polyline(self, points, color="#ffcc33", close=False, width=2):
        coords = []
        for x, y in points:
            sx, sy = self.world_to_screen(x, y)
            coords.extend([sx, sy])
            self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill=color, outline="")
        if close and len(points) >= 3:
            sx, sy = self.world_to_screen(*points[0])
            coords.extend([sx, sy])
        if len(coords) >= 4:
            self.canvas.create_line(*coords, fill=color, width=width, dash=(4, 2))

    def _redraw_measure(self):
        # 완료된 거리/면적은 확대/축소/PAN 후에도 계속 표시한다.
        for measurement_index, m in enumerate(self.completed_measurements):
            pts = m.get("points", [])
            if not pts:
                continue
            is_selected_measurement = measurement_index == self.selected_measurement
            self._draw_measure_polyline(
                pts,
                color="#ff8c00" if is_selected_measurement else "#ffd43b",
                close=m.get("type") == "area",
                width=4 if is_selected_measurement else 2,
            )
            if m.get("type") in {"distance", "distance_path"} and len(pts) >= 2:
                segments = m.get("segments") or [
                    math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1])
                    for i in range(1, len(pts))
                ]
                for i in range(1, len(pts)):
                    mx = (pts[i-1][0] + pts[i][0]) / 2
                    my = (pts[i-1][1] + pts[i][1]) / 2
                    sx, sy = self.world_to_screen(mx, my)
                    self.canvas.create_text(
                        sx, sy-10, text=f"{segments[i-1]:,.3f}",
                        fill="#fff3bf", font=("Malgun Gothic", 9)
                    )
                lx, ly = self.world_to_screen(*pts[-1])
                self.canvas.create_text(
                    lx+8, ly-14, anchor="w",
                    text=f'총 {m.get("label", "")}',
                    fill="#fff3bf", font=("Malgun Gothic", 10, "bold")
                )


        # 현재 측정 중인 선과 마우스까지의 임시 선.
        if self.measure_points:
            self._draw_measure_polyline(
                self.measure_points,
                color="#ffcc33",
                close=False,
                width=2,
            )
            if self.hover_world:
                x1, y1 = self.world_to_screen(*self.measure_points[-1])
                x2, y2 = self.world_to_screen(*self.hover_world)
                self.canvas.create_line(
                    x1, y1, x2, y2, fill="#ffcc33", width=1, dash=(2, 3)
                )
            if self.mode == "distance" and len(self.measure_points) >= 2:
                segments = [
                    math.hypot(
                        self.measure_points[i][0]-self.measure_points[i-1][0],
                        self.measure_points[i][1]-self.measure_points[i-1][1]
                    )
                    for i in range(1, len(self.measure_points))
                ]
                for i in range(1, len(self.measure_points)):
                    mx = (self.measure_points[i-1][0] + self.measure_points[i][0]) / 2
                    my = (self.measure_points[i-1][1] + self.measure_points[i][1]) / 2
                    sx, sy = self.world_to_screen(mx, my)
                    self.canvas.create_text(
                        sx, sy-10, text=f"{segments[i-1]:,.3f}",
                        fill="#fff3bf", font=("Malgun Gothic", 9)
                    )
                lx, ly = self.world_to_screen(*self.measure_points[-1])
                self.canvas.create_text(
                    lx+8, ly-14, anchor="w",
                    text=f"누적 {sum(segments):,.3f}",
                    fill="#fff3bf", font=("Malgun Gothic", 10, "bold")
                )

