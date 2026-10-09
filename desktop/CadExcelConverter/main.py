from __future__ import annotations

import os
import json
import queue
import threading
import tkinter as tk
import subprocess
import sys
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from converter import LayerInfo, convert_selected_layers, scan_layers
from viewer import DXFViewer, build_scene
from drawing_cache import open_drawing
from layer_defaults import is_default_hidden
from network_extract_ui import NetworkExtractionMixin
from admin_upload import AdminUploadWindow
from server_extract import ServerExtractWindow
from admin_users import UserAdminWindow
from server_client_windows import CMBServerClient
from session_guard import TkIdleSessionGuard

APP_NAME = "CMB DXF Viewer + Excel v3.36"
SESSION_ENDED_EXIT_CODE = 41


class App(NetworkExtractionMixin, tk.Tk):
    def __init__(self, session_user=None):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1450x900")
        self.minsize(1000, 650)

        self.session_user = dict(session_user or {})
        try:
            self.user_level = int(self.session_user.get("level", 5))
        except Exception:
            self.user_level = 5
        self.can_extract = self.user_level <= 3
        self.is_admin = self.user_level == 1
        self.session_ended = False

        self.q = queue.Queue()
        self.input_path = ""
        self.epsg_var = tk.StringVar(value="5174")
        self.status_var = tk.StringVar(value="파일 > 열기에서 DXF 파일을 선택해주세요.")
        self.progress_value = 0
        self.progress_text = "0% · 준비"
        self.busy = False
        self.fullscreen = False

        self.layer_names = {}
        self.layer_rows = {}
        self.checked_layers = set()
        self.visible_layers = set()
        self.last_checked_iid = None
        self.highlighted_iids = set()
        self.layer_window = None
        self.tree = None

        self._build_menu()
        self._build_main_view()
        # 시작 시 레이어는 본창 내부 좌측에 실제 도킹된 패널로 표시한다.
        self._build_docked_layer_panel()

        self.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.bind("<Escape>", self._escape_key)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(100, self._drain)

    def _require_extract_permission(self):
        if not self.can_extract:
            messagebox.showwarning(
                APP_NAME,
                "현재 계정은 도면 보기 전용입니다.\n추출/Excel 기능은 1~3등급에서만 사용할 수 있습니다.",
                parent=self,
            )
            return False
        return True

    def _require_admin_permission(self):
        if not self.is_admin:
            messagebox.showwarning(
                APP_NAME,
                "관리자 기능은 1등급 계정에서만 사용할 수 있습니다.",
                parent=self,
            )
            return False
        return True

    def _session_busy(self):
        if bool(getattr(self, "busy", False)):
            return True
        try:
            for child in self.winfo_children():
                if bool(getattr(child, "session_busy", False)):
                    return True
        except Exception:
            pass
        return False

    def _build_menu(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="열기...", command=self._pick_input, accelerator="Ctrl+O")
        if self.can_extract:
            file_menu.add_command(label="Excel로 출력...", command=self._run_excel, accelerator="Ctrl+E")
            file_menu.add_command(label="전체 레이어 Excel (기존 방식)", command=self._run_all_layer_excel)
        file_menu.add_separator()
        file_menu.add_command(label="레이어 표시", command=self._show_layer_window)
        file_menu.add_separator()
        file_menu.add_command(label="종료", command=self.destroy)
        menubar.add_cascade(label="파일", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="도면 점검 결과", command=self._show_drawing_audit)
        view_menu.add_command(label="전체 화면", command=self._toggle_fullscreen, accelerator="F11")
        menubar.add_cascade(label="보기", menu=view_menu)

        settings_menu = tk.Menu(menubar, tearoff=False)
        epsg_menu = tk.Menu(settings_menu, tearoff=False)
        for epsg, label in [
            ("5174", "EPSG:5174"),
            ("2097", "EPSG:2097"),
            ("5181", "EPSG:5181"),
            ("5179", "EPSG:5179"),
            ("5186", "EPSG:5186"),
        ]:
            epsg_menu.add_radiobutton(
                label=label,
                variable=self.epsg_var,
                value=epsg,
                command=self._epsg_changed,
            )
        settings_menu.add_cascade(label="좌표계", menu=epsg_menu)
        menubar.add_cascade(label="설정", menu=settings_menu)

        self.config(menu=menubar)
        self.bind_all("<Control-o>", lambda e: self._pick_input())
        if self.can_extract:
            self.bind_all("<Control-e>", lambda e: self._run_excel())

    def _build_main_view(self):
        root = ttk.Frame(self, padding=4)
        root.pack(fill="both", expand=True)

        self._build_extract_toolbar(root)

        # Viewer 자체가 전체 폭을 차지한다.
        # 레이어는 Viewer의 상단 도구바 아래 side_host에 실제 위젯으로 도킹된다.
        self.viewer = DXFViewer(root)
        self.viewer.pack(fill="both", expand=True)
        self.viewer.set_source_epsg(self.epsg_var.get())

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(3, 0))
        ttk.Label(status, textvariable=self.status_var, anchor="w").pack(fill="x")

        self.progress_frame = ttk.Frame(root)
        self.progress_canvas = tk.Canvas(
            self.progress_frame,
            height=24,
            highlightthickness=1,
            highlightbackground="#9ca3af",
            bg="#e5e7eb",
        )
        self.progress_canvas.pack(fill="x")
        self.progress_canvas.bind("<Configure>", lambda e: self._draw_progress())
        self.progress_frame.pack_forget()
        self.last_log = ""

    def _create_layer_window(self, show=False):
        if self.layer_window is not None and self.layer_window.winfo_exists():
            if show:
                self._show_layer_window()
            return

        win = tk.Toplevel(self)
        win.title("레이어")
        win.geometry("520x720")
        win.minsize(330, 350)
        win.transient(None)
        win.protocol("WM_DELETE_WINDOW", self._hide_layer_window)
        self.layer_window = win

        frame = ttk.Frame(win, padding=6)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame,
            columns=("check", "layer", "count", "types"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("check", text="선택")
        self.tree.heading("layer", text="레이어명")
        self.tree.heading("count", text="객체수")
        self.tree.heading("types", text="객체종류")
        self.tree.column("check", width=55, anchor="center", stretch=False)
        self.tree.column("layer", width=230)
        self.tree.column("count", width=70, anchor="center", stretch=False)
        self.tree.column("types", width=150)
        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")
        self.tree.bind("<Button-1>", self._tree_click)
        self.tree.bind("<Button-3>", self._layer_context_menu)

        y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        if not show:
            win.withdraw()

    def _layer_context_menu(self, event):
        menu = tk.Menu(self.tree, tearoff=False)
        menu.add_command(label="전체 선택", command=self._select_all)
        menu.add_command(label="전체 해제", command=self._clear_selection)
        menu.tk_popup(event.x_root, event.y_root)

    def _show_layer_window(self):
        self._create_layer_window(show=False)
        self._place_layer_window_left()
        try:
            self.layer_window.focus_force()
        except Exception:
            pass

    def _hide_layer_window(self):
        if self.layer_window is not None and self.layer_window.winfo_exists():
            self.layer_window.withdraw()
        self._set_layer_docked(False)

    def _rebuild_layer_tree_rows(self):
        if self.tree is None:
            return
        try:
            self.tree.delete(*self.tree.get_children())
        except Exception:
            return
        for iid, row in self.layer_rows.items():
            try:
                self.tree.insert("", "end", iid=iid, values=self._row_values(iid))
                if iid in self.highlighted_iids:
                    self.tree.item(iid, tags=("range_selected",))
            except Exception:
                pass

    def _build_layer_tree_in(self, parent):
        for child in parent.winfo_children():
            child.destroy()

        self.tree = ttk.Treeview(
            parent,
            columns=("check", "layer", "count", "types"),
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("check", text="선택")
        self.tree.heading("layer", text="레이어명")
        self.tree.heading("count", text="객체수")
        self.tree.heading("types", text="객체종류")
        self.tree.column("check", width=55, anchor="center", stretch=False)
        self.tree.column("layer", width=210)
        self.tree.column("count", width=65, anchor="center", stretch=False)
        self.tree.column("types", width=120)
        self.tree.tag_configure("range_selected", background="#2563eb", foreground="#ffffff")
        self.tree.bind("<Button-1>", self._tree_click)
        self.tree.bind("<Button-3>", self._layer_context_menu)

        y = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")
        self._rebuild_layer_tree_rows()

    def _build_docked_layer_panel(self):
        # 플로팅 창이 있으면 닫고, Viewer 내부 좌측에 실제 레이어 패널을 만든다.
        if self.layer_window is not None:
            try:
                if self.layer_window.winfo_exists():
                    self.layer_window.destroy()
            except Exception:
                pass
            self.layer_window = None

        host = self.viewer.side_host
        for child in host.winfo_children():
            child.destroy()

        self.layer_panel = ttk.Frame(host, relief="solid", borderwidth=1)
        self.layer_panel.pack(fill="both", expand=True)

        title = ttk.Frame(self.layer_panel, padding=(7, 4))
        title.pack(fill="x")
        self.layer_title = ttk.Label(title, text="레이어", anchor="w")
        self.layer_title.pack(side="left", fill="x", expand=True)
        close_btn = ttk.Button(title, text="×", width=3, command=self._hide_layer_window)
        close_btn.pack(side="right")

        body = ttk.Frame(self.layer_panel, padding=(4, 0, 4, 4))
        body.pack(fill="both", expand=True)
        self._build_layer_tree_in(body)

        # 제목줄을 끌면 일정 거리 이후 독립 창으로 분리한다.
        for widget in (title, self.layer_title):
            widget.bind("<ButtonPress-1>", self._layer_drag_start)
            widget.bind("<B1-Motion>", self._layer_drag_motion)

        host.configure(width=420)
        try:
            panes = [str(p) for p in self.viewer.body.panes()]
            if str(host) not in panes:
                self.viewer.body.add(host, before=self.viewer.canvas_host, minsize=220, width=420, stretch="never")
            self.after(40, lambda: self.viewer.body.sash_place(0, 420, 0))
        except Exception:
            pass
        self.layer_docked = True
        self.after(20, self.viewer.redraw)

    def _layer_drag_start(self, event):
        self._layer_drag_origin = (event.x_root, event.y_root)
        self._layer_drag_detached = False

    def _layer_drag_motion(self, event):
        origin = getattr(self, "_layer_drag_origin", None)
        if not origin or getattr(self, "_layer_drag_detached", False):
            return
        dx = event.x_root - origin[0]
        dy = event.y_root - origin[1]
        if dx * dx + dy * dy < 900:
            return
        self._layer_drag_detached = True
        self._detach_layer_window(event.x_root - 40, event.y_root - 15)

    def _detach_layer_window(self, x=None, y=None):
        # 내부 패널을 제거하면 Canvas가 즉시 전체 폭을 사용한다.
        try:
            self.viewer.body.forget(self.viewer.side_host)
        except Exception:
            pass
        self.tree = None
        try:
            for child in self.viewer.side_host.winfo_children():
                child.destroy()
        except Exception:
            pass

        self.layer_window = None
        self._create_layer_window(show=True)
        self._rebuild_layer_tree_rows()
        if self.layer_window is not None and self.layer_window.winfo_exists():
            try:
                if x is not None and y is not None:
                    self.layer_window.geometry(f"430x720+{max(0, int(x))}+{max(0, int(y))}")
                self.layer_window.lift()
            except Exception:
                pass
        self.layer_docked = False
        self.after(20, self.viewer.redraw)

    def _hide_layer_window(self):
        if self.layer_window is not None:
            try:
                if self.layer_window.winfo_exists():
                    self.layer_window.destroy()
            except Exception:
                pass
            self.layer_window = None
        try:
            self.viewer.body.forget(self.viewer.side_host)
            for child in self.viewer.side_host.winfo_children():
                child.destroy()
        except Exception:
            pass
        self.tree = None
        self.layer_docked = False
        self.after(20, self.viewer.redraw)

    def _show_layer_window(self):
        # 메뉴에서 다시 표시할 때는 항상 내부 좌측 도킹 상태로 복원한다.
        self._build_docked_layer_panel()

    def _open_online_viewer(self):
        # pywebview/WebView2는 Tk 이벤트 루프와 분리된 프로세스로 실행한다.
        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable, "--online-viewer"])
            else:
                subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--online-viewer"])
            self.status_var.set("온라인 Viewer 새 창 실행")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"온라인 Viewer 실행 실패\n{exc}")

    def _open_admin_upload(self):
        if not self._require_admin_permission():
            return
        if not self.input_path or not os.path.isfile(self.input_path) or self.viewer.scene is None:
            messagebox.showinfo(APP_NAME, "먼저 서버에 올릴 DXF 도면을 열어주세요.")
            return
        client = CMBServerClient()
        client.access_token = os.getenv("CMB_AUTH_ACCESS", "").strip()
        client.refresh_token = os.getenv("CMB_AUTH_REFRESH", "").strip()
        AdminUploadWindow(
            self,
            self.viewer.scene,
            self.input_path,
            self.epsg_var.get(),
            client=client,
            current_user=self.session_user,
        )

    def _open_server_extract(self):
        if not self._require_admin_permission():
            return
        client = CMBServerClient()
        client.access_token = os.getenv("CMB_AUTH_ACCESS", "").strip()
        client.refresh_token = os.getenv("CMB_AUTH_REFRESH", "").strip()
        ServerExtractWindow(
            self,
            self.viewer,
            client=client,
            current_user=self.session_user,
            source_epsg=int(self.epsg_var.get()),
        )

    def _open_user_admin(self):
        UserAdminWindow(self)

    def _epsg_changed(self):
        self.viewer.set_source_epsg(self.epsg_var.get())
        self.status_var.set(f"좌표계 EPSG:{self.epsg_var.get()} 적용")

    def _toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.attributes("-fullscreen", self.fullscreen)
        self.after(50, self.viewer.redraw)

    def _escape_key(self, event=None):
        # ESC는 Viewer 조작 전용: 거리 측정 완료 또는 선택 해제.
        # 전체화면 진입/해제는 F11만 사용한다.
        return self.viewer.handle_escape(event)

    def _pick_input(self):
        if self.busy:
            return
        p = filedialog.askopenfilename(
            title="DXF 파일 열기",
            filetypes=[("DXF 파일", "*.dxf"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        if Path(p).suffix.lower() != ".dxf":
            messagebox.showerror(APP_NAME, "DXF 파일만 열 수 있습니다.")
            return
        self.input_path = p
        self.title(f"{APP_NAME} - {Path(p).name}")
        self._scan()

    def _scan(self):
        inp = self.input_path
        if not inp or not os.path.isfile(inp):
            messagebox.showerror(APP_NAME, "먼저 파일 > 열기에서 DXF 파일을 선택해주세요.")
            return
        if self.busy:
            return

        self._clear_network_state()
        self.busy = True
        self.status_var.set("DXF 분석 중...")
        self._show_progress()
        self._set_progress(0, "DXF 분석 준비")
        if self.tree is not None:
            self.tree.delete(*self.tree.get_children())
        self.layer_names.clear()
        self.layer_rows.clear()
        self.checked_layers.clear()
        self.visible_layers.clear()
        self.last_checked_iid = None
        self.highlighted_iids.clear()

        def worker():
            try:
                layers, scene = open_drawing(
                    inp,
                    log=lambda m: self.q.put(("log", m)),
                    progress=lambda p, t: self.q.put(("progress", (p, t))),
                )
                self.q.put(("loaded", (layers, scene)))
            except Exception as e:
                self.q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _row_values(self, iid):
        name, count, types = self.layer_rows[iid]
        return (
            "☑" if name in self.checked_layers else "☐",
            name,
            count,
            types,
        )

    def _refresh_row(self, iid):
        if self.tree is not None and iid in self.layer_rows and self.tree.exists(iid):
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
        if self.input_path:
            self.status_var.set(
                f"{Path(self.input_path).name} · 레이어 {len(self.layer_rows)}개 · 표시/Excel 대상 {len(self.checked_layers)}개"
            )

    def _highlight_items(self, items):
        if self.tree is None:
            return
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
        if self.tree is None:
            return "break"
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid:
            return "break"

        items = list(self.tree.get_children())
        shift_pressed = bool(event.state & 0x0001)

        if shift_pressed and self.last_checked_iid in items:
            start = items.index(self.last_checked_iid)
            end = items.index(iid)
            lo, hi = sorted((start, end))
            range_items = items[lo:hi + 1]
            self._highlight_items(range_items)
            if col == "#1":
                clicked_name = self.layer_names.get(iid)
                target = clicked_name not in self.checked_layers
                for item in range_items:
                    self._set_checked(item, target)
            self.last_checked_iid = iid
            return "break"

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

        self._highlight_items([iid])
        self.last_checked_iid = iid
        return "break"

    def _select_all(self):
        if self.tree is None:
            return
        items = list(self.tree.get_children())
        for iid in items:
            self._set_checked(iid, True)
        self._highlight_items(items)

    def _clear_selection(self):
        if self.tree is None:
            return
        for iid in self.tree.get_children():
            self._set_checked(iid, False)
        self._highlight_items([])
        self.last_checked_iid = None

    def _run_excel(self):
        if not self._require_extract_permission():
            return
        if self.export_scope is not None:
            return self._run_network_excel()
        messagebox.showinfo(APP_NAME, "먼저 광주간선 추출 또는 100mm 주관로 추출로 대상을 선택해주세요. 전체 레이어 출력은 파일 메뉴의 기존 방식을 사용하세요.")

    def _run_all_layer_excel(self):
        if not self._require_extract_permission():
            return
        if self.busy:
            return
        if not self.input_path or not os.path.isfile(self.input_path):
            messagebox.showerror(APP_NAME, "먼저 DXF 파일을 열어주세요.")
            return
        selected = [
            self.layer_names[iid]
            for iid in (self.tree.get_children() if self.tree is not None else [])
            if self.layer_names.get(iid) in self.checked_layers
        ]
        if not selected:
            messagebox.showerror(APP_NAME, "Excel로 출력할 레이어가 없습니다. 레이어 표시에서 선택해주세요.")
            return

        default_name = Path(self.input_path).stem + "_레이어별.xlsx"
        out = filedialog.asksaveasfilename(
            title="Excel로 출력",
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
        self._set_progress(0, "Excel 변환 준비")
        self._log("Excel 추출 레이어: " + ", ".join(selected))

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

    def _populate_layers(self, layers, scene):
        known = {layer.name for layer in layers}
        scene_counts = {}
        scene_types = {}
        for ent in scene.entities:
            scene_counts[ent.layer] = scene_counts.get(ent.layer, 0) + 1
            scene_types.setdefault(ent.layer, set()).add(ent.entity_type)
        for layer_name in sorted(scene_counts, key=str.lower):
            if layer_name not in known:
                layers.append(LayerInfo(
                    layer_name,
                    scene_counts[layer_name],
                    ", ".join(sorted(scene_types[layer_name])),
                ))
        layers.sort(key=lambda x: x.name.lower())

        if self.tree is None:
            self._create_layer_window(show=False)
        self.tree.delete(*self.tree.get_children())
        for i, layer in enumerate(layers):
            iid = f"L{i}"
            self.layer_names[iid] = layer.name
            self.layer_rows[iid] = (layer.name, scene_counts.get(layer.name, 0), ", ".join(sorted(scene_types.get(layer.name, set()))))
            # 지번은 첫 화면 가독성을 위해 기본 OFF.
            if True:  # Zoom controls detail; ID layers must remain available at close range.
                self.visible_layers.add(layer.name)
                self.checked_layers.add(layer.name)
            self.tree.insert("", "end", iid=iid, values=self._row_values(iid))

    def _show_drawing_audit(self):
        scene = self.viewer.scene
        if scene is None:
            messagebox.showinfo(APP_NAME, '먼저 DXF 도면을 열어주세요.')
            return
        counts = {}
        for ent in scene.entities:
            counts[ent.layer] = counts.get(ent.layer, 0) + 1
        empty = [name for name in self.layer_names.values() if not counts.get(name)]
        missing = [ent for ent in scene.entities if not ent.primitives]
        lines = [f'등록 레이어: {len(self.layer_names)}개', f'객체가 있는 레이어: {len(counts)}개',
                 f'빈 레이어: {len(empty)}개', f'상위/블록 내부 표시 객체: {len(scene.entities):,}개',
                 f'도형 미표시 객체: {len(missing)}개', f'블록/도형 변환 문제: {len(scene.diagnostics)}건']
        if missing:
            lines.append(chr(10) + '미표시 객체:')
            lines.extend(f'{e.layer} / {e.entity_type} / {e.handle}' for e in missing)
        if scene.diagnostics:
            lines.append(chr(10) + '변환 문제:')
            lines.extend(f"{i['layer']} / {i['type']}: {i['reason']}" for i in scene.diagnostics)
        lines.append(chr(10) + '새 사용자 객체 형식은 지원 여부를 확인해야 합니다.')
        window = tk.Toplevel(self)
        window.title('도면 점검 결과')
        window.geometry('760x480')
        text = tk.Text(window, wrap='word', font=('Malgun Gothic', 10))
        text.pack(fill='both', expand=True)
        text.insert('1.0', chr(10).join(lines))
        text.configure(state='disabled')

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
                    self._populate_layers(layers, scene)
                    self.viewer.set_source_epsg(self.epsg_var.get())
                    self.viewer.load_scene(scene)
                    self.busy = False
                    self._update_status()
                    self._set_progress(100, f"DXF Viewer 준비 완료 · 객체 {len(scene.entities):,}개")
                    self.after(450, self._hide_progress)
                    if scene.unsupported or scene.diagnostics:
                        messagebox.showwarning(APP_NAME, '일부 객체 또는 블록 내부 도형을 표시하지 못했습니다. 보기 > 도면 점검 결과에서 확인하세요.')
                    if scene.unsupported:
                        text = ", ".join(f"{k}:{v}" for k, v in sorted(scene.unsupported.items()))
                        self._log("Viewer 미표시 객체: " + text)
                elif kind == "done":
                    stats, out = data
                    self.busy = False
                    self._set_progress(100, "Excel 생성 완료")
                    self.after(450, self._hide_progress)
                    self.status_var.set(
                        f"Excel 생성 완료 · 객체 {stats.entities:,} · 행 {stats.rows:,} · {Path(out).name}"
                    )
                    messagebox.showinfo(APP_NAME, f"Excel 생성이 완료되었습니다.\n\n{out}")
                elif kind == "error":
                    self.busy = False
                    self._set_progress(self.progress_value, "오류 발생")
                    self.after(1200, self._hide_progress)
                    self._log("오류: " + data)
                    messagebox.showerror(APP_NAME, data)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _show_progress(self):
        if not self.progress_frame.winfo_manager():
            self.progress_frame.pack(fill="x", pady=(3, 0))
        self.progress_frame.lift()

    def _hide_progress(self):
        if self.progress_frame.winfo_manager():
            self.progress_frame.pack_forget()
        self.after(20, self.viewer.redraw)

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
            w // 2,
            h // 2,
            text=self.progress_text,
            fill="white" if self.progress_value >= 45 else "#111827",
            font=("Malgun Gothic", 9, "bold"),
        )

    def _log(self, msg):
        self.last_log = str(msg)


if __name__ == "__main__":
    if "--online-viewer" in sys.argv:
        from online_viewer import run_online_viewer
        raise SystemExit(run_online_viewer())

    if "--map-viewer" in sys.argv:
        session_client = CMBServerClient()
        session_client.access_token = os.getenv("CMB_AUTH_ACCESS", "").strip()
        session_client.refresh_token = os.getenv("CMB_AUTH_REFRESH", "").strip()

        try:
            if not session_client.access_token:
                raise RuntimeError("세션 없음")
            verified_user = session_client.me()
        except Exception:
            raise SystemExit(SESSION_ENDED_EXIT_CODE)

        app = App(session_user=verified_user)

        def expire_map_session():
            app.session_ended = True
            try:
                app.destroy()
            except Exception:
                pass

        app.session_guard = TkIdleSessionGuard(
            app,
            expire_map_session,
            client=session_client,
            busy_predicate=app._session_busy,
        )
        app.mainloop()
        raise SystemExit(SESSION_ENDED_EXIT_CODE if app.session_ended else 0)

    import socket
    from launcher import (
        Launcher,
        SINGLE_INSTANCE_HOST,
        SINGLE_INSTANCE_PORT,
    )

    instance_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        instance_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        instance_socket.bind((SINGLE_INSTANCE_HOST, SINGLE_INSTANCE_PORT))
        instance_socket.listen(4)
    except OSError:
        try:
            instance_socket.close()
        except Exception:
            pass
        try:
            with socket.create_connection(
                (SINGLE_INSTANCE_HOST, SINGLE_INSTANCE_PORT),
                timeout=1.0,
            ) as active:
                active.sendall(b"ACTIVATE")
        except Exception:
            pass
        raise SystemExit(0)

    app = Launcher()
    app.start_single_instance_listener(instance_socket)

    def close_instance_socket():
        try:
            instance_socket.close()
        except Exception:
            pass

    app.protocol(
        "WM_DELETE_WINDOW",
        lambda: (close_instance_socket(), app.destroy()),
    )
    app.mainloop()
