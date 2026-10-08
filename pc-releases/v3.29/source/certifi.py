"""
Internal compatibility shim for pyproj optional PROJ network CA bundle hook.

CMB DXF Viewer does not enable PROJ network access. pyproj imports a module
named certifi unconditionally and calls where() during initialization.
Returning an empty path tells PROJ to use system/default settings while keeping
the application fully offline.

This file is original project code and does not contain or redistribute the
certifi package or Mozilla CA bundle.
"""

__version__ = "cmb-offline-shim-1"

def where() -> str:
    return ""

def contents() -> str:
    return ""
