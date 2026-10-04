from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v3.18 patch target not found: {label}")
    return text.replace(old, new, 1)


# -----------------------------------------------------------------------------
# Viewer: 상단 도구바는 전체 폭 유지, 그 아래 body만 좌측 레이어/우측 Canvas로 분할
# -----------------------------------------------------------------------------
viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")

old_canvas = '''        self.canvas = tk.Canvas(\n            self,\n            background="#171a1f",\n            highlightthickness=0,\n            cursor="crosshair",\n        )\n        self.canvas.pack(fill="both", expand=True)\n'''
new_canvas = '''        # 상단 도구바는 전체 폭을 그대로 유지한다.\n        # 레이어 도킹 영역과 DXF Canvas는 그 아래 body에서만 좌/우로 나뉜다.\n        self.body = ttk.Frame(self)\n        self.body.pack(fill="both", expand=True)\n\n        self.side_host = ttk.Frame(self.body, width=420)\n        self.side_host.pack_propagate(False)\n\n        self.canvas_host = ttk.Frame(self.body)\n        self.canvas_host.pack(side="left", fill="both", expand=True)\n\n        self.canvas = tk.Canvas(\n            self.canvas_host,\n            background="#171a1f",\n            highlightthickness=0,\n            cursor="crosshair",\n        )\n        self.canvas.pack(fill="both", expand=True)\n'''
viewer = replace_once(viewer, old_canvas, new_canvas, "viewer body split host")
viewer_path.write_text(viewer, encoding="utf-8")


# -----------------------------------------------------------------------------
# Main: 기본 레이어는 Toplevel이 아니라 Viewer 내부 side_host에 실제로 도킹
# -----------------------------------------------------------------------------
main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.17"', 'APP_NAME = "CMB DXF Viewer + Excel v3.18"', 1)

old_view = '''        # 레이어 창은 독립 Toplevel이지만, 본창 내부에 있을 때는\n        # 좌측 도킹 공간을 확보하여 도면과 겹치지 않게 한다.\n        self.viewer_host = ttk.Frame(root)\n        self.viewer_host.pack(fill="both", expand=True)\n\n        self.layer_dock_space = ttk.Frame(self.viewer_host, width=430)\n        self.layer_dock_space.pack(side="left", fill="y")\n        self.layer_dock_space.pack_propagate(False)\n        self.layer_docked = True\n\n        self.viewer_frame = ttk.Frame(self.viewer_host)\n        self.viewer_frame.pack(side="left", fill="both", expand=True)\n\n        self.viewer = DXFViewer(self.viewer_frame)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n\n        status = ttk.Frame(root)\n'''
new_view = '''        # Viewer 자체가 전체 폭을 차지한다.\n        # 레이어는 Viewer의 상단 도구바 아래 side_host에 실제 위젯으로 도킹된다.\n        self.viewer = DXFViewer(root)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n\n        status = ttk.Frame(root)\n'''
main = replace_once(main, old_view, new_view, "remove fake dock blank space")

old_start = '''        self._create_layer_window(show=True)\n        if self.layer_window is not None and self.layer_window.winfo_exists():\n            self.layer_window.bind("<Configure>", self._layer_window_configure, add="+")\n        self.after(180, self._place_layer_window_left)\n\n        self.bind("<F11>", lambda e: self._toggle_fullscreen())\n'''
new_start = '''        # 시작 시 레이어는 본창 내부 좌측에 실제 도킹된 패널로 표시한다.\n        self._build_docked_layer_panel()\n\n        self.bind("<F11>", lambda e: self._toggle_fullscreen())\n'''
main = replace_once(main, old_start, new_start, "start with true docked layer panel")

# 도킹/플로팅 관련 v3.17 메서드 전체를 v3.18 구조로 교체한다.
start_marker = '    def _set_layer_docked(self, docked):\n'
end_marker = '    def _epsg_changed(self):\n'
start = main.find(start_marker)
end = main.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError("v3.18 patch target not found: v3.17 dock methods")

methods = '''    def _rebuild_layer_tree_rows(self):\n        if self.tree is None:\n            return\n        try:\n            self.tree.delete(*self.tree.get_children())\n        except Exception:\n            return\n        for iid, row in self.layer_rows.items():\n            try:\n                self.tree.insert("", "end", iid=iid, values=self._row_values(iid))\n                if iid in self.highlighted_iids:\n                    self.tree.item(iid, tags=("range_selected",))\n            except Exception:\n                pass\n\n    def _build_layer_tree_in(self, parent):\n        for child in parent.winfo_children():\n            child.destroy()\n\n        self.tree = ttk.Treeview(\n            parent,\n            columns=("check", "layer", "count", "types"),\n            show="headings",\n            selectmode="extended",\n        )\n        self.tree.heading("check", text="선택")\n        self.tree.heading("layer", text="레이어명")\n        self.tree.heading("count", text="객체수")\n        self.tree.heading("types", text="객체종류")\n        self.tree.column("check", width=55, anchor="center", stretch=False)\n        self.tree.column("layer", width=210)\n        self.tree.column("count", width=65, anchor="center", stretch=False)\n        self.tree.column("types", width=120)\n        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")\n        self.tree.bind("<Button-1>", self._tree_click)\n        self.tree.bind("<Button-3>", self._layer_context_menu)\n\n        y = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)\n        self.tree.configure(yscrollcommand=y.set)\n        self.tree.pack(side="left", fill="both", expand=True)\n        y.pack(side="right", fill="y")\n        self._rebuild_layer_tree_rows()\n\n    def _build_docked_layer_panel(self):\n        # 플로팅 창이 있으면 닫고, Viewer 내부 좌측에 실제 레이어 패널을 만든다.\n        if self.layer_window is not None:\n            try:\n                if self.layer_window.winfo_exists():\n                    self.layer_window.destroy()\n            except Exception:\n                pass\n            self.layer_window = None\n\n        host = self.viewer.side_host\n        for child in host.winfo_children():\n            child.destroy()\n\n        self.layer_panel = ttk.Frame(host, relief="solid", borderwidth=1)\n        self.layer_panel.pack(fill="both", expand=True)\n\n        title = ttk.Frame(self.layer_panel, padding=(7, 4))\n        title.pack(fill="x")\n        self.layer_title = ttk.Label(title, text="레이어", anchor="w")\n        self.layer_title.pack(side="left", fill="x", expand=True)\n        close_btn = ttk.Button(title, text="×", width=3, command=self._hide_layer_window)\n        close_btn.pack(side="right")\n\n        body = ttk.Frame(self.layer_panel, padding=(4, 0, 4, 4))\n        body.pack(fill="both", expand=True)\n        self._build_layer_tree_in(body)\n\n        # 제목줄을 끌면 일정 거리 이후 독립 창으로 분리한다.\n        for widget in (title, self.layer_title):\n            widget.bind("<ButtonPress-1>", self._layer_drag_start)\n            widget.bind("<B1-Motion>", self._layer_drag_motion)\n\n        host.configure(width=420)\n        if not host.winfo_ismapped():\n            host.pack(side="left", fill="y", before=self.viewer.canvas_host)\n        self.layer_docked = True\n        self.after(20, self.viewer.redraw)\n\n    def _layer_drag_start(self, event):\n        self._layer_drag_origin = (event.x_root, event.y_root)\n        self._layer_drag_detached = False\n\n    def _layer_drag_motion(self, event):\n        origin = getattr(self, "_layer_drag_origin", None)\n        if not origin or getattr(self, "_layer_drag_detached", False):\n            return\n        dx = event.x_root - origin[0]\n        dy = event.y_root - origin[1]\n        if dx * dx + dy * dy < 900:\n            return\n        self._layer_drag_detached = True\n        self._detach_layer_window(event.x_root - 40, event.y_root - 15)\n\n    def _detach_layer_window(self, x=None, y=None):\n        # 내부 패널을 제거하면 Canvas가 즉시 전체 폭을 사용한다.\n        try:\n            self.viewer.side_host.pack_forget()\n        except Exception:\n            pass\n        self.tree = None\n        try:\n            for child in self.viewer.side_host.winfo_children():\n                child.destroy()\n        except Exception:\n            pass\n\n        self.layer_window = None\n        self._create_layer_window(show=True)\n        self._rebuild_layer_tree_rows()\n        if self.layer_window is not None and self.layer_window.winfo_exists():\n            try:\n                if x is not None and y is not None:\n                    self.layer_window.geometry(f"430x720+{max(0, int(x))}+{max(0, int(y))}")\n                self.layer_window.lift()\n            except Exception:\n                pass\n        self.layer_docked = False\n        self.after(20, self.viewer.redraw)\n\n    def _hide_layer_window(self):\n        if self.layer_window is not None:\n            try:\n                if self.layer_window.winfo_exists():\n                    self.layer_window.destroy()\n            except Exception:\n                pass\n            self.layer_window = None\n        try:\n            self.viewer.side_host.pack_forget()\n            for child in self.viewer.side_host.winfo_children():\n                child.destroy()\n        except Exception:\n            pass\n        self.tree = None\n        self.layer_docked = False\n        self.after(20, self.viewer.redraw)\n\n    def _show_layer_window(self):\n        # 메뉴에서 다시 표시할 때는 항상 내부 좌측 도킹 상태로 복원한다.\n        self._build_docked_layer_panel()\n\n'''
main = main[:start] + methods + main[end:]

# 기존 _layer_context_menu는 Toplevel 전용 parent를 쓰지 않고 현재 Treeview를 parent로 사용.
main = main.replace('menu = tk.Menu(self.layer_window, tearoff=False)', 'menu = tk.Menu(self.tree, tearoff=False)', 1)

main_path.write_text(main, encoding="utf-8")
print("v3.18 layout applied: true internal layer dock under full-width toolbar; drag detaches")
