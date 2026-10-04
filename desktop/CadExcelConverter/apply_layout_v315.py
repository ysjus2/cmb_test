from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v3.15 patch target not found: {label}")
    return text.replace(old, new, 1)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.14"', 'APP_NAME = "CMB DXF Viewer + Excel v3.15"', 1)

# v3.14의 좌측 고정 패널을 제거하고 Viewer 단독 본창 + 독립 레이어창 구조로 복원한다.
old_main_view = '''        # Viewer 중심 레이아웃: 좌측 레이어 고정 패널 + 우측 도면.\n        # 프로그램을 재시작해도 레이어 패널은 항상 표시한다.\n        self.panes = tk.PanedWindow(\n            root, orient="horizontal", sashwidth=6, sashrelief="raised",\n            showhandle=True, bd=0, relief="flat"\n        )\n        self.panes.pack(fill="both", expand=True)\n\n        self.layer_panel = ttk.LabelFrame(self.panes, text="레이어", padding=5)\n        self.panes.add(self.layer_panel, minsize=220, width=300, stretch="never")\n\n        self.tree = ttk.Treeview(\n            self.layer_panel,\n            columns=("check", "layer", "count", "types"),\n            show="headings",\n            selectmode="extended",\n        )\n        self.tree.heading("check", text="선택")\n        self.tree.heading("layer", text="레이어명")\n        self.tree.heading("count", text="객체수")\n        self.tree.heading("types", text="객체종류")\n        self.tree.column("check", width=50, anchor="center", stretch=False)\n        self.tree.column("layer", width=180)\n        self.tree.column("count", width=65, anchor="center", stretch=False)\n        self.tree.column("types", width=120)\n        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")\n        self.tree.bind("<Button-1>", self._tree_click)\n        self.tree.bind("<Button-3>", self._layer_context_menu)\n        layer_scroll = ttk.Scrollbar(self.layer_panel, orient="vertical", command=self.tree.yview)\n        self.tree.configure(yscrollcommand=layer_scroll.set)\n        self.tree.pack(side="left", fill="both", expand=True)\n        layer_scroll.pack(side="right", fill="y")\n\n        viewer_frame = ttk.Frame(self.panes)\n        self.panes.add(viewer_frame, minsize=600, stretch="always")\n        self.viewer = DXFViewer(viewer_frame)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n        self.after(120, self._set_fixed_layer_width)\n\n        status = ttk.Frame(root)\n'''
new_main_view = '''        # 본창은 Viewer를 최대 폭으로 사용하고 레이어는 별도 이동 가능한 창으로 표시한다.\n        self.viewer = DXFViewer(root)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n\n        status = ttk.Frame(root)\n'''
main = replace_once(main, old_main_view, new_main_view, "restore detached layer window")

# 고정 패널 전용 메서드는 더 이상 필요 없다.
main = main.replace('''    def _set_fixed_layer_width(self):\n        try:\n            self.panes.sash_place(0, 300, 0)\n        except Exception:\n            pass\n        self.after(20, self.viewer.redraw)\n\n''', '', 1)

# 파일 메뉴에 레이어 표시 항목을 복원한다.
menu_anchor = '''        file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")\n        file_menu.add_separator()\n        file_menu.add_command(label="종료", command=self.destroy)\n'''
menu_new = '''        file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")\n        file_menu.add_separator()\n        file_menu.add_command(label="레이어 표시", command=self._show_layer_window)\n        file_menu.add_separator()\n        file_menu.add_command(label="종료", command=self.destroy)\n'''
main = replace_once(main, menu_anchor, menu_new, "restore layer menu")

# 시작 시 레이어 독립창을 항상 좌측 기본 위치로 띄운다.
startup_anchor = '''        self._build_menu()\n        self._build_main_view()\n\n        self.bind("<F11>", lambda e: self._toggle_fullscreen())\n'''
startup_new = '''        self._build_menu()\n        self._build_main_view()\n        self._create_layer_window(show=True)\n        self.after(180, self._place_layer_window_left)\n\n        self.bind("<F11>", lambda e: self._toggle_fullscreen())\n'''
main = replace_once(main, startup_anchor, startup_new, "show layer window on startup")

# v3.14에서 컨텍스트 메뉴 parent를 self로 바꿨던 것을 독립 레이어창 기준으로 복원.
main = main.replace('menu = tk.Menu(self, tearoff=False)', 'menu = tk.Menu(self.layer_window, tearoff=False)', 1)

place_anchor = '''    def _epsg_changed(self):\n'''
place_method = '''    def _place_layer_window_left(self):\n        if self.layer_window is None or not self.layer_window.winfo_exists():\n            return\n        try:\n            self.update_idletasks()\n            x = max(0, self.winfo_x())\n            y = max(0, self.winfo_y() + 45)\n            h = max(520, self.winfo_height() - 90)\n            self.layer_window.geometry(f"430x{h}+{x}+{y}")\n            self.layer_window.deiconify()\n            self.layer_window.lift()\n        except Exception:\n            pass\n\n'''
main = replace_once(main, place_anchor, place_method + place_anchor, "layer initial position")

main_path.write_text(main, encoding="utf-8")

viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")

# 속성창 단일 인스턴스 상태 추가.
viewer = replace_once(
    viewer,
    '''        self.info_var = tk.StringVar(value="")\n        self._build()\n''',
    '''        self.info_var = tk.StringVar(value="")\n        self.details_window = None\n        self._build()\n''',
    "details window state",
)

# 객체 우클릭: 즉시 속성창 대신 메뉴 1개만 표시.
old_right = '''        # DXF 원본 객체는 우클릭 시 메뉴 없이 속성창만 즉시 표시한다.\n        # 삭제/전주정보/주소 메뉴는 표시하지 않는다.\n        self.show_details()\n'''
new_right = '''        # DXF 원본 객체는 우클릭 시 속성정보 메뉴만 제공한다.\n        # 삭제/전주정보/주소 메뉴는 제공하지 않는다.\n        menu = tk.Menu(self.canvas, tearoff=False)\n        menu.add_command(label="속성정보", command=self.show_details)\n        menu.tk_popup(event.x_root, event.y_root)\n'''
viewer = replace_once(viewer, old_right, new_right, "object context properties menu")

# 새 속성창을 열 때 기존 속성창은 자동으로 닫는다.
old_win = '''        win = tk.Toplevel(self)\n        win.title("선택 객체 상세정보")\n        win.geometry(f"{width}x{height}")\n        win.transient(self.winfo_toplevel())\n\n        frame = ttk.Frame(win, padding=8)\n'''
new_win = '''        if self.details_window is not None:\n            try:\n                if self.details_window.winfo_exists():\n                    self.details_window.destroy()\n            except Exception:\n                pass\n            self.details_window = None\n\n        win = tk.Toplevel(self)\n        self.details_window = win\n        win.title("선택 객체 상세정보")\n        win.geometry(f"{width}x{height}")\n        win.transient(self.winfo_toplevel())\n\n        def _close_details():\n            try:\n                win.destroy()\n            finally:\n                if self.details_window is win:\n                    self.details_window = None\n        win.protocol("WM_DELETE_WINDOW", _close_details)\n\n        frame = ttk.Frame(win, padding=8)\n'''
viewer = replace_once(viewer, old_win, new_win, "single details window")

viewer_path.write_text(viewer, encoding="utf-8")

print("v3.15 layout applied: floating layer window left on startup / properties context menu / single details window")
