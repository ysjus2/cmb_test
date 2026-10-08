from pathlib import Path

path = Path("main.py")
text = path.read_text(encoding="utf-8")
old = '''    def _escape_key(self, event=None):\n        if self.fullscreen:\n            self.fullscreen = False\n            self.attributes("-fullscreen", False)\n            self.after(50, self.viewer.redraw)\n        else:\n            self.viewer.handle_escape()\n'''
new = '''    def _escape_key(self, event=None):\n        # ESC는 Viewer 조작 전용: 거리 측정 완료 또는 선택 해제.\n        # 전체화면 진입/해제는 F11만 사용한다.\n        return self.viewer.handle_escape(event)\n'''
if old not in text:
    raise RuntimeError("ESC policy target not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("ESC policy applied: F11 fullscreen only / ESC viewer interaction only")
