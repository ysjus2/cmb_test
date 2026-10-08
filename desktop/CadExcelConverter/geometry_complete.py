from __future__ import annotations

import re

from ezdxf.path import make_path, from_hatch, triangulate

_POLE_CODE_RE = re.compile(r"(?<![0-9A-Za-z])\d{4}[Xx]\d{3}(?![0-9A-Za-z])")

def _is_pole_layer(layer):
    u = str(layer or "").upper()
    return "POLE" in u or "전주" in str(layer or "")

def _keep_insert_attrib(attr, parent_layer):
    """Render only field-useful pole labels from INSERT attributes.

    Equipment/cable IDs remain available as entity metadata/Excel attributes,
    but are not painted over the drawing.
    """
    if not _is_pole_layer(parent_layer):
        return False
    tag = str(getattr(attr.dxf, "tag", "") or "")
    text = str(getattr(attr.dxf, "text", "") or "")
    blob = (tag + " " + text).lower()
    if any(k in blob for k in ("pole", "전주", "전주번호", "전주명", "주번호", "지지물")):
        return True
    return bool(_POLE_CODE_RE.search(text))


def render_entity(entity, inherited_layer, depth, fallback, parts, issues, chain=()):
    typ = entity.dxftype()
    layer = str(getattr(entity.dxf, 'layer', '0') or '0')
    if layer == '0' and inherited_layer:
        layer = inherited_layer
    primitives = []
    try:
        if typ == 'INSERT':
            name = str(entity.dxf.name)
            if name in chain or depth >= 32:
                raise ValueError('순환 블록 또는 블록 중첩 한도 초과')
            for child in entity.virtual_entities():
                child_layer, child_prims = render_entity(child, layer, depth + 1, fallback, parts, issues, chain + (name,))
                if child_layer == layer:
                    primitives.extend(child_prims)
            for attr in getattr(entity, 'attribs', []):
                if int(getattr(attr.dxf, 'flags', 0)) & 1:
                    continue
                if not _keep_insert_attrib(attr, layer):
                    continue
                attr_layer, attr_prims = render_entity(attr, layer, depth + 1, fallback, parts, issues, chain + (name,))
                if attr_layer == layer:
                    primitives.extend(attr_prims)
            if not primitives:
                p = entity.dxf.insert
                primitives.append(('insert', (float(p.x), float(p.y), name)))
            return layer, primitives
        if typ in {'ACAD_PROXY_ENTITY', 'ACAD_PROXY'} and hasattr(entity, 'virtual_entities'):
            # ezdxf can decode the embedded proxy graphic (DXF 310 data) into
            # ordinary virtual LINE/LWPOLYLINE/ARC/... entities.
            for child in entity.virtual_entities():
                child_layer, child_prims = render_entity(
                    child, layer, depth + 1, fallback, parts, issues, chain
                )
                primitives.extend(child_prims)
        elif typ in {'LWPOLYLINE', 'POLYLINE'}:
            path = make_path(entity)
            points = [(float(v.x), float(v.y)) for v in path.flattening(distance=0.02, segments=16)]
            if len(points) >= 2:
                primitives.append(('polyline', points))
        elif typ == 'HATCH':
            paths = list(from_hatch(entity))
            if int(entity.dxf.solid_fill):
                for triangle in triangulate(paths, max_sagitta=0.02, min_segments=16):
                    primitives.append(('polygon', [(float(v.x), float(v.y)) for v in triangle]))
            for path in paths:
                points = [(float(v.x), float(v.y)) for v in path.flattening(distance=0.02, segments=16)]
                if len(points) >= 2:
                    primitives.append(('polyline', points))
        elif typ == 'ATTRIB':
            p = entity.dxf.insert
            text = str(entity.dxf.text or '')
            if text.strip():
                primitives.append(('text', (float(p.x), float(p.y), text)))
        else:
            _, primitives = fallback(entity, inherited_layer, depth)
    except Exception as exc:
        issues.append({'type': typ, 'layer': layer, 'handle': str(getattr(entity.dxf, 'handle', '') or ''), 'reason': str(exc)})
    if not primitives and typ != 'ATTRIB':
        issues.append({'type': typ, 'layer': layer, 'handle': str(getattr(entity.dxf, 'handle', '') or ''), 'reason': '표시할 도형 없음'})
    if depth and primitives:
        parts.append((entity, layer, primitives))
    return layer, primitives
