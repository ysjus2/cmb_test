import math
import re

def conduit_info(entity, item=None):
    item = item or {}
    xdata = item.get('xdata') or dict(entity.xdata or [])
    def values(app, code):
        prefix = str(code) + ':'
        return [str(value).split(':', 1)[1].strip() for value in xdata.get(app, []) if str(value).startswith(prefix)]
    labels = values('EXMAP_POLELINK', 1000)
    candidates = {tuple(map(int, match.groups())) for text in labels
                  for match in [re.fullmatch(r'\s*(\d+)\s*[*xX×]\s*(\d+)\s*', text)] if match and int(match[1]) > 0 and int(match[2]) > 0}
    diameter, count = next(iter(candidates)) if len(candidates) == 1 else (None, None)
    raw = next((text for text in labels if re.fullmatch(r'\s*\d+\s*[*xX×]\s*\d+\s*', text)), '')
    if diameter is None and not candidates:
        for key, value in {**entity.attributes, **item.get('attributes', {})}.items():
            if any(word in key.lower() for word in ('diameter', '관경', '지름', '직경')):
                match = re.fullmatch(r'\s*(\d+)\s*(?:mm|㎜)?\s*', str(value), re.I)
                if match:
                    diameter = int(match[1]); break
        if diameter is None:
            explicit = {int(match) for text in values('EXMAP_PIPELINE', 1000) for match in re.findall(r'(?<!\d)(\d+)\s*(?:mm|㎜)', text, re.I)}
            if len(explicit) == 1:
                diameter = explicit.pop()
    codes = values('EXMAP_PIPELINE', 1000)
    return {'diameter': diameter, 'count': count, 'raw': raw,
            'code': codes[0] if codes else '', 'source': 'EXMAP_POLELINK' if candidates else '명시 속성' if diameter else '미기재'}

def conduit_points(entity):
    paths = [list(map(tuple, points)) for kind, points in entity.primitives
             if kind in {'line', 'polyline'} and len(points) >= 2
             and all(math.isfinite(value) for point in points for value in point)
             and math.dist(points[0], points[-1]) > 1e-8]
    if not paths:
        return []
    points = paths.pop(0)
    while paths:
        for index, path in enumerate(paths):
            if math.dist(points[-1], path[0]) < 1e-6:
                points.extend(path[1:]); break
            if math.dist(points[-1], path[-1]) < 1e-6:
                points.extend(list(reversed(path))[1:]); break
            if math.dist(points[0], path[-1]) < 1e-6:
                points = path[:-1] + points; break
            if math.dist(points[0], path[0]) < 1e-6:
                points = list(reversed(path))[:-1] + points; break
        else:
            return []  # Never invent a connection across a gap.
        paths.pop(index)
    return points
