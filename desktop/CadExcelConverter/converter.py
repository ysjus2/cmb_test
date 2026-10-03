from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import ezdxf
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from pyproj import Transformer

FACILITY_HEADERS = ["구분","시설ID","블록명","CAD레이어","CAD_X","CAD_Y","경도","위도","원본속성","비고"]
EQUIPMENT_HEADERS = ["구분","장비ID","블록명","CAD레이어","CAD_X","CAD_Y","경도","위도","셀정보","OBJECT","LOCATION","FIBER","비고"]
FIBER_HEADERS = ["선로ID","순번","경도","위도","CAD_X","CAD_Y","케이블명","케이블ID","연결정보","길이","CAD레이어"]
COAX_HEADERS = FIBER_HEADERS[:]
CELL_HEADERS = ["셀명","셀번호","상위국사","상향포트","하향포트","주소","전주번호","경도","위도","셀구분","비고"]

@dataclass
class ConversionStats:
    facilities: int = 0
    equipment: int = 0
    fiber_points: int = 0
    coax_points: int = 0
    cells: int = 0
    skipped: int = 0

def _norm(s):
    return (s or "").strip()

def _upper(s):
    return _norm(s).upper()

def _attributes(entity):
    out = {}
    if entity.dxftype() == "INSERT":
        for a in getattr(entity, "attribs", []):
            out[_upper(a.dxf.tag)] = _norm(a.dxf.text)
    return out

def _joined_attrs(attrs):
    return " | ".join(f"{k}={v}" for k, v in attrs.items() if v)

def _pick(attrs, *keys):
    for key in keys:
        v = attrs.get(key.upper(), "")
        if v:
            return v
    return ""

def _classify_insert(layer, block):
    text = f"{_upper(layer)} {_upper(block)}"
    if any(k in text for k in ["POLE", "전주"]):
        return "FACILITY", "전주"
    if any(k in text for k in ["MANHOLE", "HANDHOLE", "MH-", "맨홀", "수공"]):
        return "FACILITY", "맨홀"
    rules = [
        (["CLOSURE", "클로저"], "광클로저"),
        (["CENTER", "RACK", "CABINET", "광센터"], "광센터"),
        (["_ONU", " ONU", "ONU-"], "ONU"),
        (["TAPOFF", "TAP-OFF", "_TAP", " TAP"], "TAP"),
        (["PASSIVE", "수동소자"], "수동소자"),
        (["_AMP", " AMP", "TBA"], "AMP-TBA"),
        (["NODE", "NODE-"], "NODE"),
    ]
    for keys, label in rules:
        if any(k in text for k in keys):
            return "EQUIPMENT", label
    if layer.upper().startswith("CN_") or block:
        return "EQUIPMENT", block or "장비"
    return "SKIP", ""

def _classify_line(layer):
    t = _upper(layer)
    if any(k in t for k in ["CN_F_CABLE", "FOC", "FIBER", "OPTIC", "광"]):
        return "FIBER"
    if any(k in t for k in ["CN_C_CABLE", "500F", "COAX", "동축"]):
        return "COAX"
    return "SKIP"

def _polyline_points(entity):
    typ = entity.dxftype()
    if typ == "LWPOLYLINE":
        return [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
    if typ == "POLYLINE":
        return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    if typ == "LINE":
        s, e = entity.dxf.start, entity.dxf.end
        return [(float(s.x), float(s.y)), (float(e.x), float(e.y))]
    return []

def _length(points):
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))

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

def _cable_meta(doc, entity):
    xdata = _xdata_text(doc, entity)
    cable_name = ""
    cable_id = ""
    connection = ""
    for token in [p.strip() for p in xdata.split("|") if p.strip()]:
        u = token.upper()
        if not cable_name and ("/" in token or "FC" in u or "C/" in u):
            cable_name = token
        elif not cable_id and (u.startswith("FC") or u.startswith("CC")):
            cable_id = token
        elif not connection:
            connection = token
    return cable_name, cable_id, connection

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
        sample = [len(str(header)) + 2]
        for r in range(2, min(ws.max_row, 250) + 1):
            sample.append(len(str(ws.cell(r, i).value or "")))
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(38, max(sample)))

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
        raise RuntimeError("DWG 변환에는 ODA File Converter가 필요합니다. ODAFileConverter.exe 경로를 지정해주세요.")
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

def convert_file(input_path, output_path, source_epsg=5174, oda_exe=None, log=None):
    log = log or (lambda msg: None)
    src = Path(input_path)
    temp = None
    try:
        if src.suffix.lower() == ".dwg":
            log("DWG 감지: 로컬 ODA 변환 시작")
            src, temp = dwg_to_dxf(src, oda_exe)
        elif src.suffix.lower() != ".dxf":
            raise ValueError("지원 형식은 DWG 또는 DXF입니다.")

        log(f"DXF 읽기: {src}")
        doc = ezdxf.readfile(str(src))
        msp = doc.modelspace()
        transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)

        facilities, equipment, fibers, coax, cells = [], [], [], [], []
        stats = ConversionStats()

        for ent in msp:
            typ = ent.dxftype()
            layer = _norm(getattr(ent.dxf, "layer", ""))
            handle = _norm(getattr(ent.dxf, "handle", ""))

            if typ == "INSERT":
                block = _norm(getattr(ent.dxf, "name", ""))
                kind, label = _classify_insert(layer, block)
                if kind == "SKIP":
                    stats.skipped += 1
                    continue
                p = ent.dxf.insert
                x, y = float(p.x), float(p.y)
                lon, lat = transformer.transform(x, y)
                attrs = _attributes(ent)

                if kind == "FACILITY":
                    facilities.append([label, handle, block, layer, x, y, lon, lat, _joined_attrs(attrs), ""])
                    stats.facilities += 1
                else:
                    equipment.append([
                        label, handle, block, layer, x, y, lon, lat,
                        _pick(attrs, "CELL", "CELLINFO", "셀정보"),
                        _pick(attrs, "OBJECT"),
                        _pick(attrs, "LOCATION", "LOC"),
                        _pick(attrs, "FIBER", "FIBERINFO"),
                        ""
                    ])
                    stats.equipment += 1

                    if label == "ONU":
                        cell_no = _pick(attrs, "CELLNO", "CELL_NO", "셀번호")
                        cell_name = _pick(attrs, "CELLNAME", "CELL_NAME", "셀명")
                        if cell_no or cell_name:
                            cells.append([
                                cell_name, cell_no,
                                _pick(attrs, "OFFICE", "상위국사"),
                                _pick(attrs, "UPPORT", "상향포트"),
                                _pick(attrs, "DOWNPORT", "하향포트"),
                                _pick(attrs, "ADDRESS", "주소"),
                                _pick(attrs, "POLE", "전주번호"),
                                lon, lat, "일반", ""
                            ])
                            stats.cells += 1

            elif typ in {"LWPOLYLINE", "POLYLINE", "LINE"}:
                line_kind = _classify_line(layer)
                if line_kind == "SKIP":
                    continue
                pts = _polyline_points(ent)
                if len(pts) < 2:
                    stats.skipped += 1
                    continue
                cable_name, cable_id, connection = _cable_meta(doc, ent)
                total_len = _length(pts)
                rows = fibers if line_kind == "FIBER" else coax
                for seq, (x, y) in enumerate(pts, 1):
                    lon, lat = transformer.transform(x, y)
                    rows.append([handle, seq, lon, lat, x, y, cable_name, cable_id, connection, total_len, layer])
                if line_kind == "FIBER":
                    stats.fiber_points += len(pts)
                else:
                    stats.coax_points += len(pts)

        wb = Workbook()
        ws = wb.active
        ws.title = "CELL"
        _write_sheet(ws, CELL_HEADERS, cells)

        for name, headers, rows in [
            ("FACILITY", FACILITY_HEADERS, facilities),
            ("EQUIPMENT", EQUIPMENT_HEADERS, equipment),
            ("FIBER", FIBER_HEADERS, fibers),
            ("COAX", COAX_HEADERS, coax),
        ]:
            _write_sheet(wb.create_sheet(name), headers, rows)

        info = wb.create_sheet("INFO")
        _write_sheet(info, ["항목", "값"], [
            ["원본파일", str(input_path)],
            ["원본좌표계", f"EPSG:{source_epsg}"],
            ["출력좌표계", "EPSG:4326 (WGS84)"],
            ["시설", stats.facilities],
            ["장비", stats.equipment],
            ["광선로 좌표점", stats.fiber_points],
            ["동축선로 좌표점", stats.coax_points],
            ["CELL", stats.cells],
            ["외부전송", "없음 - 로컬 처리"],
        ])

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out)
        log(f"완료: {out}")
        return stats
    finally:
        if temp is not None:
            temp.cleanup()
