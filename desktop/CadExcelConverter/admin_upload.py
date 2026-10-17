from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from pyproj import Transformer

from drawing_identity import drawing_code
from server_client_windows import CMBServerClient
from backup_v2 import enrich_payload_v2

GROUPS = ("FIBER", "COAX", "CONDUIT", "POLE", "USER")
MANAGED_ITEMS = GROUPS
# 전체 버튼은 광 + 동축 + 관로만 업로드한다.
# POLE/USER MEMO는 선택 업로드로 유지한다.
FULL_UPLOAD_ITEMS = ("FIBER", "COAX", "CONDUIT")


def classify_entity(e):
    # 서버 업로드 분류는 실제 CAD 레이어명을 기준으로 단순하게 고정한다.
    layer = str(e.layer or "").strip().upper()
    block = str(e.block_name or "").strip().upper()
    text = f"{layer} {block}"

    # 지형/배경 및 등록정보/주석(-Anno) 레이어는 온라인 서버 업로드 대상이 아니다.
    # -Anno는 광/동축 기기 속성 표시용 등록정보이므로 지도 객체로 만들지 않는다.
    if (
        layer.startswith("TS_")
        or layer == "TL_SCCO_SIG"
        or "ANNO" in layer
        or "ANNO" in block
        or layer.startswith("CN_L_POLEMAP_")
    ):
        return None

    # ONU는 현장 운용 기준상 동축 기기로 관리한다.
    # 레이어명이 CN_F_* 계열이더라도 ONU 표기가 있으면 COAX가 우선이다.
    if "ONU" in text:
        return "COAX"

    # 광선로 / 광장비
    # 광기기는 레이어가 일반명이어도 실제 block명이 CLOSURE/TERMINAL/
    # CENTER/FOSC/FDF이면 반드시 FIBER 그룹으로 저장한다.
    fiber_device_block = (
        block.startswith("CLOSURE")
        or block.startswith("TERMINAL")
        or block.startswith("CENTER")
        or block.startswith("FOSC")
        or block.startswith("FDF")
    )
    if (
        layer.startswith("CN_F_")
        or fiber_device_block
        or "F_CABLE" in text
        or "FIBER" in text
        or "FOC" in text
        or "OPTIC" in text
        or "광" in text
    ):
        return "FIBER"

    # 관로/맨홀/핸드홀은 CN_L_POLE 계열 이름을 사용하더라도 CONDUIT가 우선이다.
    if (
        layer.startswith("CN_L_POLE_MANHOLE")
        or layer.startswith("CN_L_POLE_HANDHOLE")
        or layer.startswith("CN_L_POLE_LINE_")
        or any(k in text for k in ("CONDUIT", "MANHOLE", "HANDHOLE", "관로", "맨홀", "핸드홀"))
    ):
        return "CONDUIT"

    # 실제 전주 위치만 저장한다. Drop은 가상점이고 TEL 등은 이번 전주 표시에 제외한다.
    entity_type = str(e.entity_type or "").strip().upper()
    actual_pole_layers = {
        "CN_L_POLE_POLE-JOINT",
        "CN_L_POLE_POLE-JOINT-TRS",
        "CN_L_POLE_POLE-CATV",
        "CN_L_POLE_POLE-STEEL",
        "CN_L_POLE_POLE-CONCRETE",
    }
    if entity_type == "INSERT" and layer in actual_pole_layers:
        return "POLE"

    # 동축선로 / 동축장비
    if (
        layer.startswith("CN_C_")
        or any(k in text for k in (
            "C_CABLE", "COAX", "RG06", "RG11", "PFC", "AMP", "TAP",
            "PASSIVE", "POWER", "CONNECTOR", "동축", "증폭", "분기",
        ))
    ):
        return "COAX"

    # USER 도형/건물은 카카오맵 기반 온라인 Viewer에서 사용하지 않는다.
    # 현장 공유용 USER MEMO 텍스트만 좌표와 함께 서버에 저장한다.
    user_text = str(getattr(e, "text", "") or "").strip()
    if (
        user_text
        and (
            "MEMO" in layer
            or "MEMO" in block
        )
        and (
            layer.startswith("CN_M_USER_")
            or "USER" in text
        )
    ):
        return "USER"

    return None


def _symbol_kind(e):
    """Map actual CMB CAD layer/block codes to viewer symbol kinds.

    CAD code is authoritative. Generic English keyword fallback is used only
    for legacy data that does not expose a recognized CMB code.
    """
    layer = str(e.layer or "").strip().upper()
    block = str(e.block_name or "").strip().upper()
    entity_type = str(e.entity_type or "").strip().upper()
    text = f"{layer} {block} {entity_type}"
    padded = f" {text.replace('-', ' ').replace('_', ' ')} "

    # ---- CMB coax device codes (authoritative) ----
    if layer.startswith("CN_C_ONU") or " ONU " in padded:
        return "onu"

    if layer.startswith("CN_C_AMP") or block.startswith("AMP") or " AMP " in padded:
        return "amp"

    if layer.startswith("CN_C_TAP") or block.startswith("TAP") or " TAP " in padded:
        return "tap"

    # Passive family: 2SP/3SP/DC are splitters; PI has its own rectangular-I symbol.
    if (
        block.startswith("2SP")
        or " 2SP " in padded
        or "2WAY" in text
        or "2-WAY" in text
        or "2분기" in text
        or "2분배" in text
    ):
        return "splitter"

    if (
        block.startswith("3SP")
        or " 3SP " in padded
        or "3WAY" in text
        or "3-WAY" in text
        or "3분기" in text
        or "3분배" in text
    ):
        return "splitter"

    if (
        layer.startswith("CN_C_DC")
        or block.startswith("DC")
        or " DC " in padded
        or "DIRECTIONAL COUPLER" in text
    ):
        return "splitter"

    if (
        layer.startswith("CN_C_PI")
        or block.startswith("PI")
        or " PI " in padded
    ):
        return "pi"

    if (
        layer.startswith("CN_C_POWER")
        or block.startswith("PS")
        or " POWER " in padded
        or " PS " in padded
    ):
        return "power_ps"

    # ---- Fiber / infrastructure codes ----
    if (
        layer.startswith("CN_F_CLOSURE")
        or layer.startswith("CN_F_CENTER")
        or layer.startswith("CN_F_TERMINAL")
        or any(k in text for k in ("CLOSURE", "TERMINAL", "CENTER"))
    ):
        return "closure"

    if "MANHOLE" in text:
        return "manhole"

    if layer == "CN_L_POLE" or layer.startswith("CN_L_POLE_POLE") or "POLE" in text:
        return "pole"

    # Legacy fallback only.
    if "ONU" in text:
        return "onu"
    if "AMP" in text or "증폭" in text:
        return "amp"
    if "TAP" in text:
        return "tap"

    return "generic"


def _is_info_entity(e):
    layer = str(e.layer or "").strip().upper()
    block = str(e.block_name or "").strip().upper()
    entity_type = str(e.entity_type or "").strip().upper()

    if entity_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION", "LEADER", "MLEADER"}:
        return True

    info_layer_tokens = (
        "CELLNO", "_ID", "TEXT", "LABEL", "JIBUN", "ADDRESS", "ADDR",
        "INFO", "ANNO", "ANNOT", "NOTE", "MEMO",
    )
    if any(token in layer for token in info_layer_tokens):
        return True

    info_block_tokens = ("TEXT", "LABEL", "ID", "ADDR", "ADDRESS", "JIBUN", "INFO", "ANNO", "ANNOT", "NOTE", "TAG")
    if any(
        block == token or block.startswith(token + "_") or block.endswith("_" + token)
        for token in info_block_tokens
    ):
        return True

    return False


def _rotation_deg(e):
    data = dict(getattr(e, "dxf_data", {}) or {})
    for key in ("rotation", "ROTATION", "angle", "ANGLE"):
        value = data.get(key)
        if value not in (None, ""):
            try:
                return float(value) % 360.0
            except Exception:
                pass
    return 0.0


def _geometry_parts(e):
    """Return all drawable geometry parts for one scene entity.

    Device-like INSERT/POINT keeps a single insertion point.
    Cable/line entities preserve every line/polyline/polygon primitive so
    multi-part CAD geometry is not silently truncated to the first primitive.
    """
    entity_type = str(e.entity_type or "").upper()

    if entity_type in {"INSERT", "POINT"}:
        for kind, data in e.primitives:
            if kind in {"insert", "point"}:
                return "Point", [(float(data[0]), float(data[1]))]
        if e.bbox:
            x1, y1, x2, y2 = e.bbox
            return "Point", [((x1 + x2) / 2, (y1 + y2) / 2)]

    parts = []
    for kind, data in e.primitives:
        if kind in {"line", "polyline", "polygon"} and len(data) >= 2:
            path = [(float(x), float(y)) for x, y in data]
            if len(path) >= 2:
                parts.append(path)

    if parts:
        return ("LineString", parts[0]) if len(parts) == 1 else ("MultiLineString", parts)

    for kind, data in e.primitives:
        if kind in {"insert", "point"}:
            return "Point", [(float(data[0]), float(data[1]))]

    if e.bbox:
        x1, y1, x2, y2 = e.bbox
        return "Point", [((x1 + x2) / 2, (y1 + y2) / 2)]

    return None, []


_UPLOAD_POLE_CODE_RE = re.compile(
    r"(?<![0-9A-Za-z])(\d{4}[A-Za-z][A-Za-z0-9]{3,27})(?![0-9A-Za-z])"
)


def _upload_pole_refs(e):
    """Return every KEPCO pole reference carried by the original CAD object.

    No nearest-pole/geometric inference is performed here. The source CAD
    attribute/XDATA/DXF values are authoritative.
    """
    blobs = []

    for key, value in (getattr(e, "attributes", {}) or {}).items():
        blobs.extend((str(key or ""), str(value or "")))

    for appid, values in (getattr(e, "xdata", []) or []):
        blobs.append(str(appid or ""))
        blobs.extend(str(v or "") for v in (values or []))

    for key, value in (getattr(e, "dxf_data", {}) or {}).items():
        blobs.extend((str(key or ""), str(value or "")))

    pole_info = getattr(e, "pole_info", {}) or {}
    if isinstance(pole_info, dict):
        for key, value in pole_info.items():
            blobs.extend((str(key or ""), str(value or "")))

    blobs.extend([
        str(getattr(e, "text", "") or ""),
        str(getattr(e, "block_name", "") or ""),
        str(getattr(e, "layer", "") or ""),
    ])

    seen = set()
    refs = []
    for blob in blobs:
        for raw in _UPLOAD_POLE_CODE_RE.findall(str(blob or "")):
            pole_no = raw.upper()
            if pole_no in seen:
                continue
            seen.add(pole_no)
            refs.append({
                "pole_no": pole_no,
                "grid_id": pole_no[:5],
            })
    return refs


_UPLOAD_GRID_CODE_RE = re.compile(
    r"(?<![0-9A-Za-z])(\d{4}[A-Za-z])(?![0-9A-Za-z])"
)
_UPLOAD_LOCAL_POLE_ID_RE = re.compile(r"^\(?\s*(\d{1,3})\s*\)?$")


def _object_grid_ids(e):
    """Return every 5-char Polemap grid id explicitly carried by one CAD object.

    Grid grouping must not depend on a full 8-char pole number being present.
    Many drawings store the 5-char grid and local pole id separately, and
    cables/devices may carry only the grid code needed for cell grouping.
    """
    blobs = []

    for key, value in (getattr(e, "attributes", {}) or {}).items():
        blobs.extend((str(key or ""), str(value or "")))

    for appid, values in (getattr(e, "xdata", []) or []):
        blobs.append(str(appid or ""))
        blobs.extend(str(v or "") for v in (values or []))

    for key, value in (getattr(e, "dxf_data", {}) or {}).items():
        blobs.extend((str(key or ""), str(value or "")))

    pole_info = getattr(e, "pole_info", {}) or {}
    if isinstance(pole_info, dict):
        for key, value in pole_info.items():
            blobs.extend((str(key or ""), str(value or "")))

    blobs.extend([
        str(getattr(e, "text", "") or ""),
        str(getattr(e, "block_name", "") or ""),
        str(getattr(e, "layer", "") or ""),
    ])

    grids = []
    for ref in _upload_pole_refs(e):
        grid = str(ref.get("grid_id") or "").strip().upper()
        if grid and grid not in grids:
            grids.append(grid)

    for blob in blobs:
        for raw in _UPLOAD_GRID_CODE_RE.findall(str(blob or "")):
            grid = raw.upper()
            if grid not in grids:
                grids.append(grid)

    return grids


def _actual_pole_numbers(e):
    """Return full KEPCO pole numbers for an actual POLE INSERT.

    Some drawings store the 5-char Polemap grid id and the local 1~3 digit
    pole id in separate XDATA/ATTRIB fields. Combine them deterministically.
    """
    direct = [ref["pole_no"] for ref in _upload_pole_refs(e)]
    if direct:
        return direct

    blobs = []
    local_candidates = []

    for key, value in (getattr(e, "attributes", {}) or {}).items():
        k = str(key or "").upper()
        v = str(value or "").strip()
        blobs.extend((k, v))
        m = _UPLOAD_LOCAL_POLE_ID_RE.match(v)
        if m and any(token in k for token in ("ID", "NO", "POLE", "전주", "번호")):
            local_candidates.append(m.group(1))

    for appid, values in (getattr(e, "xdata", []) or []):
        blobs.append(str(appid or ""))
        for value in (values or []):
            blobs.append(str(value or ""))

    for key, value in (getattr(e, "dxf_data", {}) or {}).items():
        blobs.extend((str(key or ""), str(value or "")))

    pole_info = getattr(e, "pole_info", {}) or {}
    if isinstance(pole_info, dict):
        for key, value in pole_info.items():
            blobs.extend((str(key or ""), str(value or "")))

    grids = []
    for blob in blobs:
        for raw in _UPLOAD_GRID_CODE_RE.findall(str(blob or "")):
            grid = raw.upper()
            if grid not in grids:
                grids.append(grid)

    # ATTRIB tag names vary by drawing; if keyword-based detection missed it,
    # accept a unique 1~3 digit attribute value on the actual POLE INSERT.
    if not local_candidates:
        numeric = []
        for value in (getattr(e, "attributes", {}) or {}).values():
            m = _UPLOAD_LOCAL_POLE_ID_RE.match(str(value or "").strip())
            if m and m.group(1) not in numeric:
                numeric.append(m.group(1))
        if len(numeric) == 1:
            local_candidates = numeric

    out = []
    for grid in grids:
        for local in local_candidates:
            pole_no = grid + str(local).zfill(3)
            if pole_no not in out:
                out.append(pole_no)
    return out


def _build_pole_location_lookup(scene, transformer):
    """Build authoritative pole_no -> stored location map from actual POLE INSERTs."""
    lookup = {}
    for e in scene.entities:
        if classify_entity(e) != "POLE":
            continue
        pole_numbers = _actual_pole_numbers(e)
        if not pole_numbers:
            continue
        anchor = _entity_anchor_xy(e)
        if not anchor:
            continue
        try:
            cad_x, cad_y = float(anchor[0]), float(anchor[1])
            lon, lat = transformer.transform(cad_x, cad_y)
        except Exception:
            continue
        if not all(math.isfinite(v) for v in (cad_x, cad_y, lon, lat)):
            continue
        for pole_no in pole_numbers:
            pole_no = str(pole_no or "").upper()
            if not pole_no:
                continue
            lookup[pole_no] = {
                "pole_no": pole_no,
                "grid_id": pole_no[:5],
                "cad_x": cad_x,
                "cad_y": cad_y,
                "lon": float(lon),
                "lat": float(lat),
            }
    return lookup


def _resolved_pole_refs(e, pole_lookup):
    refs = []
    for ref in _upload_pole_refs(e):
        pole_no = str(ref.get("pole_no") or "").upper()
        stored = dict(pole_lookup.get(pole_no) or {})
        if stored:
            refs.append(stored)
        else:
            refs.append({
                "pole_no": pole_no,
                "grid_id": str(ref.get("grid_id") or pole_no[:5]).upper(),
            })
    return refs


def build_payload(scene, source_path, group, epsg, region_code, memo=""):
    transformer = Transformer.from_crs(
        f"EPSG:{int(epsg)}",
        "EPSG:4326",
        always_xy=True,
    )
    pole_lookup = _build_pole_location_lookup(scene, transformer)

    region_code = str(region_code or "").strip()
    if not region_code:
        raise RuntimeError("서버 지역코드를 선택해주세요.")

    objects = []

    for e in scene.entities:
        if classify_entity(e) != group:
            continue

        geometry_type, source_geometry = _geometry_parts(e)
        if not geometry_type or not source_geometry:
            continue

        def transform_path(points):
            out = []
            for x, y in points:
                lon, lat = transformer.transform(x, y)
                if math.isfinite(lon) and math.isfinite(lat):
                    out.append([lon, lat])
            return out

        geometries = []
        if geometry_type == "Point":
            geo = transform_path(source_geometry)
            if not geo:
                continue
            geometries = [{"type": "Point", "coordinates": geo[0]}]
        elif geometry_type == "LineString":
            geo = transform_path(source_geometry)
            if len(geo) < 2:
                continue
            geometries = [{"type": "LineString", "coordinates": geo}]
        else:
            # 서버 저장 API는 Point / LineString만 허용한다.
            # CAD 객체 내부의 여러 primitive를 MultiLineString 하나로 보내지 않고
            # 각 선분을 독립 LineString object로 분리한다.
            geo_parts = [
                transformed
                for transformed in (transform_path(part) for part in source_geometry)
                if len(transformed) >= 2
            ]
            if not geo_parts:
                continue
            geometries = [
                {"type": "LineString", "coordinates": part}
                for part in geo_parts
            ]

        attrs = dict(e.attributes or {})
        dxf = dict(getattr(e, "dxf_data", {}) or {})

        # USER 그룹은 현장 메모만 저장한다.
        # 건물/지형 도형과 기타 USER 속성은 업로드하지 않는다.
        if str(group or "").upper() == "USER":
            memo_text = str(getattr(e, "text", "") or "").strip()
            if not memo_text:
                continue
            anchor = _entity_anchor_xy(e)
            if not anchor:
                continue
            try:
                lon, lat = transformer.transform(float(anchor[0]), float(anchor[1]))
            except Exception:
                continue
            if not (math.isfinite(lon) and math.isfinite(lat)):
                continue
            geometries = [{
                "type": "Point",
                "coordinates": [float(lon), float(lat)],
            }]
            geometry_type = "Point"
            attrs = {
                "_cmb_user_memo": memo_text,
                "memo": memo_text,
            }
            dxf = {}

        # CAD 원본 색상/선 스타일을 서버까지 보존한다.
        # 특히 COAX 케이블의 빨강/초록/파랑은 전원 상태 의미를 가지므로
        # 그룹 고정색으로 치환하지 않는다.
        style = {}
        display_color = str(getattr(e, "color", "") or "").strip()
        if display_color.startswith("#") and len(display_color) == 7:
            try:
                style["display_color"] = display_color.lower()
                style["true_color"] = int(display_color[1:], 16)
            except Exception:
                pass
        for key in ("color", "true_color", "lineweight", "ltscale"):
            value = dxf.get(key)
            if value not in (None, ""):
                try:
                    if key in ("color", "true_color", "lineweight"):
                        style[key] = int(float(value))
                    else:
                        style[key] = float(value)
                except Exception:
                    pass
        if style:
            attrs["_cmb_style"] = style
        attrs["_cmb_dxf_data"] = dxf

        symbol_kind = _symbol_kind(e)
        attrs["_cmb_symbol_kind"] = symbol_kind
        attrs["_cmb_rotation_deg"] = _rotation_deg(e)
        # POINT는 좌표/정보 표시에 쓰이는 경우가 많으므로 POINT라는 이유만으로
        # 기기로 판정하지 않는다. 실제 INSERT 또는 인식 가능한 기기 심벌만 기기다.
        attrs["_cmb_is_device"] = bool(
            not _is_info_entity(e)
            and (
                str(e.entity_type or "").upper() == "INSERT"
                or symbol_kind != "generic"
            )
        )
        for src_key, dst_key in (
            ("xscale", "_cmb_xscale"),
            ("yscale", "_cmb_yscale"),
            ("zscale", "_cmb_zscale"),
        ):
            value = dxf.get(src_key)
            if value not in (None, ""):
                attrs[dst_key] = value
        # 모든 서버 업로드 객체(FIBER/COAX/CONDUIT/POLE/USER)에 대해
        # 원본 CAD가 가진 한전주 위치값을 직접 보존한다.
        # 좌표 근접/최근접 전주 연산은 하지 않는다.
        pole_info = dict(getattr(e, "pole_info", {}) or {})
        pole_refs = _resolved_pole_refs(e, pole_lookup)
        if pole_info:
            attrs["_cmb_pole_info"] = pole_info
        object_grid_ids = sorted(set(
            _object_grid_ids(e)
            + [
                str(ref.get("grid_id") or "").upper()
                for ref in pole_refs
                if str(ref.get("grid_id") or "").strip()
            ]
        ))
        if object_grid_ids:
            # 격자 그룹 조회는 full pole number 인식 여부와 독립적으로 보존한다.
            attrs["_cmb_grid_ids"] = object_grid_ids
            if len(object_grid_ids) == 1:
                attrs["_cmb_grid_id"] = object_grid_ids[0]

        if pole_refs:
            attrs["_cmb_pole_refs"] = pole_refs
            # 단일 전주 참조 객체는 조회/검색 편의를 위해 대표값도 평탄화한다.
            if len(pole_refs) == 1:
                attrs["_cmb_pole_no"] = pole_refs[0]["pole_no"]
                attrs["_cmb_grid_id"] = pole_refs[0]["grid_id"]
            missing_positions = [
                ref.get("pole_no") for ref in pole_refs
                if ref.get("lon") is None or ref.get("lat") is None
            ]
            if missing_positions:
                attrs["_cmb_pole_position_missing"] = missing_positions

        # 서버의 기기 Point 위치는 CAD 삽입점이 아니라 해당 한전주 저장 좌표를 사용한다.
        # Viewer가 실행 중에 최근접 전주/거리 연산을 하지 않도록 업로드 시점에 위치를 확정한다.
        if geometry_type == "Point" and pole_refs:
            primary = next(
                (
                    ref for ref in pole_refs
                    if ref.get("lon") is not None and ref.get("lat") is not None
                ),
                None,
            )
            if primary is not None:
                original_point = (
                    geometries[0].get("coordinates")
                    if geometries and geometries[0].get("type") == "Point"
                    else None
                )
                if original_point:
                    attrs["_cmb_original_point"] = list(original_point)
                geometries = [{
                    "type": "Point",
                    "coordinates": [float(primary["lon"]), float(primary["lat"])],
                }]
                attrs["_cmb_position_source"] = "POLE"
                attrs["_cmb_pole_position"] = {
                    "pole_no": primary["pole_no"],
                    "grid_id": primary["grid_id"],
                    "lon": float(primary["lon"]),
                    "lat": float(primary["lat"]),
                }
            else:
                attrs["_cmb_position_source"] = "LEGACY_GEOMETRY"

        part_count = len(geometries)
        for part_index, geometry in enumerate(geometries, start=1):
            part_attrs = dict(attrs)
            if part_count > 1:
                part_attrs["_cmb_geometry_part_index"] = part_index
                part_attrs["_cmb_geometry_part_count"] = part_count

            base_object_id = (
                f"{region_code}_{e.handle}"
                if e.handle else ""
            )
            object_id = (
                f"{base_object_id}_part{part_index:03d}"
                if base_object_id and part_count > 1
                else base_object_id
            )

            original_handle = str(e.handle or "")
            source_handle = (
                f"{original_handle}/part/{part_index:03d}"
                if original_handle and part_count > 1
                else original_handle
            )
            if original_handle:
                part_attrs["_cmb_original_handle"] = original_handle

            objects.append({
                # 서버는 source_handle 중복을 허용하지 않으므로 part별로 유일하게 만든다.
                "source_handle": source_handle,
                "object_id": object_id,
                "layer": e.layer,
                "entity_type": e.entity_type,
                "block_name": e.block_name,
                "geometry": geometry,
                "attributes": part_attrs,
                "xdata": dict(e.xdata or []),
            })

    p = Path(source_path)

    payload = {
        "package_schema": "cmb-network-package-v1",
        "region_code": region_code,
        "group": group,
        "source_epsg": int(epsg),
        "source_file": p.name,
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "object_count": len(objects),
        "memo": str(memo or "").strip(),
        "objects": objects,
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["package_sha256"] = hashlib.sha256(canonical).hexdigest()

    payload = enrich_payload_v2(
        scene,
        source_path,
        group,
        payload,
        classify_entity,
    )

    # USER 그룹은 좌표 + 메모 텍스트만 유지한다.
    if str(group or "").upper() == "USER":
        for obj in payload.get("objects") or []:
            attrs = dict(obj.get("attributes") or {})
            memo_text = str(
                attrs.get("_cmb_user_memo")
                or attrs.get("memo")
                or ""
            ).strip()
            obj["attributes"] = (
                {"memo": memo_text, "_cmb_user_memo": memo_text}
                if memo_text else {}
            )
            obj["xdata"] = {}
            obj["block_name"] = ""
            obj["entity_type"] = "TEXT"
        payload["symbol_library"] = []
        payload["symbol_count"] = 0
        payload["user_storage_schema"] = "memo-point-v1"

    # Full pole ID = 5-char management zone (Polemap) + individual CAD NO.
    # Source layers are used only for local resolution; never uploaded as POLE objects.
    pole_no_by_handle = {}
    pole_resolve_stats = {}
    if str(group or "").upper() == "POLE":
        pole_no_by_handle, pole_resolve_stats = resolve_pole_numbers(scene)

    # POLE: 전주 종류 + 전체번호 + 좌표만 저장. 불완전 번호의 묵시적 업로드 금지.
    if str(group or "").upper() == "POLE":
        valid_pole_no = re.compile(r"^[0-9]{4}[A-Z][A-Z0-9-]{1,64}$")
        pole_kinds = {
            "CN_L_POLE_POLE-JOINT": "JOINT",
            "CN_L_POLE_POLE-JOINT-TRS": "TRS",
            "CN_L_POLE_POLE-CATV": "CATV",
            "CN_L_POLE_POLE-STEEL": "STEEL",
            "CN_L_POLE_POLE-CONCRETE": "CONCRETE",
        }
        invalid = []
        kept = []
        for obj in payload.get("objects") or []:
            layer = str(obj.get("layer") or "").strip().upper()
            kind = pole_kinds.get(layer)
            if kind is None:
                continue
            attrs = dict(obj.get("attributes") or {})
            # Trust only the SAME CAD INSERT: ATTRIB ID + XDATA EXMAP_POLE.
            # Never infer a management code from a nearby object, cable or polygon.
            full = pole_no_by_handle.get(str(obj.get("source_handle") or ""))
            if not full or not valid_pole_no.fullmatch(full):
                invalid.append((layer, str(obj.get("source_handle") or ""),
                                str(attrs.get("ID") or "")[:48]))
                continue
            obj["attributes"] = {
                "_cmb_pole_no": full,
                "_cmb_pole_grid": full[:5],
                "_cmb_pole_local": full[5:],
                "_cmb_pole_type": kind,
            }
            obj["xdata"] = {}
            obj["block_name"] = ""
            kept.append(obj)
        if invalid:
            preview = "; ".join(f"{layer}: {values}" for layer, values in invalid[:5])
            raise RuntimeError(
                f"POLE 업로드 중단: 전주번호 또는 관리구역이 없는 "
                f"전주 {len(invalid)}개가 발견되었습니다. 예: {preview}. "
                f"원본 INSERT ID/EXMAP_POLE 검사: {pole_resolve_stats}. "
                "원본 전주 ID 및 EXMAP_POLE 값을 확인하세요. "
                "기존 서버 전주 데이터는 변경되지 않았습니다."
            )
        payload["objects"] = kept
        payload["object_count"] = len(kept)
        payload["symbol_library"] = []
        payload["symbol_count"] = 0
        payload["pole_storage_schema"] = "typed-full-number-v2"

    canonical_v2 = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["package_sha256"] = hashlib.sha256(canonical_v2).hexdigest()

    return payload


def payload_center(payload):
    """Return the fixed WGS84 center of an upload package.

    The center is calculated once from the local upload payload, never from
    server-side regional bounds at view time.
    """
    min_lon = min_lat = None
    max_lon = max_lat = None

    def visit(coords):
        nonlocal min_lon, min_lat, max_lon, max_lat
        if not isinstance(coords, (list, tuple)):
            return
        if (
            len(coords) >= 2
            and isinstance(coords[0], (int, float))
            and isinstance(coords[1], (int, float))
        ):
            lon = float(coords[0])
            lat = float(coords[1])
            if not (math.isfinite(lon) and math.isfinite(lat)):
                return
            if abs(lon) > 180 or abs(lat) > 90:
                return
            min_lon = lon if min_lon is None else min(min_lon, lon)
            max_lon = lon if max_lon is None else max(max_lon, lon)
            min_lat = lat if min_lat is None else min(min_lat, lat)
            max_lat = lat if max_lat is None else max(max_lat, lat)
            return
        for item in coords:
            visit(item)

    for obj in (payload or {}).get("objects") or []:
        geometry = (obj or {}).get("geometry") or {}
        visit(geometry.get("coordinates"))

    if None in (min_lon, min_lat, max_lon, max_lat):
        return None
    return {
        "lat": (min_lat + max_lat) / 2.0,
        "lon": (min_lon + max_lon) / 2.0,
    }



_POLEMAP_GRID_RE = re.compile(r"(?<![0-9A-Za-z])(\d{4}[A-Za-z])(?![0-9A-Za-z])")


def _polemap_grid_id(e):
    values = [str(getattr(e, "text", "") or "")]
    values.extend(str(v) for v in (getattr(e, "attributes", {}) or {}).values())
    for appid, items in (getattr(e, "xdata", []) or []):
        values.append(str(appid or ""))
        values.extend(str(v) for v in (items or []))
    values.extend(str(v) for v in (getattr(e, "dxf_data", {}) or {}).values())
    for value in values:
        m = _POLEMAP_GRID_RE.search(value)
        if m:
            return m.group(1).upper()
    return ""


def _entity_anchor_xy(e):
    for kind, data in (getattr(e, "primitives", []) or []):
        if kind in {"text", "point", "insert"} and len(data) >= 2:
            try:
                return float(data[0]), float(data[1])
            except Exception:
                pass
    box = getattr(e, "bbox", None)
    if box:
        return (float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0
    return None


def build_polemap_payload(scene, source_path, epsg, region_code):
    """Extract only Polemap grid boundaries/IDs as lightweight server metadata."""
    region_code = str(region_code or "").strip()
    if not region_code:
        raise RuntimeError("서버 지역코드를 선택해주세요.")

    transformer = Transformer.from_crs(
        f"EPSG:{int(epsg)}",
        "EPSG:4326",
        always_xy=True,
    )

    idx_points = []
    for e in scene.entities:
        if str(e.layer or "").strip().upper() != "CN_L_POLEMAP_IDXMAIN":
            continue
        grid_id = _polemap_grid_id(e)
        anchor = _entity_anchor_xy(e)
        if grid_id and anchor:
            idx_points.append((grid_id, anchor[0], anchor[1]))

    cells = []
    seen = set()
    for e in scene.entities:
        if str(e.layer or "").strip().upper() != "CN_L_POLEMAP_BOUND":
            continue

        paths = []
        for kind, data in (getattr(e, "primitives", []) or []):
            if kind in {"line", "polyline", "polygon"} and len(data) >= 3:
                try:
                    path = [(float(x), float(y)) for x, y in data]
                except Exception:
                    continue
                if len(path) >= 3:
                    paths.append(path)
        if not paths:
            continue

        grid_id = _polemap_grid_id(e)
        if not grid_id and getattr(e, "bbox", None):
            x1, y1, x2, y2 = e.bbox
            matches = [
                (gid, x, y)
                for gid, x, y in idx_points
                if x1 <= x <= x2 and y1 <= y <= y2
            ]
            if matches:
                cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                matches.sort(key=lambda row: (row[1]-cx)**2 + (row[2]-cy)**2)
                grid_id = matches[0][0]

        if not grid_id or grid_id in seen:
            continue

        # Polemap_Bound는 사각 폐합 polyline이므로 가장 긴 경계를 대표 polygon으로 사용한다.
        path = max(paths, key=len)
        if path[0] != path[-1]:
            path = path + [path[0]]

        polygon = []
        for x, y in path:
            lon, lat = transformer.transform(x, y)
            if math.isfinite(lon) and math.isfinite(lat):
                polygon.append([lon, lat])
        if len(polygon) < 4:
            continue
        if polygon[0] != polygon[-1]:
            polygon.append(list(polygon[0]))

        seen.add(grid_id)
        cells.append({
            "grid_id": grid_id,
            "polygon": polygon,
            "source_layer": "CN_L_Polemap_Bound",
        })

    p = Path(source_path)
    return {
        "region_code": region_code,
        "source_file": p.name,
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "cells": cells,
    }


def build_symbol_payload(scene, source_path, region_code, memo=""):
    region_code = str(region_code or "").strip()
    if not region_code:
        raise RuntimeError("서버 지역코드를 선택해주세요.")

    symbols = {}
    for e in scene.entities:
        entity_type = str(e.entity_type or "").upper()
        kind = _symbol_kind(e)
        is_device = (not _is_info_entity(e)) and (entity_type == "INSERT" or kind != "generic")
        if not is_device:
            continue

        block = str(e.block_name or "").strip()
        layer = str(e.layer or "").strip()
        key = block or f"{layer}|{kind}"
        if not key:
            continue

        dxf = dict(getattr(e, "dxf_data", {}) or {})
        symbols[key] = {
            "key": key,
            "symbol_kind": kind,
            "block_name": block,
            "layer": layer,
            "entity_type": entity_type,
            "rotation_default_deg": _rotation_deg(e),
            "xscale": dxf.get("xscale"),
            "yscale": dxf.get("yscale"),
            "zscale": dxf.get("zscale"),
        }

    p = Path(source_path)
    payload = {
        "region_code": region_code,
        "source_file": p.name,
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "memo": str(memo or "").strip(),
        "symbol_count": len(symbols),
        "symbols": list(symbols.values()),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["package_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


class AdminUploadWindow(tk.Toplevel):
    def __init__(self, master, scene, source_path, source_epsg, client=None, current_user=None):
        super().__init__(master)

        self.scene = scene
        self.source_path = source_path
        self.epsg = source_epsg
        self.client = client or CMBServerClient()
        self.current_user = current_user
        self.session_busy = False
        self._busy_generation = 0

        self.title("관리자 · 서버 도면 업로드")
        self.geometry("820x690")
        self.minsize(720, 590)
        self.protocol("WM_DELETE_WINDOW", self._close_requested)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="관리자 서버 도면 업로드",
            font=("Malgun Gothic", 16, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=f"{Path(source_path).name} · EPSG:{source_epsg}",
        ).pack(anchor="w", pady=(3, 6))

        region_box = ttk.LabelFrame(root, text="서버 지역", padding=8)
        region_box.pack(fill="x", pady=(0, 10))
        self.region_var = tk.StringVar(value="")
        self.region_combo = ttk.Combobox(
            region_box,
            textvariable=self.region_var,
            state="disabled",
            width=52,
        )
        self.region_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(
            region_box,
            text="지역 새로고침",
            command=self._load_server_regions,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(region_box, text="도면 중심점 변경", command=self._save_drawing_center).pack(side="left", padx=(6, 0))
        self.region_rows = []
        self.region_display_to_id = {}

        self.login_status = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.login_status).pack(anchor="w", pady=(0, 10))

        self.tree = ttk.Treeview(
            root,
            columns=("g", "n", "d"),
            show="headings",
            height=9,
        )

        for key, title, width in (
            ("g", "그룹", 100),
            ("n", "객체수", 90),
            ("d", "범위", 540),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width)

        self.tree.pack(fill="x")

        desc = {
            "FIBER": "광케이블 + 광 관련 기기",
            "COAX": "동축케이블 + ONU/AMP/TAP/PASSIVE/POWER/CONNECTOR 등 동축기기",
            "CONDUIT": "관로 + 맨홀 + 핸드홀",
            "POLE": "실제 전주 INSERT + 전주 속성",
            "USER": "USER MEMO · 현장 공유 메모 좌표 + 텍스트",
        }

        counts = {g: 0 for g in GROUPS}

        for e in scene.entities:
            g = classify_entity(e)
            if g:
                counts[g] += 1

        self.group_counts = counts

        for g in MANAGED_ITEMS:
            scope = desc[g] if counts[g] > 0 else desc[g] + " · 객체 없음(업로드 제외)"
            self.tree.insert(
                "",
                "end",
                iid=g,
                values=(g, f"{counts[g]:,}", scope),
            )

        self.tree.selection_set("FIBER")

        memo_box = ttk.LabelFrame(
            root,
            text="업로드 메모",
            padding=8,
        )
        memo_box.pack(fill="x", pady=(10, 0))

        self.memo_var = tk.StringVar(value="")
        ttk.Entry(
            memo_box,
            textvariable=self.memo_var,
        ).pack(fill="x")
        ttk.Label(
            memo_box,
            text="선택 항목 또는 전체 업로드에 적용할 메모입니다.",
        ).pack(anchor="w", pady=(4, 0))

        row = ttk.Frame(root)
        row.pack(fill="x", pady=12)

        self.upload_one_btn = ttk.Button(
            row,
            text="선택 항목 업로드",
            command=self.upload_selected,
            state="disabled",
        )
        self.upload_one_btn.pack(side="left")

        self.upload_all_btn = ttk.Button(
            row,
            text="광 + 동축 + 관로 업로드",
            command=self.upload_all,
            state="disabled",
        )
        self.upload_all_btn.pack(side="left", padx=6)

        ttk.Button(
            row,
            text="서버 상태 확인",
            command=self.health,
        ).pack(side="left")

        ttk.Button(
            row,
            text="현재 업로드 정보 조회",
            command=self.show_revisions,
        ).pack(side="left", padx=6)

        self.status = tk.StringVar(
            value="서버: https://192.168.246.54:8443"
        )

        ttk.Label(
            root,
            textvariable=self.status,
            anchor="w",
        ).pack(fill="x")

        # 장시간 업로드가 멈춘 것처럼 보이지 않도록 별도 진행 표시를 유지한다.
        self.upload_progress = ttk.Progressbar(
            root,
            mode="indeterminate",
            maximum=100,
        )
        self.upload_progress.pack(fill="x", pady=(8, 3))
        self.upload_progress.pack_forget()

        self.upload_detail = tk.StringVar(value="")
        self.upload_detail_label = ttk.Label(
            root,
            textvariable=self.upload_detail,
            anchor="w",
        )
        self.upload_detail_label.pack(fill="x")
        self.upload_detail_label.pack_forget()

        if self.current_user:
            self.after(0, self._apply_existing_session)
        else:
            self.after(0, self.destroy)

    def _apply_existing_session(self):
        try:
            level = int((self.current_user or {}).get("level", 5))
        except Exception:
            level = 5
        user = self.current_user or {}
        label = (
            f"{user.get('name') or user.get('username')} "
            f"· {user.get('department', '')} · {level}등급"
        )
        self.login_status.set(label)
        if level == 1:
            self.upload_one_btn.configure(state="normal")
            self.upload_all_btn.configure(state="normal")
            self.status.set("관리자 세션 연결 완료")
            self._load_server_regions()
        else:
            self.upload_one_btn.configure(state="disabled")
            self.upload_all_btn.configure(state="disabled")
            self.status.set("1등급 관리자만 업로드할 수 있습니다.")

    def _save_drawing_center(self):
        if int((self.current_user or {}).get("level") or 0) != 1:
            messagebox.showerror("권한 오류", "1등급 관리자만 저장 가능합니다.", parent=self)
            return
        region = self.region_display_to_id.get(self.region_var.get().strip())
        if not region or region != Path(self.source_path).stem.strip():
            messagebox.showerror("지역 확인", "현재 DXF 파일명과 서버 지역코드가 일치해야 합니다.", parent=self)
            return
        viewer = getattr(self.master, "viewer", None)
        if viewer is None or viewer.scene is not self.scene:
            messagebox.showerror("도면 확인", "열린 DXF 도면을 확인할 수 없습니다.", parent=self)
            return
        if not messagebox.askokcancel(
            "도면 중심점 지정",
            "업로드 창을 잠시 숨깁니다.\n도면에서 시작점으로 사용할 위치를 마우스로 한 번 클릭하세요.\n화면 전체 중심이나 멀리 떨어진 도면 객체는 사용하지 않습니다.",
            parent=self,
        ):
            return
        self.withdraw()
        self.master.lift()
        self.master.focus_force()

        def selected_point(x, y):
            self.deiconify()
            self.lift()
            try:
                lon, lat = Transformer.from_crs(
                    f"EPSG:{int(self.epsg)}", "EPSG:4326", always_xy=True
                ).transform(float(x), float(y))
                if not (math.isfinite(lon) and math.isfinite(lat) and 33 <= lat <= 39 and 124 <= lon <= 132):
                    raise ValueError("지정 위치가 한국 지도 범위를 벗어났습니다. 도면 좌표계와 선택 지점을 확인하세요.")
            except Exception as exc:
                messagebox.showerror("좌표 확인 실패", str(exc), parent=self)
                return
            if not messagebox.askyesno(
                "도면 중심점 변경",
                f"지역: {self.region_var.get()}\n\n선택한 위치 좌표\n위도: {lat:.6f}\n경도: {lon:.6f}\n\n기존 저장위치를 바꾸시겠습니까?",
                parent=self,
            ):
                return
            try:
                result = self.client.update_region_center(region, lat, lon)
                if isinstance(result, dict) and (result.get("ok") is False or result.get("error")):
                    raise RuntimeError(str(result.get("error") or "서버 저장 오류"))
                self.status.set(f"도면 시작점 저장 완료 · {region} · {lat:.6f},{lon:.6f}")
                messagebox.showinfo("저장 완료", "선택한 도면 위치를 지역 시작점으로 저장했습니다.", parent=self)
            except Exception as exc:
                messagebox.showerror("저장 실패", str(exc), parent=self)

        viewer.region_center_pick = selected_point

    def _load_server_regions(self):
        self.upload_one_btn.configure(state="disabled")
        self.upload_all_btn.configure(state="disabled")
        self.region_display_to_id = {}
        try:
            rows = self.client.admin_regions() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("regions") or []

            self.region_rows = []
            self.region_display_to_id = {}
            values = []

            for row in rows:
                if not isinstance(row, dict):
                    continue
                rid = str(
                    row.get("id")
                    or row.get("region_id")
                    or row.get("region_code")
                    or ""
                ).strip()
                if not rid.startswith("CMB_GN_"):
                    continue
                name = str(
                    row.get("name")
                    or row.get("region_name")
                    or rid
                ).strip()
                display = f"{name} ({rid})" if name and name != rid else rid
                self.region_rows.append(row)
                self.region_display_to_id[display] = rid
                values.append(display)

            self.region_combo["values"] = values

            # 업로드 지역은 사용자가 선택하지 않는다.
            # 현재 DXF 파일명(stem)과 canonical 지역코드가 정확히 일치할 때만 자동 연결한다.
            # 예: CMB_GN_HP.dxf -> CMB_GN_HP
            source_region = Path(self.source_path).stem.strip()
            auto_display = next(
                (
                    display
                    for display, rid in self.region_display_to_id.items()
                    if rid == source_region
                ),
                "",
            )

            if auto_display:
                self.region_var.set(auto_display)
                self.upload_one_btn.configure(state="normal")
                self.upload_all_btn.configure(state="normal")
                self.status.set(
                    f"서버 canonical 지역 {len(values)}개 · 자동 연결: {source_region}"
                )
            else:
                self.region_var.set("")
                self.upload_one_btn.configure(state="disabled")
                self.upload_all_btn.configure(state="disabled")
                self.status.set(
                    f"서버에 현재 도면 지역이 없습니다: {source_region}"
                )
                messagebox.showerror(
                    "서버 지역 없음",
                    (
                        f"현재 도면 파일명과 일치하는 서버 지역이 없습니다.\n\n"
                        f"도면: {Path(self.source_path).name}\n"
                        f"필요 지역코드: {source_region}\n\n"
                        "지역을 임의로 선택해서 업로드할 수 없습니다."
                    ),
                    parent=self,
                )
        except Exception as exc:
            self.region_combo["values"] = []
            self.region_var.set("")
            self.status.set("서버 지역 조회 실패: " + str(exc))

    def _selected_region_code(self):
        display = self.region_var.get().strip()
        rid = self.region_display_to_id.get(display, "")
        if not rid or rid != Path(self.source_path).stem.strip():
            source_region = Path(self.source_path).stem.strip()
            raise RuntimeError(
                f"현재 도면과 일치하는 서버 지역이 없습니다: {source_region}"
            )
        return rid

    def health(self):
        try:
            self.status.set(
                "서버 응답: "
                + json.dumps(
                    self.client.health(),
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            messagebox.showerror(
                "서버",
                str(exc),
                parent=self,
            )

    def _require_admin(self):
        if not self.current_user:
            raise RuntimeError("먼저 서버에 로그인해주세요.")

        if int(self.current_user.get("level", 5)) != 1:
            raise RuntimeError(
                "도면 업로드는 1등급 관리자만 가능합니다."
            )

    def _close_requested(self):
        if self.session_busy:
            messagebox.showinfo(
                "업로드 진행 중",
                "업로드 또는 서버 처리 중에는 창을 닫을 수 없습니다.\n완료 후 닫아주세요.",
                parent=self,
            )
            return
        self.destroy()

    @staticmethod
    def _format_elapsed(seconds):
        seconds = max(0, int(seconds))
        hours, remain = divmod(seconds, 3600)
        minutes, secs = divmod(remain, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _show_upload_progress(self, phase, group, object_count=0, package_mb=None):
        try:
            if not self.upload_progress.winfo_manager():
                self.upload_progress.pack(fill="x", pady=(8, 3))
            if not self.upload_detail_label.winfo_manager():
                self.upload_detail_label.pack(fill="x")
            self.upload_progress.stop()
            self.upload_progress.configure(mode="indeterminate", value=0)
            self.upload_progress.start(12)
        except Exception:
            pass
        size_text = f" · 패키지 {package_mb:.1f} MB" if package_mb is not None else ""
        self.upload_detail.set(
            f"{Path(self.source_path).name} · {group} · 대상 {int(object_count):,}개"
            f"{size_text} · {phase}"
        )
        self.update_idletasks()

    def _hide_upload_progress(self):
        try:
            self.upload_progress.stop()
            self.upload_progress.pack_forget()
            self.upload_detail_label.pack_forget()
        except Exception:
            pass

    def _run_background_task(
        self,
        func,
        phase,
        group,
        object_count=0,
        package_mb=None,
        progress_state=None,
    ):
        """Run long work off the Tk thread while keeping visible progress alive."""
        state = {"done": False, "result": None, "error": None}
        started = time.monotonic()

        def worker():
            try:
                state["result"] = func()
            except Exception as exc:
                state["error"] = exc
            finally:
                state["done"] = True

        self._show_upload_progress(
            phase,
            group,
            object_count=object_count,
            package_mb=package_mb,
        )
        threading.Thread(target=worker, daemon=True).start()

        while not state["done"]:
            elapsed = self._format_elapsed(time.monotonic() - started)
            size_text = f" · 패키지 {package_mb:.1f} MB" if package_mb is not None else ""

            progress_text = ""
            if isinstance(progress_state, dict):
                sent = int(progress_state.get("sent") or 0)
                total = int(progress_state.get("total") or 0)
                if total > 0:
                    pct = max(0.0, min(100.0, sent * 100.0 / total))
                    sent_mb = sent / (1024.0 * 1024.0)
                    total_mb = total / (1024.0 * 1024.0)
                    if sent < total:
                        progress_text = (
                            f" · 전송 {pct:5.1f}%"
                            f" ({sent_mb:.1f}/{total_mb:.1f} MB)"
                        )
                        try:
                            self.upload_progress.stop()
                            self.upload_progress.configure(mode="determinate", value=pct)
                        except Exception:
                            pass
                    else:
                        progress_text = (
                            f" · 전송 100.0% ({total_mb:.1f} MB)"
                            " · 서버 DB 저장/검증 중"
                        )
                        try:
                            self.upload_progress.stop()
                            self.upload_progress.configure(mode="indeterminate", value=0)
                            self.upload_progress.start(12)
                        except Exception:
                            pass

            self.upload_detail.set(
                f"{Path(self.source_path).name} · {group} · 대상 {int(object_count):,}개"
                f"{size_text} · {phase}{progress_text} · 경과 {elapsed} · 세션 유지중"
            )
            try:
                self.update()
            except tk.TclError:
                break
            time.sleep(0.10)

        elapsed = self._format_elapsed(time.monotonic() - started)
        self.upload_detail.set(
            f"{Path(self.source_path).name} · {group} · {phase} 완료 · 경과 {elapsed}"
        )
        self.update_idletasks()

        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    def _begin_busy(self):
        self.session_busy = True
        self._busy_generation += 1
        generation = self._busy_generation
        try:
            self.upload_one_btn.configure(state="disabled")
            self.upload_all_btn.configure(state="disabled")
        except Exception:
            pass

        # 업로드는 Tk 메인 스레드를 오래 점유할 수 있으므로
        # 로컬 idle guard가 사용자 입력 없음으로 로그아웃시키지 않게 일시정지한다.
        try:
            guard = getattr(self.master, "session_guard", None)
            if guard is not None:
                guard.pause()
        except Exception:
            pass

        def heartbeat():
            # 업로드 중에는 사용자 입력과 무관하게 서버 세션을 계속 활성 상태로 유지한다.
            while self.session_busy and generation == self._busy_generation:
                try:
                    self.client.touch_session()
                except Exception:
                    pass
                for _ in range(15):
                    if not self.session_busy or generation != self._busy_generation:
                        return
                    time.sleep(1)

        threading.Thread(target=heartbeat, daemon=True).start()

    def _end_busy(self):
        self.session_busy = False
        self._busy_generation += 1
        try:
            guard = getattr(self.master, "session_guard", None)
            if guard is not None:
                guard.resume()
        except Exception:
            pass
        try:
            # canonical 지역이 정상 연결된 경우에만 다시 활성화한다.
            self._selected_region_code()
            self.upload_one_btn.configure(state="normal")
            self.upload_all_btn.configure(state="normal")
        except Exception:
            pass
        self._hide_upload_progress()

    def _upload(self, group, allow_empty=False):
        self._require_admin()
        region_code = self._selected_region_code()
        self._begin_busy()

        try:
            # POLE도 다른 그룹과 동일한 /admin/drawings/upload 경로를 사용한다.
            # 폐기된 Polemap 격자 API는 호출하지 않는다.

            preview_count = int((self.group_counts or {}).get(group, 0))
            self.status.set(f"{group} · 업로드 패키지 생성 중")
            payload = self._run_background_task(
                lambda: build_payload(
                    self.scene,
                    self.source_path,
                    group,
                    self.epsg,
                    region_code,
                    self.memo_var.get(),
                ),
                "패키지 생성 중",
                group,
                object_count=preview_count,
            )

            if payload["object_count"] <= 0 and not allow_empty:
                raise RuntimeError(
                    f"{group} 그룹에 업로드 가능한 객체가 없습니다."
                )

            package_bytes = len(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            package_mb = package_bytes / (1024.0 * 1024.0)
            object_count = int(payload.get("object_count") or 0)

            self.status.set(
                f"{group} · {object_count:,}개 · {package_mb:.1f} MB · 서버 전송/DB 저장 중"
            )
            transfer = {"sent": 0, "total": package_bytes}

            def on_upload_progress(sent, total):
                transfer["sent"] = int(sent or 0)
                if int(total or 0) > 0:
                    transfer["total"] = int(total)

            result = self._run_background_task(
                lambda: self.client.upload_group(
                    payload,
                    progress_callback=on_upload_progress,
                ),
                "서버 전송/DB 저장 중",
                group,
                object_count=object_count,
                package_mb=package_mb,
                progress_state=transfer,
            )

            # 지역 중심은 광(FIBER) 원본 업로드 패키지에서 한 번만 확정한다.
            # Viewer에서는 bounds 중심을 다시 계산하지 않는다.
            if str(group or "").upper() == "FIBER":
                center = payload_center(payload)
                if not center:
                    raise RuntimeError(
                        "FIBER 업로드는 완료됐지만 지역 중심점을 계산할 수 없습니다."
                    )
                try:
                    self.client.update_region_center(
                        region_code,
                        center["lat"],
                        center["lon"],
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "FIBER 업로드는 완료됐지만 지역 중심점 서버 저장에 실패했습니다: "
                        + str(exc)
                    ) from exc

            self.status.set(
                f"{group} 업로드 완료 · "
                f"revision {result.get('revision')} · "
                f"{result.get('object_count')}개 · {package_mb:.1f} MB"
            )
            return result
        finally:
            self._end_busy()

    def _upload_symbol(self, allow_empty=False):
        self._require_admin()
        region_code = self._selected_region_code()
        self._begin_busy()
        try:
            preview_count = int((self.group_counts or {}).get("SYMBOL", 0))
            payload = self._run_background_task(
                lambda: build_symbol_payload(
                    self.scene,
                    self.source_path,
                    region_code,
                    self.memo_var.get(),
                ),
                "심볼 패키지 생성 중",
                "SYMBOL",
                object_count=preview_count,
            )
            if payload["symbol_count"] <= 0 and not allow_empty:
                raise RuntimeError("업로드 가능한 심볼 정의가 없습니다.")

            package_bytes = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            package_mb = package_bytes / (1024.0 * 1024.0)
            symbol_count = int(payload.get("symbol_count") or 0)

            self.status.set(
                f"SYMBOL · {symbol_count:,}개 · {package_mb:.1f} MB · 서버 전송/DB 저장 중"
            )
            transfer = {"sent": 0, "total": package_bytes}

            def on_upload_progress(sent, total):
                transfer["sent"] = int(sent or 0)
                if int(total or 0) > 0:
                    transfer["total"] = int(total)

            result = self._run_background_task(
                lambda: self.client.upload_symbols(
                    region_code,
                    payload,
                    progress_callback=on_upload_progress,
                ),
                "서버 전송/DB 저장 중",
                "SYMBOL",
                object_count=symbol_count,
                package_mb=package_mb,
                progress_state=transfer,
            )
            self.status.set(
                "SYMBOL 업로드 완료 · "
                f"revision {result.get('revision')} · "
                f"{result.get('symbol_count', symbol_count)}개 · {package_mb:.1f} MB"
            )
            return result
        finally:
            self._end_busy()

    def upload_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        try:
            self._upload(item)
        except Exception as exc:
            messagebox.showerror(
                "업로드 오류",
                str(exc),
                parent=self,
            )

    def upload_all(self):
        try:
            self._require_admin()

            uploaded = []
            failed = []

            # 전체 업로드는 광 + 동축 + 관로만 순차 교체한다.
            # POLE/USER MEMO는 전체 업로드에서 절대 건드리지 않는다.
            # 전주 관련 데이터는 POLE 선택 업로드에서만 갱신한다.
            for item in FULL_UPLOAD_ITEMS:
                try:
                    self._upload(item, allow_empty=True)
                    uploaded.append(item)
                except Exception as exc:
                    failed.append(f"{item}: {exc}")

            if not uploaded:
                raise RuntimeError(
                    "모든 업로드 항목이 실패했습니다.\n" + "\n".join(failed)
                )

            text = "성공: " + ", ".join(uploaded)
            if failed:
                text += "\n\n실패:\n" + "\n".join(failed)

            messagebox.showinfo(
                "전체 업로드 결과",
                text,
                parent=self,
            )
            self.status.set(
                "전체 업로드 완료 · 성공 " + ", ".join(uploaded)
                + (f" · 실패 {len(failed)}개" if failed else "")
            )

        except Exception as exc:
            messagebox.showerror(
                "업로드 오류",
                str(exc),
                parent=self,
            )

    def show_revisions(self):
        if not self.current_user:
            messagebox.showinfo(
                "백업 조회",
                "먼저 서버에 로그인해주세요.",
                parent=self,
            )
            return

        if int(self.current_user.get("level", 5)) != 1:
            messagebox.showinfo(
                "백업 조회",
                "백업 조회/복원은 현재 1등급 관리자만 가능합니다.",
                parent=self,
            )
            return

        try:
            region = self._selected_region_code()
        except Exception as exc:
            messagebox.showerror("백업 조회", str(exc), parent=self)
            return

        win = tk.Toplevel(self)
        win.title(f"서버 도면 백업 · {region}")
        win.geometry("920x480")
        win.minsize(760, 400)
        win.transient(self)

        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text=f"{region} · 광 → 동축 → 관로 → 전주 → USER MEMO",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=(
                "백업을 선택해 복원하면 해당 그룹의 선택 백업이 현재본이 되고, "
                "기존 현재본은 백업으로 유지됩니다."
            ),
        ).pack(anchor="w", pady=(3, 10))

        tree = ttk.Treeview(
            root,
            columns=("group", "state", "version", "date", "count", "memo"),
            show="headings",
            height=13,
        )
        for key, title, width in (
            ("group", "종류", 90),
            ("state", "상태", 70),
            ("version", "저장일-차수", 125),
            ("date", "저장일시", 155),
            ("count", "객체수", 90),
            ("memo", "메모", 420),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        row_map = {}

        def load_rows():
            for item in tree.get_children():
                tree.delete(item)
            row_map.clear()

            rows = self.client.revisions(region) or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("revisions") or []

            order = {g: i for i, g in enumerate(MANAGED_ITEMS)}
            rows = [
                r for r in list(rows)
                if str((r or {}).get("group_id") or "").upper() in order
            ]
            rows = sorted(
                rows,
                key=lambda r: (
                    order.get(str(r.get("group_id") or "").upper(), 999),
                    0 if r.get("active") else 1,
                    -int(r.get("revision") or 0),
                ),
            )

            daily_counts = {}
            display_ids = {}
            for row in sorted(rows, key=lambda r: (str(r.get("created_at") or ""), int(r.get("revision") or 0))):
                group_key = str(row.get("group_id") or "").upper()
                day = str(row.get("created_at") or "")[:10].replace("-", "")
                if not day:
                    continue
                key = (group_key, day)
                daily_counts[key] = daily_counts.get(key, 0) + 1
                display_ids[id(row)] = f"{day}-{daily_counts[key]:02d}"

            for idx, item in enumerate(rows):
                group = str(item.get("group_id") or "")
                state = "현재" if item.get("active") else "백업"
                created = str(item.get("created_at") or "").replace("T", " ")[:19]
                memo = str(item.get("memo") or "").strip() or "메모 없음"
                count = int(item.get("object_count") or 0)
                iid = f"rev_{idx}_{item.get('id') or item.get('revision')}"
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(group, state, display_ids.get(id(item), "날짜 없음"), created or "날짜 없음", f"{count:,}", memo),
                )
                row_map[iid] = {**item, "_display_version": display_ids.get(id(item), "날짜 없음")}

        def restore_selected():
            selected = tree.selection()
            if not selected:
                messagebox.showinfo(
                    "백업 복원",
                    "복원할 백업을 선택해주세요.",
                    parent=win,
                )
                return

            item = row_map.get(selected[0]) or {}
            if item.get("active"):
                messagebox.showinfo(
                    "백업 복원",
                    "현재 사용 중인 도면입니다. 백업 항목을 선택해주세요.",
                    parent=win,
                )
                return

            revision_id = item.get("id")
            if revision_id in (None, ""):
                messagebox.showerror(
                    "백업 복원",
                    "서버 응답에 Revision ID가 없어 복원할 수 없습니다.",
                    parent=win,
                )
                return

            group = str(item.get("group_id") or "")
            created = str(item.get("created_at") or "").replace("T", " ")[:19]
            memo = str(item.get("memo") or "").strip() or "메모 없음"

            if not messagebox.askyesno(
                "백업 복원 확인",
                (
                    f"지역: {region}\n"
                    f"종류: {group}\n"
                    f"저장버전: {item.get('_display_version', '-')}\n"
                    f"백업일시: {created or '날짜 없음'}\n"
                    f"메모: {memo}\n\n"
                    "이 백업을 현재 도면으로 복원하시겠습니까?\n"
                    "기존 현재본은 백업으로 유지됩니다."
                ),
                parent=win,
            ):
                return

            try:
                result = self.client.restore_revision(
                    region,
                    revision_id,
                    item.get("group_id"),
                )
                load_rows()
                self.status.set(
                    f"{group} 백업 복원 완료 · "
                    f"선택 버전 {item.get('_display_version', '-')}"
                )
                messagebox.showinfo(
                    "백업 복원",
                    "선택한 백업을 현재 도면으로 복원했습니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "백업 복원 오류",
                    str(exc),
                    parent=win,
                )

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(10, 0))

        ttk.Button(
            controls,
            text="새로고침",
            command=load_rows,
        ).pack(side="left")

        ttk.Button(
            controls,
            text="선택 백업 복원",
            command=restore_selected,
        ).pack(side="right")

        try:
            load_rows()
        except Exception as exc:
            win.destroy()
            messagebox.showerror(
                "백업 조회 오류",
                str(exc),
                parent=self,
            )


# Inline direct-source POLE resolver: bundled with admin_upload itself.
"""Extract existing pole identification from the original pole INSERT only.

The individual NO is the INSERT's ID attribute (CN_L_Pole_ID).
The five-character management grid is an EXMAP_POLE XDATA 1000 string.
No geometry-based guess, nearby poles, or Polemap polygon inference is used.
"""

GRID = re.compile(r"^[0-9]{4}[A-Z]$")
FULL = re.compile(r"^[0-9]{4}[A-Z][A-Z0-9]{3,27}$")
LOCAL = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,63}$")
POLES = {
    "CN_L_POLE_POLE-JOINT",
    "CN_L_POLE_POLE-JOINT-TRS",
    "CN_L_POLE_POLE-CATV",
    "CN_L_POLE_POLE-STEEL",
    "CN_L_POLE_POLE-CONCRETE",
}

def _id_value(e):
    attrs = getattr(e, "attributes", {}) or {}
    raw = str(attrs.get("ID") or "").strip().upper()\n    if raw.startswith("(") and raw.endswith(")"):\n        raw = raw[1:-1].strip()
    return raw

def _grid_values(e):
    result = set()
    for appid, values in (getattr(e, "xdata", None) or []):
        if str(appid).strip().upper() != "EXMAP_POLE":
            continue
        for item in values or []:
            raw = str(item).strip()
            # The viewer preserves XDATA as "1000: VALUE" strings.
            match = re.fullmatch(r"1000:\s*(.*)", raw, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip().upper()
                if GRID.fullmatch(candidate):
                    result.add(candidate)
    return result

def resolve_pole_numbers(scene):
    resolved = {}
    reasons = {"id_missing_or_invalid":0, "grid_missing":0, "grid_ambiguous":0}
    samples = {k:[] for k in reasons}
    total = 0
    for e in scene.entities:
        if str(e.layer or "").upper() not in POLES or str(e.entity_type or "").upper() != "INSERT":
            continue
        total += 1
        local = _id_value(e)
        if FULL.fullmatch(local):
            resolved[e.handle] = local
            continue
        if not local or local == "-" or not LOCAL.fullmatch(local):
            reason="id_missing_or_invalid"
        else:
            grids = _grid_values(e)
            if len(grids)==0: reason="grid_missing"
            elif len(grids)!=1: reason="grid_ambiguous"
            else:
                resolved[e.handle] = next(iter(grids)) + local
                continue
        reasons[reason] += 1
        if len(samples[reason]) < 5:
            samples[reason].append({
                "handle":str(e.handle),"layer":str(e.layer),
                "id": local,"grids":sorted(_grid_values(e))
            })
    stats={"pole_objects":total,"resolved":len(resolved),
           "unresolved":total-len(resolved),"reasons":reasons,"samples":samples,
           "method":"INSERT.ID + INSERT.XDATA.EXMAP_POLE.1000"}
    return resolved, stats

