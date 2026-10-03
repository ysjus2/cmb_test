from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import ttk, messagebox

from ezdxf.path import make_path
from ezdxf.colors import aci2rgb
from pyproj import Transformer

from converter import load_dxf_document

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

@dataclass
class Scene:
    entities: list[VisualEntity]
    bbox: tuple
    unsupported: dict

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
    if kind in {"polyline", "line"}:
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

def _resolve_entity_color(doc, entity, layer_name, inherited=None):
    try:
        true_color = getattr(entity.dxf, "true_color", None)
        if true_color is not None:
            value = int(true_color)
            return _contrast_color(f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}")
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
            return _contrast_color(_rgb_hex(aci2rgb(color)))
        except Exception:
            pass

    try:
        layer = doc.layers.get(layer_name)
        layer_color = abs(int(layer.dxf.color))
        if 1 <= layer_color <= 255:
            return _contrast_color(_rgb_hex(aci2rgb(layer_color)))
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

def build_scene(input_path, log=None, progress=None):
    log = log or (lambda msg: None)
    progress = progress or (lambda percent, task: None)
    progress(3, "Viewer DXF 읽기")
    doc = load_dxf_document(input_path, log)
    source = list(doc.modelspace())
    total = max(1, len(source))
    entities, unsupported = [], {}
    scene_box = None

    for i, ent in enumerate(source):
        layer, primitives = _entity_primitives(ent)
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
        ))
        if i + 1 == total or (i + 1) % max(1, total // 100) == 0:
            progress(10 + int((i + 1) / total * 88), f"Viewer 객체 준비 {i+1:,}/{total:,}")

    if scene_box is None:
        scene_box = [0.0, 0.0, 1.0, 1.0]
    if scene_box[0] == scene_box[2]:
        scene_box[2] += 1.0
    if scene_box[1] == scene_box[3]:
        scene_box[3] += 1.0
    progress(100, "Viewer 준비 완료")
    return Scene(entities, tuple(scene_box), unsupported)

class DXFViewer(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.scene = None
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
        self.hover_world = None
        self.pan_start = None
        self.source_epsg = 5174
        self.transformer = Transformer.from_crs("EPSG:5174", "EPSG:4326", always_xy=True)
        self.status_var = tk.StringVar(value="DXF를 열어주세요.")
        self.info_var = tk.StringVar(value="")
        self._build()

    def _build(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        for text, cmd in [
            ("전체보기", self.fit_view),
            ("선택", lambda: self.set_mode("select")),
            ("거리 측정", lambda: self.set_mode("distance")),
            ("좌표 확인", lambda: self.set_mode("coord")),
            ("상세정보", self.show_details),
            ("선택 해제", self.clear_selection),
            ("측정 지우기", self.clear_measure),
        ]:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 4))
        ttk.Label(bar, textvariable=self.status_var).pack(side="right")

        body = ttk.Panedwindow(self, orient="vertical")
        body.pack(fill="both", expand=True)

        canvas_frame = ttk.Frame(body)
        self.canvas = tk.Canvas(
            canvas_frame, background="#171a1f", highlightthickness=0, cursor="crosshair"
        )
        self.canvas.pack(fill="both", expand=True)
        body.add(canvas_frame, weight=5)

        info = ttk.LabelFrame(body, text="선택 객체 / 측정 정보", padding=6)
        ttk.Label(info, textvariable=self.info_var, justify="left").pack(anchor="w")
        body.add(info, weight=1)

        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_event(e, 1.15))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_event(e, 1/1.15))
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-2>", self._pan_end)
        self.canvas.bind("<ButtonPress-3>", self._pan_start)
        self.canvas.bind("<B3-Motion>", self._pan_move)
        self.canvas.bind("<ButtonRelease-3>", self._pan_end)
        self.canvas.bind("<Button-1>", self._left_click)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<Motion>", self._motion)
        self.bind_all("<Escape>", lambda e: self.clear_selection())
        self.bind_all("<Return>", lambda e: self._finish_measurement())

    def load_scene(self, scene):
        self.scene = scene
        self.visible_layers = {e.layer for e in scene.entities}
        self.selected.clear()
        self.measure_points = []
        self.completed_measurements = []
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
        self.mode = mode
        self.measure_points = []
        labels = {"select":"선택", "distance":"거리 측정", "coord":"좌표 확인"}
        self.status_var.set(f"모드: {labels.get(mode, mode)}")
        if mode == "distance":
            self.info_var.set(
                "지점을 계속 클릭하세요. 구간/누적 거리가 표시됩니다. 더블클릭 또는 Enter로 완료합니다."
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

    def show_details(self):
        if not self.scene or not self.selected:
            messagebox.showinfo("상세정보", "먼저 Viewer에서 기기/객체를 선택해주세요.")
            return

        win = tk.Toplevel(self)
        win.title("선택 객체 상세정보")
        win.geometry("760x620")
        win.transient(self.winfo_toplevel())

        text = tk.Text(win, wrap="word", font=("Consolas", 10))
        y = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=y.set)
        text.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        for order, idx in enumerate(sorted(self.selected), 1):
            ent = self.scene.entities[idx]
            text.insert("end", f"[객체 {order}]\n")
            text.insert("end", f"TYPE: {ent.entity_type}\n")
            text.insert("end", f"LAYER: {ent.layer}\n")
            text.insert("end", f"HANDLE: {ent.handle}\n")
            if ent.block_name:
                text.insert("end", f"BLOCK: {ent.block_name}\n")
            if ent.text:
                text.insert("end", f"TEXT: {ent.text}\n")

            if ent.attributes:
                text.insert("end", "\n[BLOCK ATTRIBUTES]\n")
                for key, value in ent.attributes.items():
                    text.insert("end", f"{key}: {value}\n")

            if ent.xdata:
                text.insert("end", "\n[XDATA]\n")
                for appid, values in ent.xdata:
                    text.insert("end", f"<{appid}>\n")
                    for value in values:
                        text.insert("end", f"  {value}\n")

            if ent.dxf_data:
                text.insert("end", "\n[DXF PROPERTIES]\n")
                for key in sorted(ent.dxf_data):
                    text.insert("end", f"{key}: {ent.dxf_data[key]}\n")

            text.insert("end", "\n" + "="*72 + "\n\n")

        text.config(state="disabled")

    def world_to_screen(self, x, y):
        return x * self.scale + self.ox, -y * self.scale + self.oy

    def screen_to_world(self, sx, sy):
        return (sx - self.ox) / self.scale, -(sy - self.oy) / self.scale

    def fit_view(self):
        if not self.scene:
            return
        self.update_idletasks()
        w, h = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        minx, miny, maxx, maxy = self.scene.bbox
        dx, dy = max(maxx-minx, 1e-9), max(maxy-miny, 1e-9)
        self.scale = max(1e-9, min((w-50)/dx, (h-50)/dy))
        cx, cy = (minx+maxx)/2, (miny+maxy)/2
        self.ox = w/2 - cx*self.scale
        self.oy = h/2 + cy*self.scale
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
                            ids.append(c.create_line(*coords, fill=color, width=width))
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
                        ids.append(c.create_text(sx, sy, anchor="sw", fill=color, text=text[:120], font=("Malgun Gothic", 9)))
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

    def _wheel(self, event):
        factor = 1.15 if event.delta > 0 else 1/1.15
        self._zoom_at(event.x, event.y, factor)

    def _zoom_event(self, event, factor):
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, sx, sy, factor):
        wx, wy = self.screen_to_world(sx, sy)
        self.scale = max(1e-12, min(self.scale * factor, 1e9))
        self.ox = sx - wx*self.scale
        self.oy = sy + wy*self.scale
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

    def _left_click(self, event):
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
        for m in self.completed_measurements:
            pts = m.get("points", [])
            if not pts:
                continue
            self._draw_measure_polyline(
                pts,
                color="#ffd43b",
                close=m.get("type") == "area",
                width=2,
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

