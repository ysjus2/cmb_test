from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import convert_selected_layers, scan_layers
from viewer import DXFViewer, build_scene

APP_NAME = "CMB DXF Viewer + Excel v3.4"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1450x900")
        self.minsize(1100, 700)

        self.q = queue.Queue()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.epsg_var = tk.StringVar(value="5174")
        self.status_var = tk.StringVar(value="DXF 파일을 선택해주세요.")
        self.progress_value = 0
        self.progress_text = "0% · 준비"

        self.layer_names = {}
        self.layer_rows = {}
        self.checked_layers = set()
        self.visible_layers = set()
        self.last_checked_iid = None
        self.highlighted_iids = set()
        self.layer_panel_visible = True
        self.fullscreen = False

        self._build()
        self.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.bind("<Escape>", self._escape_key)
        self.after(100, self._drain)

    def _build(self):
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        title = ttk.Frame(root)
        title.pack(fill="x")
        ttk.Label(title, text=APP_NAME, font=("Malgun Gothic", 19, "bold")).pack(side="left")
        ttk.Label(
            title,
            text="DXF 전용 · 읽기 전용 Viewer · 로컬 처리 · 원본 수정 없음",
            foreground="#126b3a",
        ).pack(side="right")

        form = ttk.Frame(root)
        form.pack(fill="x", pady=(8, 6))
        ttk.Label(form, text="DXF 파일").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(form, textvariable=self.input_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(form, text="열기", command=self._pick_input).grid(row=0, column=2, padx=6)

        ttk.Label(form, text="Excel 출력").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(5, 0))
        ttk.Entry(form, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", pady=(5, 0))
        ttk.Button(form, text="찾기", command=self._pick_output).grid(row=1, column=2, padx=6, pady=(5, 0))

        ttk.Label(form, text="EPSG").grid(row=0, column=3, padx=(10, 4))
        self.epsg_combo = ttk.Combobox(
            form, textvariable=self.epsg_var,
            values=["5174", "2097", "5181", "5179", "5186"],
            width=10,
        )
        self.epsg_combo.grid(row=0, column=4)
        self.epsg_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.viewer.set_source_epsg(self.epsg_var.get())
        )
        form.columnconfigure(1, weight=1)

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", pady=(2, 6))
        self.scan_btn = ttk.Button(toolbar, text="DXF 다시 읽기", command=self._scan)
        self.scan_btn.pack(side="left")
        ttk.Button(toolbar, text="추출 전체 선택", command=self._select_all).pack(side="left", padx=(6, 2))
        ttk.Button(toolbar, text="추출 선택 해제", command=self._clear_selection).pack(side="left", padx=2)
        self.layer_toggle_btn = ttk.Button(toolbar, text="레이어 창 접기", command=self._toggle_layer_panel)
        self.layer_toggle_btn.pack(side="left", padx=(10, 2))
        ttk.Button(toolbar, text="전체 화면(F11)", command=self._toggle_fullscreen).pack(side="left", padx=2)
        self.run_btn = ttk.Button(toolbar, text="선택 레이어 Excel 생성", command=self._run, state="disabled")
        self.run_btn.pack(side="left", padx=(12, 2))
        ttk.Label(toolbar, textvariable=self.status_var).pack(side="right")

        self.panes = tk.PanedWindow(
            root,
            orient="horizontal",
            sashwidth=8,
            sashrelief="raised",
            showhandle=True,
            bg="#9ca3af",
            bd=0,
            relief="flat",
        )
        self.panes.pack(fill="both", expand=True)

        self.left_panel = ttk.LabelFrame(self.panes, text="레이어", padding=6)
        left = self.left_panel
        self.panes.add(left, minsize=220, stretch="always")

        self.tree = ttk.Treeview(
            left,
            columns=("check", "layer", "count", "types"),
            show="headings",
            selectmode="extended",
            height=28,
        )
        self.tree.heading("check", text="선택")
        self.tree.heading("layer", text="레이어명")
        self.tree.heading("count", text="객체수")
        self.tree.heading("types", text="객체종류")
        self.tree.column("check", width=55, anchor="center", stretch=False)
        self.tree.column("layer", width=260)
        self.tree.column("count", width=75, anchor="center")
        self.tree.column("types", width=250)
        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")
        self.tree.bind("<Button-1>", self._tree_click)

        y = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        self.right_panel = ttk.Frame(self.panes)
        right = self.right_panel
        self.panes.add(right, minsize=500, stretch="always")
        self.viewer = DXFViewer(right)
        self.viewer.pack(fill="both", expand=True)
        self.viewer.set_source_epsg(self.epsg_var.get())

        progress_frame = ttk.Frame(root)
        progress_frame.pack(fill="x", pady=(6, 4))
        self.progress_canvas = tk.Canvas(
            progress_frame, height=30, highlightthickness=1,
            highlightbackground="#9ca3af", bg="#e5e7eb"
        )
        self.progress_canvas.pack(fill="x")
        self.progress_canvas.bind("<Configure>", lambda e: self._draw_progress())

        self.log = tk.Text(root, height=5, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="x")
        self._log("회사 배포용: DXF만 지원 / DWG 엔진 없음 / Viewer는 원본 파일을 수정하지 않습니다.")

    def _toggle_layer_panel(self):
        if self.layer_panel_visible:
            try:
                self.panes.forget(self.left_panel)
            except Exception:
                pass
            self.layer_panel_visible = False
            self.layer_toggle_btn.config(text="레이어 창 펼치기")
        else:
            try:
                self.panes.forget(self.right_panel)
            except Exception:
                pass
            self.panes.add(self.left_panel, minsize=220, stretch="always")
            self.panes.add(self.right_panel, minsize=500, stretch="always")
            self.layer_panel_visible = True
            self.layer_toggle_btn.config(text="레이어 창 접기")
        self.after(30, self.viewer.redraw)

    def _toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)
        self.after(50, self.viewer.redraw)

    def _escape_key(self, event=None):
        if self.fullscreen:
            self.fullscreen = False
            self.attributes("-fullscreen", False)
            self.after(50, self.viewer.redraw)
        else:
            self.viewer.clear_selection()

    def _pick_input(self):
        p = filedialog.askopenfilename(
            filetypes=[("DXF 파일", "*.dxf"), ("모든 파일", "*.*")]
        )
        if p:
            if Path(p).suffix.lower() != ".dxf":
                messagebox.showerror(APP_NAME, "회사용 최종판은 DXF 파일만 열 수 있습니다.")
                return
            self.input_var.set(p)
            self.output_var.set(str(Path(p).with_suffix("")) + "_레이어별.xlsx")
            self._scan()

    def _pick_output(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if p:
            self.output_var.set(p)

    def _scan(self):
        inp = self.input_var.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "DXF 파일을 선택해주세요.")
            return
        if Path(inp).suffix.lower() != ".dxf":
            messagebox.showerror(APP_NAME, "DXF 파일만 지원합니다.")
            return

        self.scan_btn.config(state="disabled")
        self.run_btn.config(state="disabled")
        self.status_var.set("DXF 분석 중...")
        self._set_progress(0, "DXF 분석 준비")
        self.tree.delete(*self.tree.get_children())
        self.layer_names.clear()
        self.layer_rows.clear()
        self.checked_layers.clear()
        self.visible_layers.clear()
        self.last_checked_iid = None
        self.highlighted_iids.clear()

        def worker():
            try:
                layers = scan_layers(
                    inp,
                    None,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda p, t: self.q.put(("progress", (int(p * 0.45), t))),
                )
                scene = build_scene(
                    inp,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda p, t: self.q.put(("progress", (45 + int(p * 0.55), t))),
                )
                self.q.put(("loaded", (layers, scene)))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _row_values(self, iid):
        name, count, types = self.layer_rows[iid]
        return (
            "☑" if name in self.checked_layers else "☐",
            name, count, types
        )

    def _refresh_row(self, iid):
        if iid in self.layer_rows:
            self.tree.item(iid, values=self._row_values(iid))

    def _set_checked(self, iid, checked):
        row = self.layer_rows.get(iid)
        if not row:
            return
        name = row[0]
        if checked:
            self.checked_layers.add(name)
            self.visible_layers.add(name)
        else:
            self.checked_layers.discard(name)
            self.visible_layers.discard(name)
        self._refresh_row(iid)
        self.viewer.set_visible_layers(self.visible_layers)
        self._update_status()

    def _update_status(self):
        self.status_var.set(
            f"레이어 {len(self.layer_rows)}개 · 선택/표시/추출 {len(self.checked_layers)}개"
        )

    def _highlight_items(self, items):
        for old_iid in list(self.highlighted_iids):
            if self.tree.exists(old_iid):
                self.tree.item(old_iid, tags=())
        self.highlighted_iids = set(items)
        for item in items:
            if self.tree.exists(item):
                self.tree.item(item, tags=("range_selected",))
        if items:
            self.tree.see(items[-1])

    def _tree_click(self, event):
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid:
            return "break"

        items = list(self.tree.get_children())
        shift_pressed = bool(event.state & 0x0001)

        # v2.2 CAD식 범위 선택: 일반 클릭 기준점, Shift 클릭 연속 파란 범위.
        if shift_pressed and self.last_checked_iid in items:
            start = items.index(self.last_checked_iid)
            end = items.index(iid)
            lo, hi = sorted((start, end))
            range_items = items[lo:hi + 1]
            self._highlight_items(range_items)

            # Shift+체크 클릭: 클릭 항목 상태 기준으로 범위 전체 일괄 체크/해제.
            # 체크 상태는 Viewer 표시 여부와 Excel 추출 대상을 동시에 결정한다.
            if col == "#1":
                clicked_name = self.layer_names.get(iid)
                target = clicked_name not in self.checked_layers
                for item in range_items:
                    self._set_checked(item, target)

            self.last_checked_iid = iid
            return "break"

        # 파란 선택 범위 안 체크 클릭: 선택 그룹 전체 일괄 체크/해제.
        if col == "#1":
            if iid in self.highlighted_iids and self.highlighted_iids:
                targets = [item for item in items if item in self.highlighted_iids]
            else:
                targets = [iid]
                self._highlight_items(targets)
                self.last_checked_iid = iid

            clicked_name = self.layer_names.get(iid)
            target = clicked_name not in self.checked_layers
            for item in targets:
                self._set_checked(item, target)
            return "break"

        # 일반 행 클릭: 기존 파란 선택을 지우고 클릭 행 하나를 즉시 파란색으로.
        self._highlight_items([iid])
        self.last_checked_iid = iid
        return "break"

    def _select_all(self):
        items = list(self.tree.get_children())
        for iid in items:
            self._set_checked(iid, True)
        self._highlight_items(items)

    def _clear_selection(self):
        for iid in self.tree.get_children():
            self._set_checked(iid, False)
        self._highlight_items([])
        self.last_checked_iid = None

    def _run(self):
        selected = [
            self.layer_names[iid]
            for iid in self.tree.get_children()
            if self.layer_names.get(iid) in self.checked_layers
        ]
        if not selected:
            messagebox.showerror(APP_NAME, "Excel로 추출할 레이어를 선택해주세요.")
            return
        out = self.output_var.get().strip()
        if not out:
            messagebox.showerror(APP_NAME, "출력 Excel 경로를 지정해주세요.")
            return
        try:
            epsg = int(self.epsg_var.get().strip())
        except ValueError:
            messagebox.showerror(APP_NAME, "EPSG 번호를 확인해주세요.")
            return

        self.run_btn.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self._set_progress(0, "Excel 변환 준비")
        self._log("=" * 60)
        self._log("Excel 추출 레이어: " + ", ".join(selected))

        def worker():
            try:
                stats = convert_selected_layers(
                    self.input_var.get().strip(),
                    out, selected, epsg, None,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda p, t: self.q.put(("progress", (p, t))),
                )
                self.q.put(("done", stats))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "progress":
                    self._set_progress(data[0], data[1])
                elif kind == "loaded":
                    layers, scene = data
                    for i, layer in enumerate(layers):
                        iid = f"L{i}"
                        self.layer_names[iid] = layer.name
                        self.layer_rows[iid] = (layer.name, layer.count, layer.types)
                        self.visible_layers.add(layer.name)
                        self.checked_layers.add(layer.name)
                        self.tree.insert("", "end", iid=iid, values=self._row_values(iid))
                    self.viewer.set_source_epsg(self.epsg_var.get())
                    self.viewer.load_scene(scene)
                    self.viewer.set_visible_layers(self.visible_layers)
                    self.scan_btn.config(state="normal")
                    self.run_btn.config(state="normal" if layers else "disabled")
                    self._update_status()
                    self._set_progress(100, f"DXF Viewer 준비 완료 · 객체 {len(scene.entities):,}개")
                    if scene.unsupported:
                        text = ", ".join(f"{k}:{v}" for k, v in sorted(scene.unsupported.items()))
                        self._log("Viewer 미표시 객체: " + text)
                elif kind == "done":
                    self.scan_btn.config(state="normal")
                    self.run_btn.config(state="normal")
                    self._set_progress(100, "Excel 생성 완료")
                    self._log(f"완료 · 레이어 {data.layers} · 객체 {data.entities} · 행 {data.rows}")
                    messagebox.showinfo(APP_NAME, "선택 레이어 Excel 생성이 완료되었습니다.")
                elif kind == "error":
                    self.scan_btn.config(state="normal")
                    self.run_btn.config(state="normal" if self.layer_names else "disabled")
                    self._set_progress(self.progress_value, "오류 발생")
                    self._log("오류: " + data)
                    messagebox.showerror(APP_NAME, data)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _set_progress(self, percent, task):
        try:
            value = max(0, min(100, int(percent)))
        except Exception:
            value = 0
        self.progress_value = value
        self.progress_text = f"{value}% · {task}"
        self._draw_progress()

    def _draw_progress(self):
        if not hasattr(self, "progress_canvas"):
            return
        c = self.progress_canvas
        c.delete("all")
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        fill = int(w * self.progress_value / 100.0)
        c.create_rectangle(0, 0, w, h, fill="#e5e7eb", outline="")
        if fill > 0:
            c.create_rectangle(0, 0, fill, h, fill="#2563eb", outline="")
        c.create_text(
            w // 2, h // 2, text=self.progress_text,
            fill="white" if self.progress_value >= 45 else "#111827",
            font=("Malgun Gothic", 10, "bold"),
        )

    def _log(self, msg):
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")

if __name__ == "__main__":
    App().mainloop()
