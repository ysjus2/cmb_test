from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v3.14 patch target not found: {label}")
    return text.replace(old, new, 1)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.13"', 'APP_NAME = "CMB DXF Viewer + Excel v3.14"', 1)

main = replace_once(
    main,
    '''        self._build_menu()\n        self._build_main_view()\n        self._create_layer_window(show=False)\n''',
    '''        self._build_menu()\n        self._build_main_view()\n''',
    "remove detached layer window startup",
)

main = main.replace(
    '''        file_menu.add_separator()\n        file_menu.add_command(label="레이어 표시", command=self._show_layer_window)\n''',
    '',
    1,
)

old_main_view = '''        self.viewer = DXFViewer(root)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n\n        status = ttk.Frame(root)\n'''
new_main_view = '''        # Viewer 중심 레이아웃: 좌측 레이어 고정 패널 + 우측 도면.\n        # 프로그램을 재시작해도 레이어 패널은 항상 표시한다.\n        self.panes = tk.PanedWindow(\n            root, orient="horizontal", sashwidth=6, sashrelief="raised",\n            showhandle=True, bd=0, relief="flat"\n        )\n        self.panes.pack(fill="both", expand=True)\n\n        self.layer_panel = ttk.LabelFrame(self.panes, text="레이어", padding=5)\n        self.panes.add(self.layer_panel, minsize=220, width=300, stretch="never")\n\n        self.tree = ttk.Treeview(\n            self.layer_panel,\n            columns=("check", "layer", "count", "types"),\n            show="headings",\n            selectmode="extended",\n        )\n        self.tree.heading("check", text="선택")\n        self.tree.heading("layer", text="레이어명")\n        self.tree.heading("count", text="객체수")\n        self.tree.heading("types", text="객체종류")\n        self.tree.column("check", width=50, anchor="center", stretch=False)\n        self.tree.column("layer", width=180)\n        self.tree.column("count", width=65, anchor="center", stretch=False)\n        self.tree.column("types", width=120)\n        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")\n        self.tree.bind("<Button-1>", self._tree_click)\n        self.tree.bind("<Button-3>", self._layer_context_menu)\n        layer_scroll = ttk.Scrollbar(self.layer_panel, orient="vertical", command=self.tree.yview)\n        self.tree.configure(yscrollcommand=layer_scroll.set)\n        self.tree.pack(side="left", fill="both", expand=True)\n        layer_scroll.pack(side="right", fill="y")\n\n        viewer_frame = ttk.Frame(self.panes)\n        self.panes.add(viewer_frame, minsize=600, stretch="always")\n        self.viewer = DXFViewer(viewer_frame)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n        self.after(120, self._set_fixed_layer_width)\n\n        status = ttk.Frame(root)\n'''
main = replace_once(main, old_main_view, new_main_view, "fixed layer main view")

# Context menu parent must work without detached layer window.
main = main.replace('menu = tk.Menu(self.layer_window, tearoff=False)', 'menu = tk.Menu(self, tearoff=False)', 1)

# Add stable initial layer width method before EPSG handler.
anchor = '''    def _epsg_changed(self):\n'''
method = '''    def _set_fixed_layer_width(self):\n        try:\n            self.panes.sash_place(0, 300, 0)\n        except Exception:\n            pass\n        self.after(20, self.viewer.redraw)\n\n'''
main = replace_once(main, anchor, method + anchor, "fixed layer width method")

main_path.write_text(main, encoding="utf-8")

viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")
old_object_menu = '''        menu = tk.Menu(self.canvas, tearoff=False)\n        menu.add_command(label="속성", command=self.show_details)\n        menu.add_command(label="전주정보", command=self.show_pole_info)\n        menu.add_command(label="주소", command=self.show_address_info)\n        menu.tk_popup(event.x_root, event.y_root)\n'''
new_object_menu = '''        # DXF 원본 객체는 우클릭 시 메뉴 없이 속성창만 즉시 표시한다.\n        # 삭제/전주정보/주소 메뉴는 표시하지 않는다.\n        self.show_details()\n'''
viewer = replace_once(viewer, old_object_menu, new_object_menu, "object right click properties only")
viewer_path.write_text(viewer, encoding="utf-8")

print("v3.14 layout applied: fixed left layer panel / object right-click properties only")
