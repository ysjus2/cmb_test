from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v3.16 patch target not found: {label}")
    return text.replace(old, new, 1)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.15"', 'APP_NAME = "CMB DXF Viewer + Excel v3.16"', 1)

old_place = '''    def _place_layer_window_left(self):\n        if self.layer_window is None or not self.layer_window.winfo_exists():\n            return\n        try:\n            self.update_idletasks()\n            x = max(0, self.winfo_x())\n            y = max(0, self.winfo_y() + 45)\n            h = max(520, self.winfo_height() - 90)\n            self.layer_window.geometry(f"430x{h}+{x}+{y}")\n            self.layer_window.deiconify()\n            self.layer_window.lift()\n        except Exception:\n            pass\n\n'''
new_place = '''    def _place_layer_window_left(self):\n        if self.layer_window is None or not self.layer_window.winfo_exists():\n            return\n        try:\n            # 레이어 창은 독립 Toplevel이지만 최초 위치는 반드시\n            # 본 프로그램의 도면 영역 안쪽 좌측에 겹쳐서 표시한다.\n            self.update_idletasks()\n            self.viewer.update_idletasks()\n\n            vx = self.viewer.winfo_rootx()\n            vy = self.viewer.winfo_rooty()\n            vw = max(600, self.viewer.winfo_width())\n            vh = max(420, self.viewer.winfo_height())\n\n            margin = 10\n            width = min(430, max(300, vw // 3))\n            height = max(360, min(vh - margin * 2, 720))\n            x = vx + margin\n            y = vy + margin\n\n            self.layer_window.geometry(f"{width}x{height}+{x}+{y}")\n            self.layer_window.deiconify()\n            self.layer_window.lift()\n        except Exception:\n            pass\n\n'''
main = replace_once(main, old_place, new_place, "place layer window inside viewer")
main_path.write_text(main, encoding="utf-8")

print("v3.16 layout applied: layer window starts inside viewer left edge")
