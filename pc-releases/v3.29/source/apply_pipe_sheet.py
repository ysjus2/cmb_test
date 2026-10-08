from pathlib import Path
p=Path("main.py")
s=p.read_text(encoding="utf8").replace("v3.28","v3.29")
p.write_text(s,encoding="utf8")
