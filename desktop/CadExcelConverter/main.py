from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import convert_file, list_layers

APP_NAME = "CAD → Excel 레이어 변환기"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("980x760")
        self.minsize(900, 680)
        self.q = queue.Queue()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.epsg_var = tk.StringVar(value="5174")
        self.oda_var = tk.StringVar()
        self.status_var = tk.StringVar(value="CAD 파일을 선택해주세요.")
        self.layer_items = []
        self._build()
        self.after(100, self._drain)

    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="CAD → Excel 레이어 변환기",
                  font=("Malgun Gothic", 20, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="AI/서버 전송 없음 · CAD와 Excel은 이 PC 내부에서만 처리",
            foreground="#126b3a",
        ).pack(anchor="w", pady=(2, 14))

        form = ttk.Frame(root)
        form.pack(fill="x")
        self._row(form, 0, "CAD 파일", self.input_var, self._pick_input)
        self._row(form, 1, "출력 Excel", self.output_var, self._pick_output)

        ttk.Label(form, text="원본 좌표계").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Combobox(
            form, textvariable=self.epsg_var,
            values=["5174", "2097", "5181", "5179", "5186"], width=18
        ).grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(form, text="현재 샘플 CAD 기준: EPSG:5174").grid(
            row=2, column=2, sticky="w", padx=8
        )

        self._row(form, 3, "ODA 변환기", self.oda_var, self._pick_oda, optional=True)
        form.columnconfigure(1, weight=1)

        layer_frame = ttk.LabelFrame(root, text="CAD 레이어 선택", padding=10)
        layer_frame.pack(fill="both", expand=True, pady=(10, 8))

        toolbar = ttk.Frame(layer_frame)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text="레이어 읽기", command=self._load_layers).pack(side="left")
        ttk.Button(toolbar, text="전체 선택", command=self._select_all).pack(side="left", padx=6)
        ttk.Button(toolbar, text="전체 해제", command=self._clear_all).pack(side="left")
        ttk.Label(
            toolbar,
            text="Ctrl/Shift로 여러 레이어를 선택할 수 있습니다."
        ).pack(side="right")

        list_wrap = ttk.Frame(layer_frame)
        list_wrap.pack(fill="both", expand=True)

        self.layer_list = tk.Listbox(
            list_wrap,
            selectmode=tk.EXTENDED,
            exportselection=False,
            font=("Malgun Gothic", 10),
        )
        yscroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.layer_list.yview)
        self.layer_list.configure(yscrollcommand=yscroll.set)
        self.layer_list.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(4, 8))
        self.run_btn = ttk.Button(bottom, text="선택 레이어 Excel 생성", command=self._run)
        self.run_btn.pack(side="left")
        ttk.Button(bottom, text="출력 폴더 열기", command=self._open_output).pack(side="left", padx=8)
        ttk.Label(bottom, textvariable=self.status_var).pack(side="right")

        info = ttk.LabelFrame(root, text="출력 방식", padding=8)
        info.pack(fill="x", pady=(0, 8))
        ttk.Label(info, text="• 선택한 CAD 레이어마다 Excel 시트 1개 생성").pack(anchor="w")
        ttk.Label(info, text="• LAYER_INDEX 시트에 CAD 레이어명 ↔ Excel 시트명 대응표 생성").pack(anchor="w")
        ttk.Label(info, text="• 선/폴리라인은 좌표점별 행으로 저장, 블록/텍스트/포인트도 동일 시트에 기록").pack(anchor="w")

        self.log = tk.Text(root, height=8, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="x")
        self._log("프로그램 준비 완료.")

    def _row(self, parent, row, label, var, command, optional=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="찾기", command=command).grid(row=row, column=2, padx=(8, 0), pady=6)
        if optional:
            ttk.Label(parent, text="(DWG일 때만 필요)").grid(row=row, column=3, sticky="w", padx=6)

    def _pick_input(self):
        p = filedialog.askopenfilename(
            filetypes=[
                ("CAD 파일", "*.dwg *.dxf"),
                ("DWG", "*.dwg"),
                ("DXF", "*.dxf"),
                ("모든 파일", "*.*"),
            ]
        )
        if p:
            self.input_var.set(p)
            self.output_var.set(str(Path(p).with_suffix("")) + "_레이어별_지역DB.xlsx")
            self._load_layers()

    def _pick_output(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if p:
            self.output_var.set(p)

    def _pick_oda(self):
        p = filedialog.askopenfilename(
            filetypes=[("ODA File Converter", "ODAFileConverter.exe"), ("실행 파일", "*.exe")]
        )
        if p:
            self.oda_var.set(p)

    def _load_layers(self):
        inp = self.input_var.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "먼저 CAD 파일을 선택해주세요.")
            return
        self.status_var.set("레이어 읽는 중...")
        self.layer_list.delete(0, tk.END)
        self.layer_items = []

        def worker():
            try:
                layers = list_layers(inp, self.oda_var.get().strip() or None)
                self.q.put(("layers", layers))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _select_all(self):
        if self.layer_list.size():
            self.layer_list.selection_set(0, tk.END)

    def _clear_all(self):
        self.layer_list.selection_clear(0, tk.END)

    def _selected_layers(self):
        return [self.layer_items[i][0] for i in self.layer_list.curselection()]

    def _run(self):
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "CAD 파일을 선택해주세요.")
            return
        if not out:
            messagebox.showerror(APP_NAME, "출력 Excel 경로를 지정해주세요.")
            return
        layers = self._selected_layers()
        if not layers:
            messagebox.showerror(APP_NAME, "Excel로 만들 레이어를 하나 이상 선택해주세요.")
            return
        try:
            epsg = int(self.epsg_var.get().strip())
        except ValueError:
            messagebox.showerror(APP_NAME, "EPSG 번호를 확인해주세요.")
            return

        self.run_btn.config(state="disabled")
        self.status_var.set(f"{len(layers)}개 레이어 변환 중")
        self._log("=" * 70)
        self._log(f"입력: {inp}")
        self._log(f"선택 레이어: {len(layers)}개")

        def worker():
            try:
                stats = convert_file(
                    inp, out, epsg,
                    self.oda_var.get().strip() or None,
                    selected_layers=layers,
                    log=lambda m: self.q.put(("log", m)),
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
                elif kind == "layers":
                    self.layer_items = data
                    self.layer_list.delete(0, tk.END)
                    for layer, count in data:
                        self.layer_list.insert(tk.END, f"{layer}    [{count} entities]")
                    self._select_all()
                    self.status_var.set(f"레이어 {len(data)}개 읽음")
                    self._log(f"레이어 {len(data)}개를 찾았습니다.")
                elif kind == "done":
                    self.run_btn.config(state="normal")
                    self.status_var.set("완료")
                    self._log(f"완료: {data.layers}개 레이어 / {data.entities}개 엔티티 / {data.rows}행")
                    messagebox.showinfo(APP_NAME, "레이어별 Excel 생성이 완료되었습니다.")
                elif kind == "error":
                    self.run_btn.config(state="normal")
                    self.status_var.set("오류")
                    self._log("오류: " + data)
                    messagebox.showerror(APP_NAME, data)
        except queue.Empty:
            pass
        self.after(100, self._drain)

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
