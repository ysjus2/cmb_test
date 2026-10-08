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


# Restore dedicated quick Excel export actions from the later PC workflow.
# They export actual DXF data through the same proven convert_selected_layers()
# path, so ESSENPOLY fiber recovery and coordinates remain identical to v3.20.

# Add menu commands.
main = replace_once(
    main,
    '''        file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")
        file_menu.add_separator()
''',
    '''        file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="광 구간 Excel 추출...", command=lambda: self._run_quick_excel("fiber"))
        file_menu.add_command(label="주관로 Excel 추출...", command=lambda: self._run_quick_excel("conduit"))
        file_menu.add_separator()
''',
    "quick export menu",
)

# Add visible buttons directly above the viewer surface.
main = replace_once(
    main,
    '''        self.viewer = DXFViewer(root)
        self.viewer.pack(fill="both", expand=True)
        self.viewer.set_source_epsg(self.epsg_var.get())
''',
    '''        quickbar = ttk.Frame(root)
        quickbar.pack(fill="x", pady=(0, 3))
        ttk.Button(
            quickbar, text="광 구간 Excel 추출",
            command=lambda: self._run_quick_excel("fiber")
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            quickbar, text="주관로 Excel 추출",
            command=lambda: self._run_quick_excel("conduit")
        ).pack(side="left")

        self.viewer = DXFViewer(root)
        self.viewer.pack(fill="both", expand=True)
        self.viewer.set_source_epsg(self.epsg_var.get())
''',
    "quick export buttons",
)

quick_method = r'''
    def _run_quick_excel(self, kind):
        if self.busy:
            return
        if not self.input_path or not os.path.isfile(self.input_path):
            messagebox.showerror(APP_NAME, "먼저 DXF 파일을 열어주세요.")
            return

        available = sorted({row[0] for row in self.layer_rows.values()})
        if kind == "fiber":
            selected = [
                name for name in available
                if name.upper().startswith("CN_F_CABLE")
                or "FOC" in name.upper()
                or "FIBER" in name.upper()
            ]
            label = "광 구간"
            suffix = "_광구간.xlsx"
        else:
            exact = [name for name in available if name.upper() == "CN_L_POLE_LINE_CONDUIT"]
            selected = exact or [
                name for name in available
                if "CONDUIT" in name.upper() or "관로" in name
            ]
            label = "주관로"
            suffix = "_주관로.xlsx"

        if not selected:
            messagebox.showerror(APP_NAME, f"{label} 추출 대상 레이어를 찾지 못했습니다.")
            return

        default_name = Path(self.input_path).stem + suffix
        out = filedialog.asksaveasfilename(
            title=f"{label} Excel 추출",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel", "*.xlsx")],
        )
        if not out:
            return

        try:
            epsg = int(self.epsg_var.get())
        except ValueError:
            messagebox.showerror(APP_NAME, "좌표계 설정을 확인해주세요.")
            return

        self.busy = True
        self._show_progress()
        self._set_progress(0, f"{label} Excel 추출 준비")
        self._log(f"{label} 추출 레이어: " + ", ".join(selected))

        def worker():
            try:
                stats = convert_selected_layers(
                    self.input_path,
                    out,
                    selected,
                    epsg,
                    None,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda p, t: self.q.put(("progress", (p, t))),
                )
                self.q.put(("done", (stats, out)))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

'''
insert_at='''    def _run_excel(self):
'''
if insert_at not in main:
    raise RuntimeError("FAST patch target not found: _run_excel")
main = main.replace(insert_at, quick_method + insert_at, 1)

main_path.write_text(main, encoding="utf-8")
print("v3.20 fast cache + progressive display + fiber/conduit quick Excel export applied")
