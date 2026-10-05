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

# Windows 10/11 inbox system runtime policy:
# Do not embed UCRT/API-set forwarder DLLs that are supplied by Windows itself.
# Keep VC runtime DLLs (VCRUNTIME/MSVCP) unless separately proven unnecessary,
# because they are not treated here as Windows-inbox components.
def _is_windows_inbox_binary(entry):
    dest_name = str(entry[0])
    base = PurePath(dest_name).name.lower()
    return base == "ucrtbase.dll" or base.startswith("api-ms-win-")

removed_windows_inbox = [entry[0] for entry in a.binaries if _is_windows_inbox_binary(entry)]
a.binaries = [entry for entry in a.binaries if not _is_windows_inbox_binary(entry)]
print("Excluded Windows 10/11 inbox DLLs from bundle:")
for name in sorted(removed_windows_inbox, key=str.lower):
    print("  ", name)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CMB_DXF_Viewer",
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
