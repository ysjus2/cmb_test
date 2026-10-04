from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"v3.19 patch target not found: {label}")
    return text.replace(old, new, 1)


# Viewer body: resizable horizontal PanedWindow so layer width can be dragged.
viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")
old = '''        self.body = ttk.Frame(self)\n        self.body.pack(fill="both", expand=True)\n\n        self.side_host = ttk.Frame(self.body, width=420)\n        self.side_host.pack_propagate(False)\n\n        self.canvas_host = ttk.Frame(self.body)\n        self.canvas_host.pack(side="left", fill="both", expand=True)\n'''
new = '''        self.body = tk.PanedWindow(\n            self, orient="horizontal", sashwidth=7, sashrelief="raised",\n            showhandle=False, bd=0, relief="flat"\n        )\n        self.body.pack(fill="both", expand=True)\n\n        self.side_host = ttk.Frame(self.body, width=420)\n        self.side_host.pack_propagate(False)\n\n        self.canvas_host = ttk.Frame(self.body)\n        self.body.add(self.side_host, minsize=220, width=420, stretch="never")\n        self.body.add(self.canvas_host, minsize=500, stretch="always")\n'''
viewer = replace_once(viewer, old, new, "paned viewer body")
viewer_path.write_text(viewer, encoding="utf-8")

main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace('APP_NAME = "CMB DXF Viewer + Excel v3.18"', 'APP_NAME = "CMB DXF Viewer + Excel v3.19"', 1)

# Docked panel is already a child of PanedWindow; just ensure pane exists and set initial sash.
old = '''        host.configure(width=420)\n        if not host.winfo_ismapped():\n            host.pack(side="left", fill="y", before=self.viewer.canvas_host)\n        self.layer_docked = True\n        self.after(20, self.viewer.redraw)\n'''
new = '''        host.configure(width=420)\n        try:\n            panes = [str(p) for p in self.viewer.body.panes()]\n            if str(host) not in panes:\n                self.viewer.body.add(host, before=self.viewer.canvas_host, minsize=220, width=420, stretch="never")\n            self.after(40, lambda: self.viewer.body.sash_place(0, 420, 0))\n        except Exception:\n            pass\n        self.layer_docked = True\n        self.after(20, self.viewer.redraw)\n'''
main = replace_once(main, old, new, "restore dock pane")

old = '''        try:\n            self.viewer.side_host.pack_forget()\n        except Exception:\n            pass\n'''
new = '''        try:\n            self.viewer.body.forget(self.viewer.side_host)\n        except Exception:\n            pass\n'''
main = replace_once(main, old, new, "detach forget pane")

old = '''        try:\n            self.viewer.side_host.pack_forget()\n            for child in self.viewer.side_host.winfo_children():\n                child.destroy()\n        except Exception:\n            pass\n'''
new = '''        try:\n            self.viewer.body.forget(self.viewer.side_host)\n            for child in self.viewer.side_host.winfo_children():\n                child.destroy()\n        except Exception:\n            pass\n'''
main = replace_once(main, old, new, "hide forget pane")

main_path.write_text(main, encoding="utf-8")
print("v3.19 layout applied: draggable layer/canvas splitter")
