from pathlib import Path
p=Path("viewer.py")
s=p.read_text(encoding="utf8")
assert "    def _wheel(self, event):\n        factor = 1.15 if event.delta > 0 else 1/1.15\n        self._zoom_at(event.x, event.y, factor)" in s, 'Navigation patch marker missing'
s=s.replace("    def _wheel(self, event):\n        factor = 1.15 if event.delta > 0 else 1/1.15\n        self._zoom_at(event.x, event.y, factor)","    def _wheel(self, event):\n        delta = float(getattr(event, \"delta\", 0) or 0)\n        if not math.isfinite(delta) or delta == 0:\n            return \"break\"\n        notches = max(-4.0, min(4.0, delta / 120.0))\n        self._zoom_at(event.x, event.y, 1.15 ** notches)\n        return \"break\"",1)
assert "        self.oy = sy + wy*self.scale\n        self.redraw()" in s, 'Navigation patch marker missing'
s=s.replace("        self.oy = sy + wy*self.scale\n        self.redraw()","        self.oy = sy + wy*self.scale\n        # A drag must resume from the new zoom origin, not its pre-zoom origin.\n        if self.pan_start is not None:\n            self.pan_start = (sx, sy, self.ox, self.oy)\n        self.redraw()",1)
assert "        self.oy = h/2 + cy*self.scale\n        self.redraw()" in s, 'Navigation patch marker missing'
s=s.replace("        self.oy = h/2 + cy*self.scale\n        self.redraw()","        self.oy = h/2 + cy*self.scale\n        self.pan_start = None\n        self.redraw()",1)
p.write_text(s,encoding="utf8")
p=Path("main.py")
s=p.read_text(encoding="utf8").replace("v3.25","v3.26")
p.write_text(s,encoding="utf8")
print("v3.26 zoom/drag origin synchronization applied")
