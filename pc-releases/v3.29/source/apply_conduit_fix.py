from pathlib import Path

p = Path('viewer.py')
s = p.read_text(encoding='utf-8')
s = s.replace('from converter import load_dxf_document\n', 'from converter import load_dxf_document\nfrom essenpoly_recovery import recover_linker_polylines\n', 1)
marker = '    if scene_box is None:\n        scene_box = [0.0, 0.0, 1.0, 1.0]\n'
block = '''    # Restore original conduit/aerial paths from their embedded geometry.
    linker_items = recover_linker_polylines(input_path)
    linker_targets = {entity.handle: entity for entity in entities if entity.handle}
    linker_count = 0
    for item in linker_items:
        points = item['points']
        box = _points_bbox(points)
        if box is None:
            continue
        target = linker_targets.get(item['handle'])
        layer = item['layer']
        color = _display_color_for_layer(doc, layer, item.get('color_aci'), item.get('true_color'))
        xdata = [(appid, values) for appid, values in item.get('xdata', {}).items()]
        if target is None:
            target = VisualEntity(index=len(entities), entity_type='ASDKESSENLINKER', layer=layer, handle=item['handle'])
            entities.append(target)
            if target.handle:
                linker_targets[target.handle] = target
        else:
            if target.primitives:
                continue
            missing_type = target.entity_type
            if unsupported.get(missing_type, 0):
                unsupported[missing_type] -= 1
                if not unsupported[missing_type]:
                    unsupported.pop(missing_type)
        target.entity_type = 'ASDKESSENLINKER'
        target.layer = layer
        target.primitives = [('polyline', points)]
        target.bbox = box
        target.color = color
        target.attributes.update(item.get('attributes', {}))
        target.xdata = xdata
        scene_box = _merge_bbox(scene_box, box)
        linker_count += 1
    if linker_count:
        log(f'관로/연결선 {linker_count}개 원본 경로 복구')

'''
if marker not in s:
    raise RuntimeError('Scene recovery insertion point missing')
s = s.replace(marker, block + marker, 1)
p.write_text(s, encoding='utf-8')

p = Path('converter.py')
s = p.read_text(encoding='utf-8')
s = s.replace('from essenpoly_recovery import recover_essenpoly_polylines', 'from essenpoly_recovery import recover_essenpoly_polylines, recover_linker_polylines', 1)
s = s.replace('recovered_items = recover_essenpoly_polylines(input_path)', 'recovered_items = recover_essenpoly_polylines(input_path) + recover_linker_polylines(input_path)')
s = s.replace('if typ == "ESSENPOLY" or', 'if typ in {"ESSENPOLY", "ASDKESSENLINKER"} or')
s = s.replace('meta["RECOVERED_TYPE"] = "ESSENPOLY/Embedded AcDbPolyline"', 'meta["RECOVERED_TYPE"] = item.get("entity_type", "ESSENPOLY") + "/Embedded AcDbPolyline"')
s = s.replace('"ESSENPOLY", handle, "", seq, x, y, lon, lat,', 'item.get("entity_type", "ESSENPOLY"), handle, "", seq, x, y, lon, lat,')
p.write_text(s, encoding='utf-8')

p = Path('main.py')
s = p.read_text(encoding='utf-8').replace('v3.19', 'v3.21')
p.write_text(s, encoding='utf-8')
print('Conduit recovery applied: Viewer and Excel')
