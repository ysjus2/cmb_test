from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import convert_file

APP_NAME = "CAD → Excel 변환기"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("900x650")
        self.minsize(820, 580)
        self.q = queue.Queue()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.epsg_var = tk.StringVar(value="5174")
        self.oda_var = tk.StringVar()
        self.status_var = tk.StringVar(value="준비")
        self._build()
        self.after(100, self._drain)

    def _build(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="CAD → Excel 변환기", font=("Malgun Gothic", 20, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="서버/AI 전송 없음 · 모든 변환은 이 PC 내부에서만 수행",
            foreground="#126b3a",
        ).pack(anchor="w", pady=(2, 14))

        form = ttk.Frame(root)
        form.pack(fill="x")
        self._row(form, 0, "CAD 파일", self.input_var, self._pick_input)
        self._row(form, 1, "출력 Excel", self.output_var, self._pick_output)

        ttk.Label(form, text="원본 좌표계").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        combo = ttk.Combobox(
            form,
            textvariable=self.epsg_var,
            values=["5174", "2097", "5181", "5179", "5186"],
            width=18,
        )
        combo.grid(row=2, column=1, sticky="w", pady=6)
        ttk.Label(form, text="현재 CAD는 EPSG:5174가 정확히 일치").grid(
            row=2, column=2, sticky="w", padx=8
        )

        self._row(form, 3, "ODA 변환기", self.oda_var, self._pick_oda, optional=True)
        form.columnconfigure(1, weight=1)

        bar = ttk.Frame(root)
        bar.pack(fill="x", pady=12)
        self.run_btn = ttk.Button(bar, text="변환 시작", command=self._run)
        self.run_btn.pack(side="left")
        ttk.Button(bar, text="출력 폴더 열기", command=self._open_output).pack(side="left", padx=8)
        ttk.Label(bar, textvariable=self.status_var).pack(side="right")

        box = ttk.LabelFrame(root, text="자동 분류 기준", padding=10)
        box.pack(fill="x", pady=(0, 10))
        ttk.Label(
            box,
            text="FACILITY: 전주/맨홀 · EQUIPMENT: ONU/TAP/AMP/광클로저/광센터/수동소자 · FIBER: 광선로 · COAX: 동축선로",
        ).pack(anchor="w")
        ttk.Label(
            box,
            text="Excel 시트: CELL / FACILITY / EQUIPMENT / FIBER / COAX / INFO",
        ).pack(anchor="w")

        self.log = tk.Text(root, height=18, wrap="word", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self._log("프로그램 준비 완료.")
        self._log("DXF는 직접 처리합니다. DWG는 로컬 ODA File Converter가 필요합니다.")

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
            self.output_var.set(str(Path(p).with_suffix("")) + "_모바일앱용_지역DB.xlsx")

    def _pick_output(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if p:
            self.output_var.set(p)

    def _pick_oda(self):
        p = filedialog.askopenfilename(
            filetypes=[
                ("ODA File Converter", "ODAFileConverter.exe"),
                ("실행 파일", "*.exe"),
            ]
        )
        if p:
            self.oda_var.set(p)

    def _run(self):
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "CAD 파일을 선택해주세요.")
            return
        if not out:
            messagebox.showerror(APP_NAME, "출력 Excel 경로를 지정해주세요.")
            return
        try:
            epsg = int(self.epsg_var.get().strip())
        except ValueError:
            messagebox.showerror(APP_NAME, "EPSG 번호를 확인해주세요.")
            return

        self.run_btn.config(state="disabled")
        self.status_var.set("변환 중")
        self._log("=" * 70)
        self._log(f"입력: {inp}")
        self._log(f"출력: {out}")
        self._log(f"좌표계: EPSG:{epsg}")

        def worker():
            try:
                stats = convert_file(
                    inp,
                    out,
                    epsg,
                    self.oda_var.get().strip() or None,
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
                elif kind == "done":
                    self.run_btn.config(state="normal")
                    self.status_var.set("완료")
                    self._log(
                        f"시설 {data.facilities} / 장비 {data.equipment} / "
                        f"광선로점 {data.fiber_points} / 동축선로점 {data.coax_points}"
                    )
                    messagebox.showinfo(APP_NAME, "Excel 변환이 완료되었습니다.")
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
