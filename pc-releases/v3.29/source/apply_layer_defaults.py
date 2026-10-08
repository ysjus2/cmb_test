from pathlib import Path
p=Path("main.py")
s=p.read_text(encoding="utf8")
s=s.replace('from viewer import DXFViewer, build_scene', 'from viewer import DXFViewer, build_scene\nfrom layer_defaults import is_default_hidden',1)
assert 'if layer.name.strip() != "지번":' in s
s=s.replace('if layer.name.strip() != "지번":','if not is_default_hidden(layer.name):',1)
s=s.replace('v3.26','v3.27')
p.write_text(s,encoding="utf8")
