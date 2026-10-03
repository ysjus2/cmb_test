from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import ezdxf
from ezdxf import recover
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from pyproj import Transformer

LAYER_HEADERS = [
    "ENTITY_TYPE","ENTITY_ID","BLOCK_NAME","SEQ",
    "CAD_X","CAD_Y","경도","위도",
    "길이","TEXT","ATTRIBUTES","XDATA"
]

@dataclass
class LayerInfo:
    name: str
    count: int
    types: str

@dataclass
class ConversionStats:
    layers: int = 0
    entities: int = 0
    rows: int = 0
    skipped: int = 0

def _norm(s):
    return (s or "").strip()

def _attributes(entity):
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

def _entity_text(entity):
    typ = entity.dxftype()
    try:
        if typ == "TEXT":
            return _norm(entity.dxf.text)
        if typ == "MTEXT":
            return _norm(entity.plain_text())
    except Exception:
        pass
    return ""

def _entity_points(entity):
    typ = entity.dxftype()
    try:
        if typ == "INSERT":
            p = entity.dxf.insert
            return [(float(p.x), float(p.y))]
        if typ == "POINT":
            p = entity.dxf.location
            return [(float(p.x), float(p.y))]
        if typ in {"TEXT","MTEXT"}:
            p = entity.dxf.insert
            return [(float(p.x), float(p.y))]
        if typ == "LWPOLYLINE":
            return [(float(x), float(y)) for x, y, *_ in entity.get_points("xy")]
        if typ == "POLYLINE":
            return [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
        if typ == "LINE":
            s, e = entity.dxf.start, entity.dxf.end
            return [(float(s.x), float(s.y)), (float(e.x), float(e.y))]
        if typ in {"CIRCLE","ARC"}:
            p = entity.dxf.center
            return [(float(p.x), float(p.y))]
    except Exception:
        pass
    return []

def _length(points):
    if len(points) < 2:
        return 0.0
    return sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(points, points[1:]))

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
        for r in range(2, min(ws.max_row, 300) + 1):
            sample.append(len(str(ws.cell(r, i).value or "")))
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(42, max(sample)))

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
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        temp.cleanup()
        raise RuntimeError("ODA DWG→DXF 변환 실패: " + (proc.stderr or proc.stdout or str(proc.returncode)))
    matches = list(dst.rglob("*.dxf")) + list(dst.rglob("*.DXF"))
    if not matches:
        temp.cleanup()
        raise RuntimeError("ODA 변환 후 DXF 파일을 찾지 못했습니다.")
    return matches[0], temp

def _open_cad(input_path, oda_exe=None):
    src = Path(input_path)
    temp = None
    if src.suffix.lower() == ".dwg":
        src, temp = dwg_to_dxf(src, oda_exe)
    elif src.suffix.lower() != ".dxf":
        raise ValueError("지원 형식은 DWG 또는 DXF입니다.")
    return src, temp

def _sanitize_binary_tags(src, log):
    raw = Path(src).read_bytes().splitlines(keepends=True)
    out = []
    fixed = 0
    i = 0
    while i < len(raw):
        code_line = raw[i]
        if i + 1 >= len(raw):
            out.append(code_line)
            break
        value_line = raw[i + 1]
        try:
            code = int(code_line.strip().decode("ascii", errors="strict"))
        except Exception:
            out.append(code_line)
            i += 1
            continue

        if 310 <= code <= 319:
            value = value_line.strip()
            valid = bool(value) and len(value) % 2 == 0 and all(
                ch in b"0123456789abcdefABCDEF" for ch in value
            )
            if not valid:
                out.append(code_line)
                newline = b"\r\n" if value_line.endswith(b"\r\n") else b"\n"
                out.append(b"00" + newline)
                fixed += 1
                i += 2
                continue

        out.append(code_line)
        out.append(value_line)
        i += 2

    temp = tempfile.NamedTemporaryFile(
        prefix="cad_sanitized_",
        suffix=".dxf",
        delete=False,
    )
    temp.write(b"".join(out))
    temp.close()
    log(f"비정상 바이너리 태그 {fixed}건 정리")
    return Path(temp.name)

def _read_dxf_resilient(src, log):
    first_error = None
    recover_error = None
    explore_error = None

    try:
        log("DXF 일반 읽기 시도")
        return ezdxf.readfile(str(src))
    except Exception as e:
        first_error = e
        log(f"일반 읽기 실패: {e}")

    try:
        log("DXF recover 모드로 재시도")
        doc, auditor = recover.readfile(str(src), errors="ignore")
        if getattr(auditor, "has_errors", False):
            log(f"recover 경고: {len(getattr(auditor, 'errors', []))}건")
        log("recover 모드 읽기 성공")
        return doc
    except Exception as e:
        recover_error = e
        log(f"recover 실패: {e}")

    try:
        log("DXF explore 모드로 재시도")
        doc, auditor = recover.explore(str(src), errors="ignore")
        if getattr(auditor, "has_errors", False):
            log(f"explore 경고: {len(getattr(auditor, 'errors', []))}건")
        log("explore 모드 읽기 성공")
        return doc
    except Exception as e:
        explore_error = e
        log(f"explore 실패: {e}")

    sanitized = None
    try:
        log("바이너리 태그 사전 정리 후 최종 재시도")
        sanitized = _sanitize_binary_tags(src, log)
        try:
            doc, auditor = recover.readfile(str(sanitized), errors="ignore")
            log("정리본 recover 읽기 성공")
            return doc
        except Exception:
            doc, auditor = recover.explore(str(sanitized), errors="ignore")
            log("정리본 explore 읽기 성공")
            return doc
    except Exception as sanitize_error:
        raise RuntimeError(
            "DXF를 읽지 못했습니다. "
            f"일반={first_error} / recover={recover_error} / "
            f"explore={explore_error} / 정리후={sanitize_error}. "
            "이 경우 원본 DXF 파일을 직접 확인해야 합니다."
        )
    finally:
        if sanitized is not None:
            try:
                sanitized.unlink(missing_ok=True)
            except Exception:
                pass

def scan_layers(input_path, oda_exe=None, log: Callable[[str], None] | None = None):
    log = log or (lambda msg: None)
    src, temp = _open_cad(input_path, oda_exe)
    try:
        log(f"CAD 레이어 스캔: {src}")
        doc = _read_dxf_resilient(src, log)
        counts = {}
        types = {}
        for ent in doc.modelspace():
            layer = _norm(getattr(ent.dxf, "layer", "0")) or "0"
            counts[layer] = counts.get(layer, 0) + 1
            types.setdefault(layer, set()).add(ent.dxftype())
        result = []
        for name in sorted(counts, key=lambda x: x.lower()):
            result.append(LayerInfo(name, counts[name], ", ".join(sorted(types[name]))))
        return result
    finally:
        if temp is not None:
            temp.cleanup()

def _safe_sheet_name(layer_name, used):
    base = re.sub(r'[\\/*?:\[\]]', "_", layer_name).strip() or "LAYER"
    base = base[:31]
    name = base
    i = 2
    while name.lower() in used:
        suffix = f"_{i}"
        name = base[:31-len(suffix)] + suffix
        i += 1
    used.add(name.lower())
    return name

def convert_selected_layers(
    input_path,
    output_path,
    selected_layers,
    source_epsg=5174,
    oda_exe=None,
    log: Callable[[str], None] | None = None,
):
    log = log or (lambda msg: None)
    selected = list(dict.fromkeys(selected_layers))
    if not selected:
        raise ValueError("추출할 레이어를 하나 이상 선택해주세요.")

    src, temp = _open_cad(input_path, oda_exe)
    try:
        log(f"CAD 읽기: {src}")
        doc = _read_dxf_resilient(src, log)
        msp = doc.modelspace()
        transformer = Transformer.from_crs(
            f"EPSG:{source_epsg}",
            "EPSG:4326",
            always_xy=True,
        )

        grouped = {name: [] for name in selected}
        entity_counts = {name: 0 for name in selected}
        stats = ConversionStats(layers=len(selected))

        for ent in msp:
            layer = _norm(getattr(ent.dxf, "layer", "0")) or "0"
            if layer not in grouped:
                continue

            entity_counts[layer] += 1
            stats.entities += 1
            typ = ent.dxftype()
            handle = _norm(getattr(ent.dxf, "handle", ""))
            block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else ""
            attrs = _joined_attrs(_attributes(ent))
            xdata = _xdata_text(doc, ent)
            text = _entity_text(ent)
            points = _entity_points(ent)
            length = _length(points)

            if points:
                for seq, (x, y) in enumerate(points, 1):
                    try:
                        lon, lat = transformer.transform(x, y)
                    except Exception:
                        lon, lat = None, None
                    grouped[layer].append([
                        typ, handle, block, seq,
                        x, y, lon, lat,
                        length, text, attrs, xdata,
                    ])
                    stats.rows += 1
            else:
                grouped[layer].append([
                    typ, handle, block, 0,
                    None, None, None, None,
                    0, text, attrs, xdata,
                ])
                stats.rows += 1
                stats.skipped += 1

        wb = Workbook()
        wb.remove(wb.active)
        used = set()
        index_rows = []

        for layer in selected:
            sheet_name = _safe_sheet_name(layer, used)
            ws = wb.create_sheet(sheet_name)
            _write_sheet(ws, LAYER_HEADERS, grouped[layer])
            index_rows.append([
                layer,
                sheet_name,
                entity_counts[layer],
                len(grouped[layer]),
            ])

        idx = wb.create_sheet("LAYER_INDEX", 0)
        _write_sheet(
            idx,
            ["원본레이어","Excel시트","객체수","출력행수"],
            index_rows,
        )

        info = wb.create_sheet("INFO")
        _write_sheet(info, ["항목","값"], [
            ["원본파일", str(input_path)],
            ["원본좌표계", f"EPSG:{source_epsg}"],
            ["출력좌표계", "EPSG:4326 (WGS84)"],
            ["선택레이어수", stats.layers],
            ["대상객체수", stats.entities],
            ["출력행수", stats.rows],
            ["좌표없는객체행", stats.skipped],
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

# Backward-compatible wrapper: export all discovered layers.
def convert_file(input_path, output_path, source_epsg=5174, oda_exe=None, log=None):
    layers = scan_layers(input_path, oda_exe, log)
    return convert_selected_layers(
        input_path,
        output_path,
        [x.name for x in layers],
        source_epsg,
        oda_exe,
        log,
    )
