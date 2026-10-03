from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import ezdxf
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from pyproj import Transformer

GENERIC_HEADERS = [
    "레이어","엔티티종류","핸들","블록명","텍스트","순번",
    "CAD_X","CAD_Y","경도","위도","길이","속성","XDATA","비고"
]

@dataclass
class ConversionStats:
    layers: int = 0
    rows: int = 0
    entities: int = 0
    skipped: int = 0

def _norm(s):
    return (s or "").strip()

def _attrs(entity):
    out = {}
    if entity.dxftype() == "INSERT":
        for a in getattr(entity, "attribs", []):
            out[_norm(a.dxf.tag)] = _norm(a.dxf.text)
    return out

def _joined_attrs(attrs):
    return " | ".join(f"{k}={v}" for k, v in attrs.items() if v)

def _xdata_text(doc, entity):
    chunks = []
    try:
        for appid in doc.appids:
            name = appid.dxf.name
            try:
                tags = entity.get_xdata(name)
            except Exception:
                continue
            for tag in tags:
                if isinstance(tag.value, str) and tag.value.strip():
                    chunks.append(tag.value.strip())
    except Exception:
        pass
    return " | ".join(dict.fromkeys(chunks))

def _safe_sheet_name(name, used):
    base = re.sub(r'[:\\/?*\[\]]', '_', _norm(name)) or "LAYER"
    base = base[:31]
    candidate = base
    n = 2
    while candidate.lower() in used:
        suffix = f"_{n}"
        candidate = (base[:31-len(suffix)] + suffix)
        n += 1
    used.add(candidate.lower())
    return candidate

def _write_sheet(ws, headers, rows):
    ws.append(headers)
    fill = PatternFill("solid", fgColor="1F4E78")
    for c in ws[1]:
        c.font = Font(color="FFFFFF", bold=True)
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center")
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, header in enumerate(headers, 1):
        widths = [len(str(header)) + 2]
        for r in range(2, min(ws.max_row, 250) + 1):
            widths.append(len(str(ws.cell(r, i).value or "")))
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(42, max(widths)))

def _find_oda():
    candidates = [
        os.environ.get("ODA_FILE_CONVERTER"),
        r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
        r"C:\Program Files\ODAFileConverter\ODAFileConverter.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

def dwg_to_dxf(dwg_path, oda_exe=None):
    oda = oda_exe or _find_oda()
    if not oda:
        raise RuntimeError("DWG 파일을 읽으려면 ODA File Converter가 필요합니다. ODAFileConverter.exe 경로를 지정해주세요.")
    temp = tempfile.TemporaryDirectory(prefix="cad_excel_")
    src = Path(temp.name) / "in"
    dst = Path(temp.name) / "out"
    src.mkdir()
    dst.mkdir()
    shutil.copy2(dwg_path, src / Path(dwg_path).name)
    cmd = [oda, str(src), str(dst), "ACAD2018", "DXF", "0", "1", "*.dwg"]
    proc = subprocess.run(cmd, capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        temp.cleanup()
        raise RuntimeError("ODA DWG→DXF 변환 실패: " + (proc.stderr or proc.stdout or str(proc.returncode)))
    matches = list(dst.rglob("*.dxf")) + list(dst.rglob("*.DXF"))
    if not matches:
        temp.cleanup()
        raise RuntimeError("ODA 변환 후 DXF 파일을 찾지 못했습니다.")
    return matches[0], temp

def _open_as_dxf(input_path, oda_exe=None):
    src = Path(input_path)
    temp = None
    if src.suffix.lower() == ".dwg":
        src, temp = dwg_to_dxf(src, oda_exe)
    elif src.suffix.lower() != ".dxf":
        raise ValueError("지원 형식은 DWG 또는 DXF입니다.")
    return src, temp

def list_layers(input_path, oda_exe=None):
    src, temp = _open_as_dxf(input_path, oda_exe)
    try:
        doc = ezdxf.readfile(str(src))
        counts = {}
        for ent in doc.modelspace():
            layer = _norm(getattr(ent.dxf, "layer", "")) or "0"
            counts[layer] = counts.get(layer, 0) + 1
        return sorted(counts.items(), key=lambda x: x[0].lower())
    finally:
        if temp is not None:
            temp.cleanup()

def _points_for_entity(entity):
    typ = entity.dxftype()
    if typ == "INSERT":
        p = entity.dxf.insert
        return [(float(p.x), float(p.y))]
    if typ == "POINT":
        p = entity.dxf.location
        return [(float(p.x), float(p.y))]
    if typ == "TEXT":
        p = entity.dxf.insert
        return [(float(p.x), float(p.y))]
    if typ == "MTEXT":
        p = entity.dxf.insert
        return [(float(p.x), float(p.y))]
    if typ == "CIRCLE":
        p = entity.dxf.center
        return [(float(p.x), float(p.y))]
    if typ == "ARC":
        p = entity.dxf.center
        return [(float(p.x), float(p.y))]
    if typ == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [(float(s.x), float(s.y)), (float(e.x), float(e.y))]
    if typ == "LWPOLYLINE":
        return [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
    if typ == "POLYLINE":
        return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    return []

def _entity_text(entity):
    typ = entity.dxftype()
    if typ == "TEXT":
        return _norm(entity.dxf.text)
    if typ == "MTEXT":
        try:
            return _norm(entity.plain_text())
        except Exception:
            return _norm(getattr(entity.dxf, "text", ""))
    return ""

def _entity_length(points):
    if len(points) < 2:
        return 0.0
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))

def convert_file(input_path, output_path, source_epsg=5174, oda_exe=None, selected_layers=None, log=None):
    log = log or (lambda msg: None)
    src, temp = _open_as_dxf(input_path, oda_exe)
    try:
        log(f"DXF 읽기: {src}")
        doc = ezdxf.readfile(str(src))
        msp = doc.modelspace()
        transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)

        selected = set(selected_layers or [])
        if not selected:
            selected = {(_norm(getattr(ent.dxf, "layer", "")) or "0") for ent in msp}

        rows_by_layer = {layer: [] for layer in selected}
        stats = ConversionStats(layers=len(selected))

        for ent in msp:
            layer = _norm(getattr(ent.dxf, "layer", "")) or "0"
            if layer not in selected:
                continue

            typ = ent.dxftype()
            handle = _norm(getattr(ent.dxf, "handle", ""))
            block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else ""
            text = _entity_text(ent)
            attrs = _joined_attrs(_attrs(ent))
            xdata = _xdata_text(doc, ent)
            points = _points_for_entity(ent)
            length = _entity_length(points)

            if not points:
                rows_by_layer[layer].append([
                    layer, typ, handle, block, text, 0,
                    "", "", "", "", length, attrs, xdata, "좌표 미지원 엔티티"
                ])
                stats.rows += 1
                stats.entities += 1
                stats.skipped += 1
                continue

            for seq, (x, y) in enumerate(points, 1):
                lon, lat = transformer.transform(x, y)
                rows_by_layer[layer].append([
                    layer, typ, handle, block, text, seq,
                    x, y, lon, lat, length, attrs, xdata, ""
                ])
                stats.rows += 1
            stats.entities += 1

        wb = Workbook()
        wb.remove(wb.active)
        used = set()
        index_rows = []

        for layer in sorted(selected, key=str.lower):
            sheet_name = _safe_sheet_name(layer, used)
            ws = wb.create_sheet(sheet_name)
            _write_sheet(ws, GENERIC_HEADERS, rows_by_layer.get(layer, []))
            index_rows.append([layer, sheet_name, len(rows_by_layer.get(layer, []))])

        info = wb.create_sheet(_safe_sheet_name("INFO", used), 0)
        _write_sheet(info, ["항목", "값"], [
            ["원본파일", str(input_path)],
            ["원본좌표계", f"EPSG:{source_epsg}"],
            ["출력좌표계", "EPSG:4326 (WGS84)"],
            ["선택레이어수", len(selected)],
            ["엔티티수", stats.entities],
            ["출력행수", stats.rows],
            ["외부전송", "없음 - 로컬 처리"],
        ])

        index = wb.create_sheet(_safe_sheet_name("LAYER_INDEX", used), 1)
        _write_sheet(index, ["CAD레이어", "Excel시트", "출력행수"], index_rows)

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out)
        log(f"완료: {out}")
        return stats
    finally:
        if temp is not None:
            temp.cleanup()
