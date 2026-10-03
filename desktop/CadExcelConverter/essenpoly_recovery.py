from __future__ import annotations

from pathlib import Path


def _pairs(lines):
    out = []
    i = 0
    while i + 1 < len(lines):
        out.append((lines[i].strip(), lines[i + 1].strip()))
        i += 2
    return out


def _parse_int(value):
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def recover_essenpoly_polylines(input_path):
    """Recover embedded AcDbPolyline geometry from ESSENPOLY custom entities.

    This parser only reads the original ASCII DXF text. It does not alter the
    source file and does not depend on any proprietary DWG/DXF component.
    Malformed binary 310 groups are ignored because the usable polyline is
    stored again as ordinary 10/20 coordinate tags in the Embedded Object.

    The original entity color is also retained when it is explicitly stored
    as ACI (group 62) or true-color (group 420). If no explicit color exists,
    the Viewer can fall back to the DXF layer color.
    """
    path = Path(input_path)
    if path.suffix.lower() != ".dxf" or not path.is_file():
        return []

    raw = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    recovered = []
    i = 0

    while i + 1 < len(raw):
        if raw[i].strip() != "0" or raw[i + 1].strip() != "ESSENPOLY":
            i += 2
            continue

        start = i
        j = i + 2
        while j + 1 < len(raw):
            if raw[j].strip() == "0":
                break
            j += 2

        pairs = _pairs(raw[start:j])
        handle = ""
        layer = ""
        metadata = {}

        for code, value in pairs:
            if code == "5" and not handle:
                handle = value
            elif code == "8" and not layer:
                layer = value
            elif code in {str(n) for n in range(300, 310)} and value:
                metadata[f"ESSEN_{code}"] = value

        embedded = -1
        for idx, (code, value) in enumerate(pairs):
            if code == "101" and value == "Embedded Object":
                embedded = idx
                break

        polyline = -1
        if embedded >= 0:
            for idx in range(embedded + 1, len(pairs)):
                code, value = pairs[idx]
                if code == "100" and value == "AcDbPolyline":
                    polyline = idx
                    break

        # Prefer the embedded AcDbEntity color because that is what CAD uses
        # for the visible polyline. Fall back to the outer ESSENPOLY color.
        color_aci = None
        true_color = None
        if embedded >= 0:
            for code, value in pairs[embedded + 1:polyline if polyline >= 0 else len(pairs)]:
                if code == "62":
                    parsed = _parse_int(value)
                    if parsed not in (None, 0, 256):
                        color_aci = parsed
                elif code == "420":
                    parsed = _parse_int(value)
                    if parsed is not None:
                        true_color = parsed
        if color_aci is None and true_color is None:
            for code, value in pairs[:embedded if embedded >= 0 else len(pairs)]:
                if code == "62":
                    parsed = _parse_int(value)
                    if parsed not in (None, 0, 256):
                        color_aci = parsed
                        break
                elif code == "420":
                    parsed = _parse_int(value)
                    if parsed is not None:
                        true_color = parsed
                        break

        points = []
        if polyline >= 0:
            pending_x = None
            for code, value in pairs[polyline + 1:]:
                if code == "10":
                    try:
                        pending_x = float(value)
                    except Exception:
                        pending_x = None
                elif code == "20" and pending_x is not None:
                    try:
                        points.append((pending_x, float(value)))
                    except Exception:
                        pass
                    pending_x = None

        if layer and len(points) >= 2:
            recovered.append({
                "handle": handle,
                "layer": layer,
                "points": points,
                "attributes": metadata,
                "color_aci": color_aci,
                "true_color": true_color,
            })

        i = max(j, i + 2)

    return recovered
