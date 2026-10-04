from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v3.17 patch target not found: {label}")
    return text.replace(old, new, 1)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.16"', 'APP_NAME = "CMB DXF Viewer + Excel v3.17"', 1)

old_view = '''        # 본창은 Viewer를 최대 폭으로 사용하고 레이어는 별도 이동 가능한 창으로 표시한다.\n        self.viewer = DXFViewer(root)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n\n        status = ttk.Frame(root)\n'''
new_view = '''        # 레이어 창은 독립 Toplevel이지만, 본창 내부에 있을 때는\n        # 좌측 도킹 공간을 확보하여 도면과 겹치지 않게 한다.\n        self.viewer_host = ttk.Frame(root)\n        self.viewer_host.pack(fill="both", expand=True)\n\n        self.layer_dock_space = ttk.Frame(self.viewer_host, width=430)\n        self.layer_dock_space.pack(side="left", fill="y")\n        self.layer_dock_space.pack_propagate(False)\n        self.layer_docked = True\n\n        self.viewer_frame = ttk.Frame(self.viewer_host)\n        self.viewer_frame.pack(side="left", fill="both", expand=True)\n\n        self.viewer = DXFViewer(self.viewer_frame)\n        self.viewer.pack(fill="both", expand=True)\n        self.viewer.set_source_epsg(self.epsg_var.get())\n\n        status = ttk.Frame(root)\n'''
main = replace_once(main, old_view, new_view, "viewer dock host")

old_start = '''        self._create_layer_window(show=True)\n        self.after(180, self._place_layer_window_left)\n\n        self.bind("<F11>", lambda e: self._toggle_fullscreen())\n'''
new_start = '''        self._create_layer_window(show=True)\n        if self.layer_window is not None and self.layer_window.winfo_exists():\n            self.layer_window.bind("<Configure>", self._layer_window_configure, add="+")\n        self.after(180, self._place_layer_window_left)\n\n        self.bind("<F11>", lambda e: self._toggle_fullscreen())\n'''
main = replace_once(main, old_start, new_start, "layer configure binding")

old_place = '''    def _place_layer_window_left(self):\n        if self.layer_window is None or not self.layer_window.winfo_exists():\n            return\n        try:\n            # 레이어 창은 독립 Toplevel이지만 최초 위치는 반드시\n            # 본 프로그램의 도면 영역 안쪽 좌측에 겹쳐서 표시한다.\n            self.update_idletasks()\n            self.viewer.update_idletasks()\n\n            vx = self.viewer.winfo_rootx()\n            vy = self.viewer.winfo_rooty()\n            vw = max(600, self.viewer.winfo_width())\n            vh = max(420, self.viewer.winfo_height())\n\n            margin = 10\n            width = min(430, max(300, vw // 3))\n            height = max(360, min(vh - margin * 2, 720))\n            x = vx + margin\n            y = vy + margin\n\n            self.layer_window.geometry(f"{width}x{height}+{x}+{y}")\n            self.layer_window.deiconify()\n            self.layer_window.lift()\n        except Exception:\n            pass\n\n'''
new_place = '''    def _set_layer_docked(self, docked):\n        docked = bool(docked)\n        if getattr(self, "layer_docked", None) == docked:\n            return\n        self.layer_docked = docked\n        if docked:\n            if not self.layer_dock_space.winfo_ismapped():\n                self.layer_dock_space.pack(side="left", fill="y", before=self.viewer_frame)\n        else:\n            if self.layer_dock_space.winfo_ismapped():\n                self.layer_dock_space.pack_forget()\n        self.after(20, self.viewer.redraw)\n\n    def _layer_window_configure(self, event=None):\n        if self.layer_window is None or not self.layer_window.winfo_exists():\n            return\n        try:\n            lx = self.layer_window.winfo_rootx()\n            ly = self.layer_window.winfo_rooty()\n            lw = max(1, self.layer_window.winfo_width())\n            lh = max(1, self.layer_window.winfo_height())\n            cx = lx + lw // 2\n            cy = ly + lh // 2\n\n            hx = self.viewer_host.winfo_rootx()\n            hy = self.viewer_host.winfo_rooty()\n            hw = self.viewer_host.winfo_width()\n            hh = self.viewer_host.winfo_height()\n            inside = hx <= cx <= hx + hw and hy <= cy <= hy + hh\n            self._set_layer_docked(inside)\n        except Exception:\n            pass\n\n    def _place_layer_window_left(self):\n        if self.layer_window is None or not self.layer_window.winfo_exists():\n            return\n        try:\n            self.update_idletasks()\n            self.viewer_host.update_idletasks()\n\n            hx = self.viewer_host.winfo_rootx()\n            hy = self.viewer_host.winfo_rooty()\n            hh = max(420, self.viewer_host.winfo_height())\n\n            margin = 8\n            width = 420\n            height = max(360, min(hh - margin * 2, 720))\n            x = hx + margin\n            y = hy + margin\n\n            self.layer_dock_space.configure(width=width + margin * 2)\n            self._set_layer_docked(True)\n            self.layer_window.geometry(f"{width}x{height}+{x}+{y}")\n            self.layer_window.deiconify()\n            self.layer_window.lift()\n        except Exception:\n            pass\n\n'''
main = replace_once(main, old_place, new_place, "dynamic non-overlap docking")

old_hide = '''    def _hide_layer_window(self):\n        if self.layer_window is not None and self.layer_window.winfo_exists():\n            self.layer_window.withdraw()\n'''
new_hide = '''    def _hide_layer_window(self):\n        if self.layer_window is not None and self.layer_window.winfo_exists():\n            self.layer_window.withdraw()\n        self._set_layer_docked(False)\n'''
main = replace_once(main, old_hide, new_hide, "hide releases dock space")

old_show = '''    def _show_layer_window(self):\n        self._create_layer_window(show=False)\n        self.layer_window.deiconify()\n        self.layer_window.lift()\n        try:\n            self.layer_window.focus_force()\n        except Exception:\n            pass\n'''
new_show = '''    def _show_layer_window(self):\n        self._create_layer_window(show=False)\n        self._place_layer_window_left()\n        try:\n            self.layer_window.focus_force()\n        except Exception:\n            pass\n'''
main = replace_once(main, old_show, new_show, "reopen docked")

main_path.write_text(main, encoding="utf-8")
print("v3.17 layout applied: floating layer window with automatic non-overlap docking")
