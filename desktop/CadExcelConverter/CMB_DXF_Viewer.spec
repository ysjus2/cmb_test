# -*- mode: python ; coding: utf-8 -*-
from pathlib import PurePath

from PyInstaller.utils.hooks import collect_all

pyproj_datas, pyproj_binaries, pyproj_hidden = collect_all("pyproj")
ezdxf_datas, ezdxf_binaries, ezdxf_hidden = collect_all("ezdxf")

all_datas = pyproj_datas + ezdxf_datas
all_binaries = pyproj_binaries + ezdxf_binaries
all_hidden = pyproj_hidden + ezdxf_hidden

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Runtime policy for company Windows 10/11 PCs:
# 1) UCRT/API-set DLLs are provided by Windows itself.
# 2) VC++ v14 x64 Runtime is a machine prerequisite and is installed from the
#    official Microsoft VC Redistributable when missing (see ensure_vcredist.ps1).
# Therefore none of these Microsoft runtime DLLs are embedded in the app EXE.
def _is_system_or_prereq_runtime(entry):
    dest_name = str(entry[0])
    base = PurePath(dest_name).name.lower()
    if base == "ucrtbase.dll" or base.startswith("api-ms-win-"):
        return True
    if base.startswith("vcruntime140") and base.endswith(".dll"):
        return True
    if base.startswith("msvcp140") and base.endswith(".dll"):
        return True
    return False

removed_runtime = [entry[0] for entry in a.binaries if _is_system_or_prereq_runtime(entry)]
a.binaries = [entry for entry in a.binaries if not _is_system_or_prereq_runtime(entry)]
print("Excluded Windows/VC prerequisite runtime DLLs from bundle:")
for name in sorted(removed_runtime, key=str.lower):
    print("  ", name)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CMB_DXF_Viewer_App",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
