from pathlib import Path
p=Path('viewer.py')
s=p.read_text(encoding='utf8')
assert "        self.scene = None\n" in s, 'Viewer patch marker missing'
s=s.replace("        self.scene = None\n","        self.scene = None\n        self.entity_filter = None\n        self.network_click = None\n        self.route_nodes = {}\n        self.route_start_marker = None\n",1)
assert "        for ent in self.scene.entities:\n            if ent.layer not in self.visible_layers:" in s, 'Viewer patch marker missing'
s=s.replace("        for ent in self.scene.entities:\n            if ent.layer not in self.visible_layers:","        for ent in self.scene.entities:\n            if self.entity_filter is not None and ent.index not in self.entity_filter:\n                continue\n            if ent.layer not in self.visible_layers:",1)
assert "if e.layer in self.visible_layers and e.bbox is not None" in s, 'Viewer patch marker missing'
s=s.replace("if e.layer in self.visible_layers and e.bbox is not None","if e.layer in self.visible_layers and e.bbox is not None and (self.entity_filter is None or e.index in self.entity_filter)",1)
assert "    def _left_click(self, event):\n" in s, 'Viewer patch marker missing'
s=s.replace("    def _left_click(self, event):\n","    def _left_click(self, event):\n        if self.network_click is not None:\n            self.network_click(event)\n            return\n",1)
assert "    def handle_escape(self, event=None):\n" in s, 'Viewer patch marker missing'
s=s.replace("    def handle_escape(self, event=None):\n","    def handle_escape(self, event=None):\n        if self.network_click is not None:\n            self.winfo_toplevel()._reset_network_filter()\n            return \"break\"\n",1)
assert "        self._redraw_measure()\n" in s, 'Viewer patch marker missing'
s=s.replace("        self._redraw_measure()\n","        self._redraw_measure()\n        if self.network_click is not None:\n            for point in self.route_nodes.values():\n                sx, sy = self.world_to_screen(*point)\n                self.canvas.create_oval(sx-3, sy-3, sx+3, sy+3, fill=\"#00ffff\", outline=\"#003a46\")\n            if self.route_start_marker:\n                sx, sy = self.world_to_screen(*self.route_start_marker)\n                self.canvas.create_oval(sx-7, sy-7, sx+7, sy+7, outline=\"#54ff54\", width=3)\n",1)
p.write_text(s,encoding='utf8')
p=Path('main.py')
s=p.read_text(encoding='utf8')
assert "from viewer import DXFViewer, build_scene" in s, 'Main patch marker missing'
s=s.replace("from viewer import DXFViewer, build_scene","from viewer import DXFViewer, build_scene\nfrom network_extract_ui import NetworkExtractionMixin",1)
assert "class App(tk.Tk):" in s, 'Main patch marker missing'
s=s.replace("class App(tk.Tk):","class App(NetworkExtractionMixin, tk.Tk):",1)
assert "        # Viewer 자체가 전체 폭을 차지한다." in s, 'Main patch marker missing'
s=s.replace("        # Viewer 자체가 전체 폭을 차지한다.","        self._build_extract_toolbar(root)\n\n        # Viewer 자체가 전체 폭을 차지한다.",1)
assert "    def _run_excel(self):\n" in s, 'Main patch marker missing'
s=s.replace("    def _run_excel(self):\n","    def _run_excel(self):\n        if self.export_scope is not None:\n            return self._run_network_excel()\n",1)
assert "        self.busy = True\n        self.status_var.set(\"DXF 분석 중...\")" in s, 'Main patch marker missing'
s=s.replace("        self.busy = True\n        self.status_var.set(\"DXF 분석 중...\")","        self._clear_network_state()\n        self.busy = True\n        self.status_var.set(\"DXF 분석 중...\")",1)
s=s.replace('v3.23','v3.24')
p.write_text(s,encoding='utf8')
print('v3.24 network extraction UI applied')

p=Path("main.py")
s=p.read_text(encoding="utf8")
assert "    def _run_excel(self):\n        if self.export_scope is not None:\n            return self._run_network_excel()\n" in s
s=s.replace("    def _run_excel(self):\n        if self.export_scope is not None:\n            return self._run_network_excel()\n","    def _run_excel(self):\n        if self.export_scope is not None:\n            return self._run_network_excel()\n        messagebox.showinfo(APP_NAME, \"먼저 광주간선 추출 또는 100mm 주관로 추출로 대상을 선택해주세요. 전체 레이어 출력은 파일 메뉴의 기존 방식을 사용하세요.\")\n\n    def _run_all_layer_excel(self):\n",1)
s=s.replace("        file_menu.add_separator()","        file_menu.add_command(label=\"전체 레이어 Excel (기존 방식)\", command=self._run_all_layer_excel)\n        file_menu.add_separator()",1)
p.write_text(s,encoding="utf8")
