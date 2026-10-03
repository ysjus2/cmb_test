from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import scan_layers, convert_selected_layers

APP_NAME = "CAD → Excel 레이어 변환기 v2.1"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1050x760")
        self.minsize(920, 650)
        self.q = queue.Queue()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.epsg_var = tk.StringVar(value="5174")
        self.status_var = tk.StringVar(value="CAD 파일을 선택해주세요.")
        self.progress_value = 0
        self.progress_text = "0% · 준비"
        self.layer_names = {}
        self.layer_rows = {}
        self.checked_layers = set()
        self.last_checked_iid = None
        self.highlighted_iids = set()
        self._build()
        self.after(100, self._drain)

    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="CAD → Excel 레이어 변환기 v2.1",
            font=("Malgun Gothic", 20, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text="AI/서버 전송 없음 · CAD를 열고 필요한 레이어만 선택하여 레이어별 Excel 시트로 저장",
            foreground="#126b3a",
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.Frame(root)
        form.pack(fill="x")
        self._row(form, 0, "CAD 파일", self.input_var, self._pick_input)
        self._row(form, 1, "출력 Excel", self.output_var, self._pick_output)

        ttk.Label(form, text="원본 좌표계").grid(
            row=2, column=0, sticky="w", padx=(0,8), pady=6
        )
        ttk.Combobox(
            form,
            textvariable=self.epsg_var,
            values=["5174","2097","5181","5179","5186"],
            width=18,
        ).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(
            form,
            text="현재 샘플 CAD 기준 EPSG:5174",
        ).grid(row=2, column=2, sticky="w", padx=8)

        form.columnconfigure(1, weight=1)

        topbar = ttk.Frame(root)
        topbar.pack(fill="x", pady=(10,6))
        self.scan_btn = ttk.Button(topbar, text="1. 레이어 읽기", command=self._scan)
        self.scan_btn.pack(side="left")
        ttk.Button(topbar, text="전체 선택", command=self._select_all).pack(side="left", padx=6)
        ttk.Button(topbar, text="선택 해제", command=self._clear_selection).pack(side="left")
        ttk.Label(topbar, textvariable=self.status_var).pack(side="right")

        layer_box = ttk.LabelFrame(root, text="CAD 레이어 선택", padding=8)
        layer_box.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            layer_box,
            columns=("check","layer","count","types"),
            show="headings",
            selectmode="extended",
            height=18,
        )
        self.tree.heading("check", text="선택")
        self.tree.heading("layer", text="레이어명")
        self.tree.heading("count", text="객체수")
        self.tree.heading("types", text="객체종류")
        self.tree.column("check", width=60, anchor="center", stretch=False)
        self.tree.column("layer", width=350, stretch=True)
        self.tree.column("count", width=90, anchor="center")
        self.tree.column("types", width=400, stretch=True)
        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")
        self.tree.bind("<Button-1>", self._tree_click)
        y = ttk.Scrollbar(layer_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        bottombar = ttk.Frame(root)
        bottombar.pack(fill="x", pady=10)
        self.run_btn = ttk.Button(
            bottombar,
            text="2. 선택 레이어 Excel 생성",
            command=self._run,
            state="disabled",
        )
        self.run_btn.pack(side="left")
        ttk.Button(
            bottombar,
            text="출력 폴더 열기",
            command=self._open_output,
        ).pack(side="left", padx=8)

        progress_frame = ttk.Frame(root)
        progress_frame.pack(fill="x", pady=(2, 8))
        self.progress_canvas = tk.Canvas(
            progress_frame,
            height=34,
            highlightthickness=1,
            highlightbackground="#9ca3af",
            bg="#e5e7eb",
        )
        self.progress_canvas.pack(fill="x")
        self.progress_canvas.bind("<Configure>", lambda e: self._draw_progress())

        self.log = tk.Text(root, height=9, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="x")
        self._log("DXF는 직접 읽습니다. DWG는 내장 변환 엔진으로 자동 변환합니다.")

    def _row(self, parent, row, label, var, command, optional=False):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0,8), pady=6
        )
        ttk.Entry(parent, textvariable=var).grid(
            row=row, column=1, sticky="ew", pady=6
        )
        ttk.Button(parent, text="찾기", command=command).grid(
            row=row, column=2, padx=(8,0), pady=6
        )
        if optional:
            ttk.Label(parent, text="(DWG일 때만 필요)").grid(
                row=row, column=3, sticky="w", padx=6
            )

    def _pick_input(self):
        p = filedialog.askopenfilename(
            filetypes=[
                ("CAD 파일","*.dwg *.dxf"),
                ("DWG","*.dwg"),
                ("DXF","*.dxf"),
                ("모든 파일","*.*"),
            ]
        )
        if p:
            self.input_var.set(p)
            self.output_var.set(str(Path(p).with_suffix("")) + "_레이어별.xlsx")
            self._scan()

    def _pick_output(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel","*.xlsx")],
        )
        if p:
            self.output_var.set(p)

    def _scan(self):
        inp = self.input_var.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "CAD 파일을 선택해주세요.")
            return
        self.scan_btn.config(state="disabled")
        self.run_btn.config(state="disabled")
        self.status_var.set("레이어 분석 중...")
        self._set_progress(0, "레이어 분석 준비")
        self.tree.delete(*self.tree.get_children())
        self.layer_names.clear()
        self.layer_rows.clear()
        self.checked_layers.clear()
        self.last_checked_iid = None
        self.highlighted_iids.clear()

        def worker():
            try:
                layers = scan_layers(
                    inp,
                    None,
                    log=lambda m: self.q.put(("log",m)),
                    progress=lambda p,t: self.q.put(("progress",(p,t))),
                )
                self.q.put(("layers",layers))
            except Exception as e:
                self.q.put(("error",str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _set_checked(self, iid, checked):
        row = self.layer_rows.get(iid)
        if not row:
            return
        name, count, types = row
        if checked:
            self.checked_layers.add(name)
        else:
            self.checked_layers.discard(name)
        self.tree.item(
            iid,
            values=("☑" if checked else "☐", name, count, types),
        )
        self.status_var.set(
            f"레이어 {len(self.layer_rows)}개 발견 · {len(self.checked_layers)}개 선택"
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

        # 1) Shift 선택: 체크와 무관하게 시작~끝을 파란 선택 상태로만 만든다.
        #    Shift 키를 놓아도 이 선택 상태는 계속 유지된다.
        if shift_pressed and self.last_checked_iid in items:
            start = items.index(self.last_checked_iid)
            end = items.index(iid)
            lo, hi = sorted((start, end))
            range_items = items[lo:hi + 1]
            self._highlight_items(range_items)

            # Shift+체크박스 클릭이면 방금 선택한 범위 전체를
            # 클릭한 항목의 현재 체크 상태 기준으로 일괄 체크/해제한다.
            if col == "#1":
                clicked_name = self.layer_names.get(iid)
                target_checked = clicked_name not in self.checked_layers
                for item in range_items:
                    self._set_checked(item, target_checked)

            # CAD처럼 기준점은 마지막 클릭 위치로 이동하지만
            # 파란 선택 상태는 그대로 유지한다.
            self.last_checked_iid = iid
            return "break"

        # 2) 체크박스 클릭:
        #    클릭한 행이 현재 파란 선택 안에 있으면 파란 선택 전체에 적용.
        #    클릭한 행이 선택 밖이면 그 행 하나만 새 선택으로 만들고 적용.
        if col == "#1":
            if iid in self.highlighted_iids and self.highlighted_iids:
                target_items = [item for item in items if item in self.highlighted_iids]
            else:
                target_items = [iid]
                self._highlight_items(target_items)
                self.last_checked_iid = iid

            clicked_name = self.layer_names.get(iid)
            target_checked = clicked_name not in self.checked_layers
            for item in target_items:
                self._set_checked(item, target_checked)

            # 체크/해제 후에도 파란 선택은 절대 해제하지 않는다.
            return "break"

        # 3) 일반 행 클릭:
        #    현재 파란 선택 그룹 밖의 항목을 클릭하면 기존 파란 선택은 모두 해제.
        #    클릭한 항목은 다음 Shift 범위의 기준점(anchor)만 된다.
        if iid not in self.highlighted_iids:
            self._highlight_items([])
        self.last_checked_iid = iid
        return "break"

    def _select_all(self):
        items = list(self.tree.get_children())
        for iid in items:
            self._set_checked(iid, True)
        self._highlight_items(items)

    def _clear_selection(self):
        items = list(self.tree.get_children())
        for iid in items:
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
            messagebox.showerror(APP_NAME, "추출할 레이어를 선택해주세요.")
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
        self.status_var.set(f"{len(selected)}개 레이어 변환 중...")
        self._set_progress(0, "Excel 변환 준비")
        self._log("="*70)
        self._log("선택 레이어: " + ", ".join(selected))

        def worker():
            try:
                stats = convert_selected_layers(
                    self.input_var.get().strip(),
                    out,
                    selected,
                    epsg,
                    None,
                    log=lambda m: self.q.put(("log",m)),
                    progress=lambda p,t: self.q.put(("progress",(p,t))),
                )
                self.q.put(("done",stats))
            except Exception as e:
                self.q.put(("error",str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "progress":
                    self._set_progress(data[0], data[1])
                elif kind == "layers":
                    for i, layer in enumerate(data):
                        iid = f"L{i}"
                        self.layer_names[iid] = layer.name
                        self.layer_rows[iid] = (layer.name, layer.count, layer.types)
                        self.tree.insert(
                            "",
                            "end",
                            iid=iid,
                            values=("☐", layer.name, layer.count, layer.types),
                        )
                    self.scan_btn.config(state="normal")
                    self.run_btn.config(state="normal" if data else "disabled")
                    self.status_var.set(f"레이어 {len(data)}개 발견 · 0개 선택")
                    self._log(f"레이어 {len(data)}개 스캔 완료")
                    self._set_progress(100, f"레이어 {len(data)}개 분석 완료")
                elif kind == "done":
                    self.scan_btn.config(state="normal")
                    self.run_btn.config(state="normal")
                    self.status_var.set("완료")
                    self._set_progress(100, "Excel 생성 완료")
                    self._log(
                        f"선택레이어 {data.layers} / 객체 {data.entities} / 출력행 {data.rows}"
                    )
                    messagebox.showinfo(
                        APP_NAME,
                        "선택한 레이어를 Excel 시트로 생성했습니다.",
                    )
                elif kind == "error":
                    self.scan_btn.config(state="normal")
                    self.run_btn.config(state="normal" if self.layer_names else "disabled")
                    self.status_var.set("오류")
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
        canvas = self.progress_canvas
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        fill_width = int(width * self.progress_value / 100.0)
        canvas.create_rectangle(0, 0, width, height, fill="#e5e7eb", outline="")
        if fill_width > 0:
            canvas.create_rectangle(0, 0, fill_width, height, fill="#2563eb", outline="")
        text_color = "white" if self.progress_value >= 45 else "#111827"
        canvas.create_text(
            width // 2,
            height // 2,
            text=self.progress_text,
            fill=text_color,
            font=("Malgun Gothic", 10, "bold"),
        )

    def _log(self, msg):
        self.log.insert("end", str(msg) + "\n")
        self.log.see("end")

    def _open_output(self):
        p = self.output_var.get().strip()
        folder = str(Path(p).parent) if p else os.getcwd()
        if os.path.isdir(folder):
            os.startfile(folder)

if __name__ == "__main__":
    App().mainloop()
