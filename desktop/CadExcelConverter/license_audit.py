from __future__ import annotations

import importlib.metadata as md
import re
import sys
from collections import deque

# Final company build policy:
# - Commercial redistribution must be explicitly allowed.
# - Strong/weak copyleft, non-commercial, source-available, unknown, or custom
#   licenses are rejected unless explicitly reviewed and added here.
ALLOWED_MARKERS = (
    "mit",
    "bsd",
    "apache",
    "python software foundation",
    "psf",
    "isc",
    "zlib",
)

DENIED_MARKERS = (
    "gpl",
    "agpl",
    "lgpl",
    "mozilla public license",
    "mpl",
    "non-commercial",
    "noncommercial",
    "creative commons",
    "sspl",
    "business source",
    "commons clause",
)

# Runtime roots. PyInstaller is a build tool, not a runtime dependency root.
RUNTIME_ROOTS = ("ezdxf", "openpyxl", "pyproj")

def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()

def dist_map():
    out = {}
    for d in md.distributions():
        name = d.metadata.get("Name")
        if name:
            out[normalize_name(name)] = d
    return out

def requirement_name(req: str) -> str:
    # enough for standard package metadata requirements
    name = re.split(r"[ ;(<>=!~\[]", req, maxsplit=1)[0].strip()
    return normalize_name(name)

def closure(installed):
    seen = set()
    q = deque(normalize_name(x) for x in RUNTIME_ROOTS)
    while q:
        name = q.popleft()
        if name in seen:
            continue
        seen.add(name)
        d = installed.get(name)
        if d is None:
            raise RuntimeError(f"Required runtime package is not installed: {name}")
        for req in (d.requires or []):
            # Ignore optional extras only; unconditional and environment-marker
            # dependencies installed for Windows remain audited if present.
            dep = requirement_name(req)
            if dep and dep in installed and dep not in seen:
                q.append(dep)
    return seen

def license_text(d) -> str:
    parts = []
    meta = d.metadata
    for key in ("License-Expression", "License"):
        val = meta.get(key)
        if val:
            parts.append(val)
    for classifier in meta.get_all("Classifier", []):
        if classifier.startswith("License ::"):
            parts.append(classifier)
    return " | ".join(parts).strip()

def classify(text: str):
    low = text.lower()
    if any(x in low for x in DENIED_MARKERS):
        return "DENY"
    if any(x in low for x in ALLOWED_MARKERS):
        return "ALLOW"
    return "UNKNOWN"

def main():
    installed = dist_map()
    runtime = closure(installed)

    failures = []
    rows = []
    for name in sorted(runtime):
        d = installed[name]
        version = d.version
        lic = license_text(d)
        verdict = classify(lic)
        rows.append((name, version, verdict, lic))
        if verdict != "ALLOW":
            failures.append((name, version, verdict, lic))

    print("=== COMPANY RUNTIME LICENSE AUDIT ===")
    for name, version, verdict, lic in rows:
        print(f"{verdict:7} {name}=={version} :: {lic or 'NO LICENSE METADATA'}")

    print("\nPolicy: runtime dependency closure must be MIT/BSD/Apache/PSF/ISC/Zlib.")
    print("Denied: GPL/AGPL/LGPL/MPL/non-commercial/source-available/unknown.")

    if failures:
        print("\nLICENSE AUDIT FAILED:")
        for name, version, verdict, lic in failures:
            print(f" - {name}=={version}: {verdict}: {lic or 'NO LICENSE METADATA'}")
        return 2

    print("\nLICENSE AUDIT PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
