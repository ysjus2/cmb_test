from pathlib import Path
import re

def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f"FAST patch target not found: {label}")
    return text.replace(old, new, 1)

viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")

# Cache dependencies; applied after all v3.20/v3.19 legacy UI patches.
viewer = replace_once(
    viewer,
    "import math\n",
    "import math\nimport hashlib\nimport os\nimport pickle\nimport tempfile\n",
    "viewer cache imports",
)
viewer = replace_once(
    viewer,
    "from converter import load_dxf_document\n",
    "from converter import load_dxf_document, LayerInfo\n",
    "LayerInfo import",
)

# Insert exact production layer policy + cache wrapper before DXFViewer class.
marker = "class DXFViewer(ttk.Frame):\n"
if marker not in viewer:
    raise RuntimeError("DXFViewer marker not found")

helper = r'''
CACHE_VERSION = "v320-fast-lod-2"

def _cache_root():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    root = Path(base) / "CMB_DXF_Viewer" / "dxf_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root

def _cache_path(input_path):
    key = hashlib.sha256(os.path.abspath(str(input_path)).encode("utf-8", errors="ignore")).hexdigest()
    return _cache_root() / f"{key}.scene.pkl"

def _source_signature(input_path):
    p = Path(input_path)
    st = p.stat()
    return {
        "version": CACHE_VERSION,
        "path": os.path.abspath(str(p)),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }

def _load_scene_cache(input_path, log):
    try:
        cp = _cache_path(input_path)
        if not cp.exists():
            return None
        with cp.open("rb") as f:
            payload = pickle.load(f)
        if payload.get("signature") != _source_signature(input_path):
            return None
        scene = payload.get("scene")
        if scene is not None:
            log("CMB 캐시 사용")
            return scene
    except Exception as exc:
        log(f"CMB 캐시 읽기 생략: {exc}")
    return None

def _save_scene_cache(input_path, scene, log):
    try:
        cp = _cache_path(input_path)
        tmp = cp.with_suffix(".tmp")
        with tmp.open("wb") as f:
            pickle.dump(
                {"signature": _source_signature(input_path), "scene": scene},
                f,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        os.replace(tmp, cp)
        log("CMB 캐시 저장 완료")
    except Exception as exc:
        log(f"CMB 캐시 저장 생략: {exc}")

_build_scene_v320 = build_scene

def build_scene(input_path, log=None, progress=None):
    log = log or (lambda msg: None)
    progress = progress or (lambda percent, task: None)
    cached = _load_scene_cache(input_path, log)
    if cached is not None:
        progress(100, "CMB 캐시 로딩 완료")
        return cached
    scene = _build_scene_v320(input_path, log=log, progress=progress)
    _save_scene_cache(input_path, scene, log)
    return scene

def layer_info_from_scene(scene):
    counts = {}
    types = {}
    for ent in scene.entities:
        counts[ent.layer] = counts.get(ent.layer, 0) + 1
        types.setdefault(ent.layer, set()).add(ent.entity_type)
    return [
        LayerInfo(name, counts[name], ", ".join(sorted(types[name])))
        for name in sorted(counts, key=str.lower)
    ]

def _layer_stage(ent):
    """0..10: region, fiber, cell, coax, device, road, building-group, pole/manhole, conduit, other-building, parcel."""
    layer = str(ent.layer or "").strip()
    u = layer.upper()

    # 0 지역구분
    if u in {"TL_SCCO_SIG", "TL_SCCO_EMD", "TL_SCCO_END", "TL_SCCO_LI"}:
        return 0

    # 1 광케이블
    if u.startswith("CN_F_CABLE_") or u == "CN_F_CABLE":
        return 1

    # 2 셀 경계/셀 구분
    if u.startswith("CN_C_CELLBOUND") or u.startswith("CN_C_ID_CELL") or u.startswith("CN_C_CELLNO"):
        return 2

    # 3 동축/RG/PFC 케이블
    if u.startswith("CN_C_CABLE_"):
        return 3

    # 7 전주/맨홀
    if (
        u.startswith("CN_L_POLE_MANHOLE")
        or u.startswith("CN_L_POLE_HANDHOLE")
        or u.startswith("CN_L_POLE_POLE")
        or u.startswith("CN_L_POLE_ID")
        or u == "CN_L_POLE"
    ):
        return 7

    # 8 관로/지중/가공 선로
    if u.startswith("CN_L_POLE_LINE_"):
        return 8

    # 5 도로
    if u == "TL_SPRD_RW":
        return 5

    # 10 지번
    if layer == "지번":
        return 10

    # 6 건물_건물군만 먼저
    if layer == "건물_건물군":
        return 6

    # 9 나머지 건물 정보
    if layer.startswith("건물_") or u.startswith("CN_M_USER_BUILDING"):
        return 9

    # 4 각종 통신 기기
    device_prefixes = (
        "CN_C_ONU", "CN_C_POWER", "CN_C_AMP", "CN_C_TAP", "CN_C_PASSIVE",
        "CN_C_CONNECTOR", "CN_C_ID_ACTIVE", "CN_C_ID_TAP", "CN_C_ID_PASSIVE",
        "CN_C_ID_DROP", "CN_F_CLOSURE", "CN_F_CENTER", "CN_F_TERMINAL",
        "CN_F_ID_", "CN_C_DC_", "CN_C_SUBSCRIBERS", "CN_C_NMS_",
    )
    if u.startswith(device_prefixes):
        return 4

    # Other map/user/background information is deliberately delayed with other buildings.
    return 9

def _zoom_stage(viewer):
    fit = max(float(getattr(viewer, "fit_scale", 0.0) or 0.0), 1e-12)
    ratio = float(viewer.scale) / fit
    # Wide bands: several wheel notches per information group.
    if ratio < 1.60: return 0
    if ratio < 2.50: return 1
    if ratio < 3.80: return 2
    if ratio < 5.80: return 3
    if ratio < 8.50: return 4
    if ratio < 12.5: return 5
    if ratio < 18.5: return 6
    if ratio < 27.0: return 7
    if ratio < 37.0: return 8
    if ratio < 50.0: return 9
    return 10

def _bbox_intersects(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

'''
viewer = viewer.replace(marker, helper + marker, 1)

# Remember fit scale without changing v3.20 geometry calculations.
viewer = replace_once(
    viewer,
    "        self.scale = 1.0\n",
    "        self.scale = 1.0\n        self.fit_scale = 1.0\n",
    "fit scale init",
)
viewer = replace_once(
    viewer,
    "        self.scale = max(1e-9, min((w-margin*2)/dx, (h-margin*2)/dy))\n",
    "        self.scale = max(1e-9, min((w-margin*2)/dx, (h-margin*2)/dy))\n        self.fit_scale = self.scale\n",
    "fit scale capture",
)

# Progressive layer filtering + viewport culling. Do not touch primitive rendering,
# cable colors, arrows, block virtual entities, or connection coordinates.
old_loop = '''        for ent in self.scene.entities:
            if ent.layer not in self.visible_layers:
                continue
            selected = ent.index in self.selected
'''
new_loop = '''        stage = _zoom_stage(self)
        x1, y1 = self.screen_to_world(0, self.canvas.winfo_height())
        x2, y2 = self.screen_to_world(self.canvas.winfo_width(), 0)
        viewport = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        stage_names = (
            "지역구분", "광케이블", "셀경계", "동축케이블", "각종 기기",
            "도로", "건물_건물군", "전주/맨홀", "관로", "나머지 건물", "지번",
        )
        for ent in self.scene.entities:
            if ent.layer not in self.visible_layers:
                continue
            if _layer_stage(ent) > stage:
                continue
            if ent.bbox is not None and not _bbox_intersects(ent.bbox, viewport):
                continue
            selected = ent.index in self.selected
'''
viewer = replace_once(viewer, old_loop, new_loop, "redraw progressive filter")

# Add current stage to status after redraw without interfering with interaction status.
redraw_end_target = '''            if ids:
                self.entity_items[ent.index] = ids
                for item_id in ids:
                    self.item_to_entity[item_id] = ent.index
'''
if redraw_end_target in viewer:
    viewer = viewer.replace(
        redraw_end_target,
        redraw_end_target + '''        try:
            self.status_var.set(f"표시 단계 {stage+1}/11 · {stage_names[stage]} · 캐시/화면영역 렌더링")
        except Exception:
            pass
''',
        1,
    )


# Fiber route pick mode: two device clicks are passed to the main app.
viewer = replace_once(
    viewer,
    "        self.pan_start = None\\n",
    "        self.pan_start = None\\n        self.route_pick_callback = None\\n        self.route_pick_indices = []\\n",
    "route pick state",
)
viewer = replace_once(
    viewer,
    '''        idx = self._nearest_entity(event.x, event.y)
        shift = bool(event.state & 0x0001)
''',
    '''        idx = self._nearest_entity(event.x, event.y)
        if self.mode == "fiber_route":
            if idx is None:
                self.info_var.set("기기 또는 함체를 정확히 클릭해주세요.")
                return
            self.route_pick_indices.append(idx)
            self.selected = set(self.route_pick_indices[-2:])
            count = len(self.route_pick_indices)
            if count == 1:
                ent = self.scene.entities[idx]
                self.info_var.set(f"광 구간 시작 기기 선택: {ent.block_name or ent.layer} · 끝 기기를 클릭하세요.")
            elif count >= 2:
                picks = self.route_pick_indices[-2:]
                self.route_pick_indices = []
                cb = self.route_pick_callback
                if cb:
                    cb(picks[0], picks[1])
            self.redraw()
            return
        shift = bool(event.state & 0x0001)
''',
    "fiber route click mode",
)
viewer = replace_once(
    viewer,
    '''    def set_mode(self, mode):
        self.mode = mode
        self.measure_points = []
''',
    '''    def set_mode(self, mode):
        self.mode = mode
        self.measure_points = []
        if mode != "fiber_route":
            self.route_pick_indices = []
''',
    "route mode reset",
)

viewer_path.write_text(viewer, encoding="utf-8")

# Main: single parse on first load; on subsequent loads use scene cache directly.
main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace(
    "from viewer import DXFViewer, build_scene",
    "from viewer import DXFViewer, build_scene, layer_info_from_scene",
    1,
)

pattern = re.compile(
    r'''                layers = scan_layers\(\n.*?\n                scene = build_scene\(\n.*?\n                self\.q\.put\(\("loaded", \(layers, scene\)\)\)''',
    re.S,
)
replacement = '''                scene = build_scene(
                    inp,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda p, t: self.q.put(("progress", (int(p), t))),
                )
                layers = layer_info_from_scene(scene)
                self.q.put(("loaded", (layers, scene)))'''
main, n = pattern.subn(replacement, main, count=1)
if n != 1:
    raise RuntimeError("FAST patch target not found: main scan/build worker")



# Route-based coordinate export.
# Fiber: click start device then end device. Export only start/end devices and intermediate closures.
# Main conduit: 100 mm layer is not confirmed yet, so do not guess a layer.

main = main.replace(
    "import os\\nimport queue\\n",
    "import os\\nimport queue\\nimport heapq\\nimport math\\n",
    1,
)
main = main.replace(
    "from tkinter import filedialog, messagebox, ttk\\n",
    "from tkinter import filedialog, messagebox, ttk\\nfrom openpyxl import Workbook\\nfrom openpyxl.styles import Font\\n",
    1,
)

# Menu.
main = replace_once(
    main,
    '''        file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")
        file_menu.add_separator()
''',
    '''        file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="광 구간 좌표추출...", command=self._start_fiber_route_export)
        file_menu.add_command(label="주관로 구간 좌표추출...", command=self._main_conduit_pending)
        file_menu.add_separator()
''',
    "route export menu",
)

# Visible buttons.
main = replace_once(
    main,
    '''        self.viewer = DXFViewer(root)
        self.viewer.pack(fill="both", expand=True)
        self.viewer.set_source_epsg(self.epsg_var.get())
''',
    '''        quickbar = ttk.Frame(root)
        quickbar.pack(fill="x", pady=(0, 3))
        ttk.Button(
            quickbar, text="광 구간 좌표추출",
            command=self._start_fiber_route_export
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            quickbar, text="주관로 구간 좌표추출",
            command=self._main_conduit_pending
        ).pack(side="left")

        self.viewer = DXFViewer(root)
        self.viewer.pack(fill="both", expand=True)
        self.viewer.set_source_epsg(self.epsg_var.get())
        self.viewer.route_pick_callback = self._finish_fiber_route_export
''',
    "route export buttons",
)

route_methods = r'''
    @staticmethod
    def _entity_anchor(ent):
        for kind, data in ent.primitives:
            if kind in {"insert", "point", "text"}:
                return (float(data[0]), float(data[1]))
            if kind == "circle":
                return (float(data[0]), float(data[1]))
        if ent.bbox is not None:
            b = ent.bbox
            return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)
        return None

    @staticmethod
    def _fiber_entity(ent):
        u = str(ent.layer or "").upper()
        return u.startswith("CN_F_CABLE") or "FOC" in u or "FIBER" in u

    @staticmethod
    def _closure_entity(ent):
        u = str(ent.layer or "").upper()
        b = str(ent.block_name or "").upper()
        return u.startswith("CN_F_CLOSURE") or "CLOSURE" in b

    def _start_fiber_route_export(self):
        if self.busy:
            return
        if not self.viewer.scene:
            messagebox.showerror(APP_NAME, "먼저 DXF 파일을 열어주세요.")
            return
        self.viewer.route_pick_indices = []
        self.viewer.set_mode("fiber_route")
        self.viewer.clear_selection()
        self.viewer.info_var.set("광 구간 좌표추출: 시작 기기를 클릭한 뒤 끝 기기를 클릭하세요.")
        self.status_var.set("광 구간 좌표추출 · 시작 기기 선택 대기")

    def _main_conduit_pending(self):
        messagebox.showinfo(
            APP_NAME,
            "주관로(100mm) 레이어가 아직 확정되지 않았습니다.\\n\\n"
            "임의 레이어로 추출하지 않습니다. 100mm 관로 레이어가 확인되면 "
            "맨홀→맨홀 위치와 전주 입상관로의 전주 위치만 추출하도록 연결합니다."
        )

    @staticmethod
    def _path_projection(point, path):
        if len(path) < 2:
            return (float("inf"), 0.0)
        px, py = point
        best_d = float("inf")
        best_along = 0.0
        walked = 0.0
        for a, b in zip(path, path[1:]):
            ax, ay = a
            bx, by = b
            dx, dy = bx - ax, by - ay
            seg2 = dx*dx + dy*dy
            seglen = math.sqrt(seg2)
            if seg2 <= 1e-18:
                walked += seglen
                continue
            t = ((px-ax)*dx + (py-ay)*dy) / seg2
            t = max(0.0, min(1.0, t))
            qx, qy = ax + t*dx, ay + t*dy
            d = math.hypot(px-qx, py-qy)
            if d < best_d:
                best_d = d
                best_along = walked + t*seglen
            walked += seglen
        return best_d, best_along

    def _fiber_route_path(self, start_ent, end_ent):
        scene = self.viewer.scene
        if not scene:
            raise RuntimeError("DXF 장면이 없습니다.")

        minx, miny, maxx, maxy = scene.bbox
        diag = math.hypot(maxx-minx, maxy-miny)
        snap = max(0.05, min(0.50, diag * 1e-5))

        graph = {}
        coords = {}

        def key(p):
            return (int(round(p[0] / snap)), int(round(p[1] / snap)))

        def add_edge(a, b):
            ka, kb = key(a), key(b)
            coords.setdefault(ka, (float(a[0]), float(a[1])))
            coords.setdefault(kb, (float(b[0]), float(b[1])))
            w = math.hypot(b[0]-a[0], b[1]-a[1])
            if w <= 1e-12:
                return
            graph.setdefault(ka, []).append((kb, w))
            graph.setdefault(kb, []).append((ka, w))

        fiber_count = 0
        for ent in scene.entities:
            if not self._fiber_entity(ent):
                continue
            for kind, data in ent.primitives:
                if kind not in {"line", "polyline"} or len(data) < 2:
                    continue
                fiber_count += 1
                for a, b in zip(data, data[1:]):
                    add_edge(a, b)

        if not graph:
            raise RuntimeError("광케이블 경로 데이터를 찾지 못했습니다.")

        sa = self._entity_anchor(start_ent)
        ea = self._entity_anchor(end_ent)
        if sa is None or ea is None:
            raise RuntimeError("선택한 기기의 좌표를 읽을 수 없습니다.")

        nodes = list(coords)
        start_node = min(nodes, key=lambda k: math.hypot(coords[k][0]-sa[0], coords[k][1]-sa[1]))
        end_node = min(nodes, key=lambda k: math.hypot(coords[k][0]-ea[0], coords[k][1]-ea[1]))

        dist = {start_node: 0.0}
        prev = {}
        pq = [(0.0, start_node)]
        while pq:
            d, u = heapq.heappop(pq)
            if d != dist.get(u):
                continue
            if u == end_node:
                break
            for v, w in graph.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(pq, (nd, v))

        if end_node not in dist:
            raise RuntimeError("선택한 두 기기 사이의 광케이블 연결 경로를 찾지 못했습니다.")

        chain = [end_node]
        while chain[-1] != start_node:
            chain.append(prev[chain[-1]])
        chain.reverse()
        path = [coords[k] for k in chain]
        return path, dist[end_node], snap

    def _finish_fiber_route_export(self, start_idx, end_idx):
        try:
            scene = self.viewer.scene
            if not scene:
                return
            start_ent = scene.entities[start_idx]
            end_ent = scene.entities[end_idx]

            # Prevent accidentally using a cable itself as a start/end device.
            if self._fiber_entity(start_ent) or self._fiber_entity(end_ent):
                messagebox.showerror(APP_NAME, "광케이블 선이 아니라 시작 기기와 끝 기기를 각각 클릭해주세요.")
                self._start_fiber_route_export()
                return

            path, route_length, snap = self._fiber_route_path(start_ent, end_ent)

            closures = []
            for ent in scene.entities:
                if not self._closure_entity(ent):
                    continue
                p = self._entity_anchor(ent)
                if p is None:
                    continue
                d, along = self._path_projection(p, path)
                # Closure symbols can be slightly offset from the cable contact.
                if d <= max(2.0, snap * 8.0):
                    closures.append((along, ent, p))
            closures.sort(key=lambda x: x[0])

            # Remove duplicates caused by label/block pairs at the same closure.
            unique = []
            for along, ent, p in closures:
                if unique and math.hypot(p[0]-unique[-1][2][0], p[1]-unique[-1][2][1]) < max(0.5, snap*4):
                    continue
                unique.append((along, ent, p))
            closures = unique

            out = filedialog.asksaveasfilename(
                title="광 구간 좌표추출",
                defaultextension=".xlsx",
                initialfile=Path(self.input_path).stem + "_광구간_기기함체좌표.xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if not out:
                self.viewer.set_mode("select")
                return

            wb = Workbook()
            ws = wb.active
            ws.title = "광구간"
            headers = [
                "순번", "구분", "기기/함체", "레이어", "블록명", "핸들",
                "CAD_X", "CAD_Y", "위도", "경도", "경로누적거리", "속성"
            ]
            ws.append(headers)
            for cell in ws[1]:
                cell.font = Font(bold=True)

            records = []
            sp = self._entity_anchor(start_ent)
            ep = self._entity_anchor(end_ent)
            records.append((0.0, "시작기기", start_ent, sp))
            for along, ent, p in closures:
                records.append((along, "중간함체", ent, p))
            records.append((route_length, "끝기기", end_ent, ep))

            for seq, (along, kind, ent, p) in enumerate(records, 1):
                x, y = p
                lon, lat = self.viewer.transformer.transform(x, y)
                name = ent.text or ent.block_name or ent.layer
                attrs = " | ".join(f"{k}={v}" for k, v in (ent.attributes or {}).items() if str(v).strip())
                ws.append([
                    seq, kind, name, ent.layer, ent.block_name, ent.handle,
                    x, y, lat, lon, along, attrs
                ])

            ws.freeze_panes = "A2"
            widths = [7,12,28,28,24,14,16,16,15,15,16,45]
            for i, width in enumerate(widths, 1):
                ws.column_dimensions[chr(64+i) if i <= 26 else "A"].width = width

            summary = wb.create_sheet("구간요약")
            summary.append(["항목", "내용"])
            summary.append(["시작", start_ent.text or start_ent.block_name or start_ent.layer])
            summary.append(["끝", end_ent.text or end_ent.block_name or end_ent.layer])
            summary.append(["광경로 길이", route_length])
            summary.append(["중간 함체 수", len(closures)])
            summary.append(["중간 케이블 접점", "Excel 추출 제외"])
            wb.save(out)

            self.viewer.set_mode("select")
            self.viewer.selected = {start_idx, end_idx}
            self.viewer.redraw()
            self.status_var.set(
                f"광 구간 좌표추출 완료 · 시작/끝 + 중간함체 {len(closures)}개 · {Path(out).name}"
            )
            messagebox.showinfo(
                APP_NAME,
                f"광 구간 좌표추출 완료\\n\\n"
                f"중간 케이블 접점은 제외했습니다.\\n"
                f"중간 함체: {len(closures)}개\\n"
                f"광 경로 길이: {route_length:,.2f}"
            )
        except Exception as e:
            self.viewer.set_mode("select")
            messagebox.showerror(APP_NAME, f"광 구간 좌표추출 오류:\\n{e}")

'''
insert_at='''    def _run_excel(self):
'''
if insert_at not in main:
    raise RuntimeError("FAST patch target not found: _run_excel")
main = main.replace(insert_at, route_methods + insert_at, 1)

main_path.write_text(main, encoding="utf-8")
print("v3.20 fast cache + progressive display + fiber/conduit quick Excel export applied")
