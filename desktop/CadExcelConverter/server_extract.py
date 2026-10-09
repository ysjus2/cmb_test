from __future__ import annotations

import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from openpyxl import Workbook
from pyproj import Transformer

from server_client_windows import CMBServerClient

GROUPS = ("FIBER", "COAX", "POLE", "CONDUIT", "USER")


def _feature_id(feature):
    p = feature.get("properties") or {}
    return (
        feature.get("id")
        or p.get("regional_object_id")
        or p.get("entity_id")
        or json.dumps(feature.get("geometry") or {}, sort_keys=True, ensure_ascii=False)
    )


def _point_in_polygon(x, y, polygon):
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        hit = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
        )
        if hit:
            inside = not inside
        j = i
    return inside


def _ccw(a, b, c):
    return (c[1]-a[1])*(b[0]-a[0]) > (b[1]-a[1])*(c[0]-a[0])


def _segments_intersect(a, b, c, d):
    return _ccw(a, c, d) != _ccw(b, c, d) and _ccw(a, b, c) != _ccw(a, b, d)


def _line_intersects_polygon(coords, polygon):
    if any(_point_in_polygon(float(x), float(y), polygon) for x, y in coords):
        return True
    if len(coords) < 2 or len(polygon) < 3:
        return False
    edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    for a, b in zip(coords, coords[1:]):
        a = (float(a[0]), float(a[1]))
        b = (float(b[0]), float(b[1]))
        for c, d in edges:
            if _segments_intersect(a, b, c, d):
                return True
    return False


def _feature_in_polygon(feature, polygon):
    if not polygon:
        return True
    g = feature.get("geometry") or {}
    typ = g.get("type")
    coords = g.get("coordinates") or []
    if typ == "Point" and len(coords) >= 2:
        return _point_in_polygon(float(coords[0]), float(coords[1]), polygon)
    if typ == "LineString":
        return _line_intersects_polygon(coords, polygon)
    if typ == "MultiLineString":
        return any(_line_intersects_polygon(part, polygon) for part in coords)
    return False


def _flatten_properties(feature):
    p = feature.get("properties") or {}
    attrs = p.get("attributes") or {}
    fields = attrs.get("fields") if isinstance(attrs, dict) else None
    if not isinstance(fields, dict):
        fields = attrs if isinstance(attrs, dict) else {}
    row = {
        "GROUP": p.get("group_id"),
        "LAYER": p.get("layer"),
        "ENTITY_TYPE": p.get("entity_type"),
        "BLOCK_NAME": p.get("block_name"),
        "REGIONAL_OBJECT_ID": p.get("regional_object_id"),
        "ENTITY_ID": p.get("entity_id"),
        "REVISION": p.get("revision"),
    }
    for k, v in fields.items():
        if isinstance(v, (dict, list, tuple)):
            row[str(k)] = json.dumps(v, ensure_ascii=False)
        else:
            row[str(k)] = v
    return row


def _bounds_from_features(features):
    xs, ys = [], []
    for f in features:
        g = f.get("geometry") or {}
        typ, coords = g.get("type"), g.get("coordinates")
        if typ == "Point" and coords:
            xs.append(float(coords[0])); ys.append(float(coords[1]))
        elif typ == "LineString":
            for x, y in coords or []:
                xs.append(float(x)); ys.append(float(y))
        elif typ == "MultiLineString":
            for part in coords or []:
                for x, y in part:
                    xs.append(float(x)); ys.append(float(y))
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _fetch_bbox_recursive(client, region, bbox, depth=0, max_depth=7):
    west, south, east, north = bbox
    raw = client.online_objects(
        region,
        f"{west},{south},{east},{north}",
        limit=5000,
    ) or {}
    features = list(raw.get("features") or [])
    if len(features) < 5000 or depth >= max_depth:
        return features

    mx = (west + east) / 2.0
    my = (south + north) / 2.0
    cells = [
        (west, south, mx, my),
        (mx, south, east, my),
        (west, my, mx, north),
        (mx, my, east, north),
    ]
    merged = {}
    for cell in cells:
        for feature in _fetch_bbox_recursive(client, region, cell, depth + 1, max_depth):
            merged[str(_feature_id(feature))] = feature
    return list(merged.values())


def fetch_region_features(client, region):
    info = client.online_layers(region) or {}
    bounds = info.get("bounds")
    if not bounds:
        return info, []
    bbox = (
        float(bounds["west"]),
        float(bounds["south"]),
        float(bounds["east"]),
        float(bounds["north"]),
    )
    return info, _fetch_bbox_recursive(client, region, bbox)


def export_excel(path, features):
    rows = [_flatten_properties(f) for f in features]
    headers = []
    for row in rows:
        for key in row:
            if key not in headers:
                headers.append(key)

    wb = Workbook()
    ws = wb.active
    ws.title = "SERVER_DATA"
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def export_dxf(path, features, target_epsg=5174):
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    transform = Transformer.from_crs(
        "EPSG:4326",
        f"EPSG:{int(target_epsg)}",
        always_xy=True,
    )

    for feature in features:
        p = feature.get("properties") or {}
        layer = str(p.get("layer") or "SERVER").replace("/", "_")[:240]
        if layer not in doc.layers:
            try:
                doc.layers.add(layer)
            except Exception:
                layer = "SERVER"

        g = feature.get("geometry") or {}
        typ = g.get("type")
        coords = g.get("coordinates") or []

        if typ == "Point" and len(coords) >= 2:
            x, y = transform.transform(float(coords[0]), float(coords[1]))
            msp.add_point((x, y), dxfattribs={"layer": layer})
        elif typ == "LineString" and len(coords) >= 2:
            pts = [transform.transform(float(x), float(y)) for x, y in coords]
            msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
        elif typ == "MultiLineString":
            for part in coords:
                if len(part) >= 2:
                    pts = [transform.transform(float(x), float(y)) for x, y in part]
                    msp.add_lwpolyline(pts, dxfattribs={"layer": layer})

    doc.saveas(path)


class ServerExtractWindow(tk.Toplevel):
    def __init__(self, master, viewer, client=None, current_user=None, source_epsg=5174):
        super().__init__(master)
        self.viewer = viewer
        self.client = client or CMBServerClient()
        self.current_user = current_user or {}
        self.source_epsg = int(source_epsg)
        self.region_rows = []
        self.layer_rows = []
        self.layer_vars = {}
        self.group_vars = {g: tk.BooleanVar(value=(g == "POLE")) for g in GROUPS}
        self.custom_polygon_lonlat = None

        self.title("관리자 · 서버 도면 추출/내려받기")
        self.geometry("980x720")
        self.minsize(860, 620)
        self.transient(master)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="서버 도면 추출 / 내려받기", font=("Malgun Gothic", 16, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="지역과 그룹/레이어를 선택한 뒤 전체 지역 또는 사용자 지정 영역을 추출합니다.",
        ).pack(anchor="w", pady=(2, 10))

        top = ttk.Frame(root)
        top.pack(fill="x")

        ttk.Label(top, text="지역").pack(side="left")
        self.region_var = tk.StringVar()
        self.region_combo = ttk.Combobox(top, textvariable=self.region_var, state="readonly", width=34)
        self.region_combo.pack(side="left", padx=(6, 8))
        self.region_combo.bind("<<ComboboxSelected>>", lambda e: self.load_layers())

        ttk.Button(top, text="지역 새로고침", command=self.load_regions).pack(side="left")

        group_box = ttk.LabelFrame(root, text="그룹", padding=8)
        group_box.pack(fill="x", pady=(10, 8))
        for g in GROUPS:
            ttk.Checkbutton(
                group_box,
                text=g,
                variable=self.group_vars[g],
                command=self._apply_group_filter,
            ).pack(side="left", padx=(0, 12))

        layer_box = ttk.LabelFrame(root, text="실제 레이어 선택", padding=8)
        layer_box.pack(fill="both", expand=True)

        self.layer_canvas = tk.Canvas(layer_box, highlightthickness=0)
        scroll = ttk.Scrollbar(layer_box, orient="vertical", command=self.layer_canvas.yview)
        self.layer_body = ttk.Frame(self.layer_canvas)
        self.layer_window = self.layer_canvas.create_window((0, 0), window=self.layer_body, anchor="nw")
        self.layer_body.bind("<Configure>", lambda e: self.layer_canvas.configure(scrollregion=self.layer_canvas.bbox("all")))
        self.layer_canvas.bind("<Configure>", lambda e: self.layer_canvas.itemconfigure(self.layer_window, width=e.width))
        self.layer_canvas.configure(yscrollcommand=scroll.set)
        self.layer_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(10, 0))

        ttk.Button(controls, text="표시 레이어 전체 선택", command=lambda: self._set_visible_layers(True)).pack(side="left")
        ttk.Button(controls, text="표시 레이어 전체 해제", command=lambda: self._set_visible_layers(False)).pack(side="left", padx=(6, 0))

        self.area_text = tk.StringVar(value="추출 범위: 지역 전체")
        ttk.Label(root, textvariable=self.area_text).pack(anchor="w", pady=(10, 2))

        area_buttons = ttk.Frame(root)
        area_buttons.pack(fill="x")
        ttk.Button(area_buttons, text="지역 전체", command=self.use_whole_region).pack(side="left")
        ttk.Button(area_buttons, text="사용자 지정 영역", command=self.begin_custom_area).pack(side="left", padx=(6, 0))

        export_buttons = ttk.Frame(root)
        export_buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(export_buttons, text="Excel 추출", command=self.save_excel).pack(side="right")
        ttk.Button(export_buttons, text="DXF 내려받기", command=self.save_dxf).pack(side="right", padx=(0, 6))

        self.status = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.status).pack(fill="x", pady=(8, 0))

        self.after(0, self.load_regions)

    def load_regions(self):
        try:
            rows = self.client.online_regions() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("regions") or []
            self.region_rows = list(rows)
            labels = []
            for r in self.region_rows:
                rid = str(r.get("id") or r.get("region_id") or "")
                name = str(r.get("name") or rid)
                labels.append(f"{name} ({rid})")
            self.region_combo["values"] = labels
            if labels and not self.region_var.get():
                self.region_combo.current(0)
                self.load_layers()
            self.status.set(f"지역 {len(labels)}개")
        except Exception as exc:
            messagebox.showerror("지역 조회 오류", str(exc), parent=self)

    def _selected_region_id(self):
        idx = self.region_combo.current()
        if idx < 0 or idx >= len(self.region_rows):
            return ""
        r = self.region_rows[idx]
        return str(r.get("id") or r.get("region_id") or "")

    def load_layers(self):
        region = self._selected_region_id()
        if not region:
            return
        try:
            info = self.client.online_layers(region) or {}
            self.layer_rows = list(info.get("layers") or [])
            self._rebuild_layers()
            self.status.set(f"{region} · 레이어 {len(self.layer_rows)}개")
        except Exception as exc:
            messagebox.showerror("레이어 조회 오류", str(exc), parent=self)

    def _rebuild_layers(self):
        for child in self.layer_body.winfo_children():
            child.destroy()
        self.layer_vars.clear()
        for row in self.layer_rows:
            group = str(row.get("group_id") or "").upper()
            layer = str(row.get("layer") or "")
            key = (group, layer)
            var = tk.BooleanVar(value=self.group_vars.get(group, tk.BooleanVar(value=False)).get())
            self.layer_vars[key] = var
            text = f"[{group}] {layer} · {row.get('object_count', 0)}개"
            cb = ttk.Checkbutton(self.layer_body, text=text, variable=var)
            cb.pack(anchor="w", pady=2)
            cb._cmb_group = group
        self._apply_group_filter()

    def _apply_group_filter(self):
        selected_groups = {g for g, var in self.group_vars.items() if var.get()}
        for child in self.layer_body.winfo_children():
            group = getattr(child, "_cmb_group", "")
            if group in selected_groups:
                child.pack(anchor="w", pady=2)
            else:
                child.pack_forget()

    def _set_visible_layers(self, value):
        selected_groups = {g for g, var in self.group_vars.items() if var.get()}
        for (group, _layer), var in self.layer_vars.items():
            if group in selected_groups:
                var.set(bool(value))

    def use_whole_region(self):
        self.custom_polygon_lonlat = None
        self.area_text.set("추출 범위: 지역 전체")

    def begin_custom_area(self):
        if self.viewer is None or getattr(self.viewer, "scene", None) is None:
            messagebox.showinfo("사용자 지정 영역", "맵추출 뷰어에 먼저 DXF 도면을 열어주세요.", parent=self)
            return

        self.withdraw()

        def finished(points):
            try:
                transformer = Transformer.from_crs(
                    f"EPSG:{self.source_epsg}",
                    "EPSG:4326",
                    always_xy=True,
                )
                self.custom_polygon_lonlat = [
                    transformer.transform(float(x), float(y))
                    for x, y in points
                ]
                self.area_text.set(f"추출 범위: 사용자 지정 다각형 · {len(points)}개 점")
            finally:
                self.deiconify()
                self.lift()

        self.viewer.begin_area_select(finished)

    def _selection(self):
        region = self._selected_region_id()
        if not region:
            raise RuntimeError("지역을 선택해주세요.")
        groups = {g for g, var in self.group_vars.items() if var.get()}
        layers = {
            (g, layer)
            for (g, layer), var in self.layer_vars.items()
            if var.get() and g in groups
        }
        if not groups:
            raise RuntimeError("그룹을 하나 이상 선택해주세요.")
        if not layers:
            raise RuntimeError("실제 레이어를 하나 이상 선택해주세요.")
        return region, groups, layers

    def _collect(self):
        region, groups, layers = self._selection()
        self.status.set("서버 객체 조회 중...")
        self.update_idletasks()

        _info, features = fetch_region_features(self.client, region)
        filtered = []
        for f in features:
            p = f.get("properties") or {}
            group = str(p.get("group_id") or "").upper()
            layer = str(p.get("layer") or "")
            if group not in groups or (group, layer) not in layers:
                continue
            if not _feature_in_polygon(f, self.custom_polygon_lonlat):
                continue
            filtered.append(f)

        self.status.set(f"추출 대상 {len(filtered):,}개")
        if not filtered:
            raise RuntimeError("선택 조건에 해당하는 서버 객체가 없습니다.")
        return region, filtered

    def save_excel(self):
        try:
            region, features = self._collect()
            out = filedialog.asksaveasfilename(
                title="서버 정보 Excel 추출",
                defaultextension=".xlsx",
                initialfile=f"{region}_서버추출.xlsx",
                filetypes=[("Excel", "*.xlsx")],
                parent=self,
            )
            if not out:
                return
            export_excel(out, features)
            messagebox.showinfo("완료", f"{len(features):,}개 객체를 Excel로 저장했습니다.", parent=self)
        except Exception as exc:
            messagebox.showerror("서버 추출 오류", str(exc), parent=self)

    def save_dxf(self):
        try:
            region, features = self._collect()
            out = filedialog.asksaveasfilename(
                title="서버 도면 DXF 내려받기",
                defaultextension=".dxf",
                initialfile=f"{region}_SERVER.dxf",
                filetypes=[("DXF", "*.dxf")],
                parent=self,
            )
            if not out:
                return
            export_dxf(out, features, self.source_epsg)
            meta = Path(out).with_suffix(".json")
            meta.write_text(
                json.dumps({"region": region, "features": features}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            messagebox.showinfo(
                "완료",
                f"{len(features):,}개 객체를 DXF로 저장했습니다.\n속성 원본은 같은 이름의 JSON에 저장했습니다.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("서버 내려받기 오류", str(exc), parent=self)
