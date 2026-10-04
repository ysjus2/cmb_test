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


def _collect_xdata(pairs, start_index=0):
    """Collect XDATA groups as APPID -> readable tag strings."""
    result = {}
    current = None
    for code, value in pairs[start_index:]:
        if code == "1001":
            current = value.strip()
            if current:
                result.setdefault(current, [])
            continue
        if current is None:
            continue
        if code == "1002":
            # Structure braces add no useful field value to Excel.
            continue
        if code.startswith("10") and value.strip():
            result[current].append(f"{code}:{value.strip()}")
    return {k: v for k, v in result.items() if v}


def recover_essenpoly_polylines(input_path):
    """Recover embedded AcDbPolyline geometry from ESSENPOLY custom entities.

    This parser only reads the original ASCII DXF text. It does not alter the
    source file and does not depend on any proprietary DWG/DXF component.
    Malformed binary 310 groups are ignored because the usable polyline is
    stored again as ordinary 10/20 coordinate tags in the Embedded Object.

    Original entity color, custom 300-309 fields and XDATA are retained so the
    same recovered cable can be rendered in the Viewer and exported to Excel.
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
                # Preserve every custom ESSEN field. Repeated codes are joined.
                key = f"ESSEN_{code}"
                if key in metadata and metadata[key] != value:
                    metadata[key] = f"{metadata[key]} | {value}"
                else:
                    metadata[key] = value

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
        xdata_start = len(pairs)
        if polyline >= 0:
            pending_x = None
            for idx in range(polyline + 1, len(pairs)):
                code, value = pairs[idx]
                if code == "1001":
                    xdata_start = idx
                    break
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

        xdata = _collect_xdata(pairs, xdata_start)

        if layer and len(points) >= 2:
            recovered.append({
                "handle": handle,
                "layer": layer,
                "points": points,
                "attributes": metadata,
                "xdata": xdata,
                "color_aci": color_aci,
                "true_color": true_color,
            })

        i = max(j, i + 2)

    return recovered
