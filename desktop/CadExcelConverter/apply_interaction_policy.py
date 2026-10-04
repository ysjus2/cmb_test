from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"interaction patch target not found: {label}")
    return text.replace(old, new, 1)


viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")
viewer = replace_once(
    viewer,
    "import math\nimport tkinter as tk\n",
    "import math\nimport re\nimport tkinter as tk\n",
    "re import",
)
viewer = replace_once(
    viewer,
    '''        self.completed_measurements = []\n        self.hover_world = None\n''',
    '''        self.completed_measurements = []\n        self.selected_measurement = None\n        self.hover_world = None\n        self._right_dragged = False\n        self._right_press_xy = None\n''',
    "interaction state",
)
viewer = replace_once(
    viewer,
    '''        self.canvas.bind("<ButtonPress-3>", self._pan_start)\n        self.canvas.bind("<B3-Motion>", self._pan_move)\n        self.canvas.bind("<ButtonRelease-3>", self._pan_end)\n''',
    '''        # 우클릭 짧게=컨텍스트 메뉴, 우클릭 드래그=기존 PAN.\n        self.canvas.bind("<ButtonPress-3>", self._right_press)\n        self.canvas.bind("<B3-Motion>", self._right_move)\n        self.canvas.bind("<ButtonRelease-3>", self._right_release)\n''',
    "right click bindings",
)
viewer = replace_once(
    viewer,
    '''        self.bind_all("<Escape>", lambda e: self.clear_selection())\n        self.bind_all("<Return>", lambda e: self._finish_measurement())\n''',
    '''        self.bind_all("<Escape>", self.handle_escape)\n        # 거리 측정 완료는 ESC를 사용한다. Enter는 더 이상 측정 종료 키로 사용하지 않는다.\n''',
    "escape binding",
)
viewer = replace_once(
    viewer,
    '''        self.completed_measurements = []\n        self.fit_view()\n''',
    '''        self.completed_measurements = []\n        self.selected_measurement = None\n        self.fit_view()\n''',
    "load scene measurement selection reset",
)
viewer = replace_once(
    viewer,
    '''            self.info_var.set(\n                "지점을 계속 클릭하세요. 구간/누적 거리가 표시됩니다. 더블클릭 또는 Enter로 완료합니다."\n            )\n''',
    '''            self.info_var.set(\n                "지점을 계속 클릭하세요. 구간/누적 거리가 표시됩니다. ESC로 현재 마지막 지점까지 측정을 완료합니다."\n            )\n''',
    "distance help",
)

pole_anchor = '''_POLE_KEYWORDS = (\n    "전주", "전주번호", "전주명", "주번호", "지지물",\n    "pole", "pole_no", "poleno", "poleid", "pole_id"\n)\n'''
pole_replacement = pole_anchor + '''\n_POLE_CODE_RE = re.compile(r"(?<![0-9A-Za-z])\\d{4}[Xx]\\d{3}(?![0-9A-Za-z])")\n_ADDRESS_KEYWORDS = (\n    "주소", "도로명", "지번", "address", "addr", "road", "jibun",\n)\n\ndef _extract_address_info(entity):\n    found = {}\n\n    def add(key, value):\n        k = str(key or "").strip()\n        v = str(value or "").strip()\n        if not v:\n            return\n        blob = (k + " " + v).lower()\n        if any(word.lower() in blob for word in _ADDRESS_KEYWORDS):\n            found[k or "주소"] = v\n\n    for key, value in (entity.attributes or {}).items():\n        add(key, value)\n    for appid, values in (entity.xdata or []):\n        for value in values:\n            add(appid, value)\n    for key, value in (entity.dxf_data or {}).items():\n        add(key, value)\n    add("TEXT", entity.text)\n    return found\n'''
viewer = replace_once(viewer, pole_anchor, pole_replacement, "pole/address helpers")
viewer = replace_once(
    viewer,
    '''    if block_name:\n        check_pair("BLOCK", block_name)\n\n    return found\n''',
    '''    if block_name:\n        check_pair("BLOCK", block_name)\n\n    # 현장 전주번호가 0000X000 형태로만 저장된 경우 키워드가 없어도 직접 인식한다.\n    blobs = []\n    blobs.extend(str(v) for v in (attributes or {}).values())\n    for appid, values in (xdata or []):\n        blobs.append(str(appid))\n        blobs.extend(str(v) for v in values)\n    blobs.extend(str(v) for v in (dxf_data or {}).values())\n    blobs.extend([str(text or ""), str(block_name or "")])\n    for blob in blobs:\n        for match in _POLE_CODE_RE.findall(blob):\n            found.setdefault("전주번호", match.upper())\n\n    return found\n''',
    "pole code regex",
)

methods_anchor = '''    def _left_click(self, event):\n'''
methods = r'''    @staticmethod
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
        menu = tk.Menu(self.canvas, tearoff=False)
        menu.add_command(label="속성", command=self.show_details)
        menu.add_command(label="전주정보", command=self.show_pole_info)
        menu.add_command(label="주소", command=self.show_address_info)
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

'''
viewer = replace_once(viewer, methods_anchor, methods + methods_anchor, "context and escape methods")

viewer = replace_once(
    viewer,
    '''        idx = self._nearest_entity(event.x, event.y)\n        shift = bool(event.state & 0x0001)\n''',
    '''        measurement_idx = self._nearest_measurement(event.x, event.y)\n        if measurement_idx is not None:\n            self.selected_measurement = measurement_idx\n            self.selected.clear()\n            m = self.completed_measurements[measurement_idx]\n            self.info_var.set(f'측정거리: {m.get("value", 0.0):,.3f} · 우클릭하면 삭제할 수 있습니다.')\n            self.redraw()\n            return\n        self.selected_measurement = None\n        idx = self._nearest_entity(event.x, event.y)\n        shift = bool(event.state & 0x0001)\n''',
    "measurement left selection",
)
viewer = replace_once(
    viewer,
    '''        self.completed_measurements.append({\n                "type": "distance_path",\n''',
    '''        self.completed_measurements.append({\n                "type": "distance_path",\n''',
    "measurement completion anchor",
)
viewer = replace_once(
    viewer,
    '''        self.completed_measurements = []\n        self.info_var.set("")\n''',
    '''        self.completed_measurements = []\n        self.selected_measurement = None\n        self.info_var.set("")\n''',
    "clear measure selection",
)
viewer = replace_once(
    viewer,
    '''        for m in self.completed_measurements:\n            pts = m.get("points", [])\n''',
    '''        for measurement_index, m in enumerate(self.completed_measurements):\n            pts = m.get("points", [])\n''',
    "enumerate measurements",
)
viewer = replace_once(
    viewer,
    '''            self._draw_measure_polyline(\n                pts,\n                color="#ffd43b",\n                close=m.get("type") == "area",\n                width=2,\n            )\n''',
    '''            is_selected_measurement = measurement_index == self.selected_measurement\n            self._draw_measure_polyline(\n                pts,\n                color="#ff8c00" if is_selected_measurement else "#ffd43b",\n                close=m.get("type") == "area",\n                width=4 if is_selected_measurement else 2,\n            )\n''',
    "measurement selection highlight",
)
viewer_path.write_text(viewer, encoding="utf-8")

main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.12"', 'APP_NAME = "CMB DXF Viewer + Excel v3.13"', 1)
main = replace_once(
    main,
    '''        else:\n            self.viewer.clear_selection()\n\n    def _pick_input(self):\n''',
    '''        else:\n            self.viewer.handle_escape()\n\n    def _pick_input(self):\n''',
    "main escape routing",
)
main_path.write_text(main, encoding="utf-8")

print("Interaction policy applied: v3.13 / object context / pole-address / ESC distance / measurement delete")
