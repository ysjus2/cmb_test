from pathlib import Path

p=Path('viewer.py')
s=p.read_text(encoding='utf8')
s=s.replace('    unsupported: dict\n', '    unsupported: dict\n    diagnostics: list = field(default_factory=list)\n', 1)
s=s.replace('if kind in {"polyline", "line"}:', 'if kind in {"polyline", "line", "polygon"}:',1)
wrapper='''from geometry_complete import render_entity

_legacy_entity_primitives = _entity_primitives

def _entity_primitives(entity, inherited_layer=None, depth=0, issues=None, parts=None):
    return render_entity(entity, inherited_layer, depth, _legacy_entity_primitives,
                         parts if parts is not None else [], issues if issues is not None else [])

'''
s=s.replace('def build_scene(input_path, log=None, progress=None):', wrapper+'def build_scene(input_path, log=None, progress=None):',1)
s=s.replace('    scene_box = None\n\n    for i, ent in enumerate(source):\n        layer, primitives = _entity_primitives(ent)', '    scene_box = None\n    geometry_issues = []\n    pending_children = []\n\n    for i, ent in enumerate(source):\n        block_parts = []\n        layer, primitives = _entity_primitives(ent, issues=geometry_issues, parts=block_parts)',1)
marker='''        if i + 1 == total or (i + 1) % max(1, total // 100) == 0:
'''
children='''        for part_index, (child, child_layer, child_prims) in enumerate(block_parts):
            if child_layer == layer:
                continue
            child_box = None
            for prim in child_prims:
                child_box = _merge_bbox(child_box, _primitive_bbox(prim))
            child_attrs, child_xdata, child_dxf = _collect_entity_details(doc, child)
            child_dxf['PARENT_HANDLE'] = str(getattr(ent.dxf, 'handle', '') or '')
            child_dxf['PARENT_BLOCK'] = block_name
            if child.dxftype() == 'ATTRIB':
                child_attrs[str(child.dxf.tag)] = str(child.dxf.text)
            pending_children.append(VisualEntity(
                index=0, entity_type=child.dxftype(), layer=child_layer,
                handle=f'{getattr(ent.dxf, "handle", "")}/child/{part_index}',
                text=str(getattr(child.dxf, 'text', '') or ''), block_name=block_name,
                primitives=child_prims, bbox=tuple(child_box) if child_box else None,
                color=_resolve_entity_color(doc, child, child_layer, display_color),
                attributes=child_attrs, xdata=child_xdata, dxf_data=child_dxf,
            ))
            scene_box = _merge_bbox(scene_box, child_box)
'''
if marker not in s:raise RuntimeError('Scene loop marker missing')
s=s.replace(marker,children+marker,1)
s=s.replace('    # 일부 통신망 CAD는 케이블을 ESSENPOLY', '    for child in pending_children:\n        child.index = len(entities)\n        entities.append(child)\n\n    # 일부 통신망 CAD는 케이블을 ESSENPOLY',1)
s=s.replace('return Scene(entities, tuple(scene_box), unsupported)', '''# Recovered custom objects are no longer missing geometry.
    repaired = {e.handle for e in entities if e.primitives}
    geometry_issues = [issue for issue in geometry_issues if not (issue['type'] in {'ESSENPOLY', 'ASDKESSENLINKER'} and issue['handle'] in repaired)]
    return Scene(entities, tuple(scene_box), unsupported, geometry_issues)''',1)
s=s.replace('                    elif kind == "circle":', '''                    elif kind == "polygon":
                        coords = []
                        for x, y in data:
                            coords.extend(self.world_to_screen(x, y))
                        if len(coords) >= 6:
                            ids.append(c.create_polygon(*coords, fill=color, outline=color))
                    elif kind == "circle":''',1)
s=s.replace('text=text[:120]', 'text=text')
p.write_text(s,encoding='utf8')

p=Path('converter.py')
s=p.read_text(encoding='utf8')
helper='''def _layer_entities(doc):
    """Include block components on explicit child layers without changing DXF."""
    def walk(insert, inherited, root_layer, chain=()):
        name = str(insert.dxf.name)
        if name in chain or len(chain) >= 32:
            return
        for child in insert.virtual_entities():
            layer = str(child.dxf.layer or '0')
            if layer == '0':
                layer = inherited
            if child.dxftype() == 'INSERT':
                yield from walk(child, layer, root_layer, chain + (name,))
            elif layer != root_layer:
                clone = child.copy()
                clone.dxf.layer = layer
                yield clone
        for attr in getattr(insert, 'attribs', []):
            layer = str(attr.dxf.layer or '0')
            if layer == '0':
                layer = inherited
            if layer != root_layer:
                clone = attr.copy()
                clone.dxf.layer = layer
                yield clone
    for ent in doc.modelspace():
        yield ent
        if ent.dxftype() == 'INSERT':
            yield from walk(ent, str(ent.dxf.layer), str(ent.dxf.layer))

'''
s=s.replace('def scan_layers(', helper+'def scan_layers(',1)
s=s.replace('entities = list(doc.modelspace())','entities = list(_layer_entities(doc))')
s=s.replace('    counts, types = {}, {}', '    counts = {str(layer.dxf.name): 0 for layer in doc.layers}\n    types = {name: set() for name in counts}',1)
s=s.replace('    out = {}\n    if entity.dxftype() == "INSERT":', '    out = {}\n    if entity.dxftype() == "ATTRIB":\n        out[_norm(entity.dxf.tag)] = _norm(entity.dxf.text)\n    if entity.dxftype() == "INSERT":',1)
s=s.replace('if entity.dxftype() == "TEXT":', 'if entity.dxftype() in {"TEXT", "ATTRIB"}:')
s=s.replace('if typ in {"TEXT", "MTEXT"}:', 'if typ in {"TEXT", "MTEXT", "ATTRIB"}:')
p.write_text(s,encoding='utf8')

p=Path('main.py')
s=p.read_text(encoding='utf8').replace('v3.21','v3.22')
s=s.replace('self.layer_rows[iid] = (layer.name, layer.count, layer.types)', 'self.layer_rows[iid] = (layer.name, scene_counts.get(layer.name, 0), ", ".join(sorted(scene_types.get(layer.name, set()))))')
s=s.replace('        view_menu.add_command(label="전체 화면"', '        view_menu.add_command(label="도면 점검 결과", command=self._show_drawing_audit)\n        view_menu.add_command(label="전체 화면"',1)
method='''    def _show_drawing_audit(self):
        scene = self.viewer.scene
        if scene is None:
            messagebox.showinfo(APP_NAME, '먼저 DXF 도면을 열어주세요.')
            return
        counts = {}
        for ent in scene.entities:
            counts[ent.layer] = counts.get(ent.layer, 0) + 1
        empty = [name for name in self.layer_names.values() if not counts.get(name)]
        missing = [ent for ent in scene.entities if not ent.primitives]
        lines = [f'등록 레이어: {len(self.layer_names)}개', f'객체가 있는 레이어: {len(counts)}개',
                 f'빈 레이어: {len(empty)}개', f'상위/블록 내부 표시 객체: {len(scene.entities):,}개',
                 f'도형 미표시 객체: {len(missing)}개', f'블록/도형 변환 문제: {len(scene.diagnostics)}건']
        if missing:
            lines.append(chr(10) + '미표시 객체:')
            lines.extend(f'{e.layer} / {e.entity_type} / {e.handle}' for e in missing)
        if scene.diagnostics:
            lines.append(chr(10) + '변환 문제:')
            lines.extend(f"{i['layer']} / {i['type']}: {i['reason']}" for i in scene.diagnostics)
        lines.append(chr(10) + '새 사용자 객체 형식은 지원 여부를 확인해야 합니다.')
        window = tk.Toplevel(self)
        window.title('도면 점검 결과')
        window.geometry('760x480')
        text = tk.Text(window, wrap='word', font=('Malgun Gothic', 10))
        text.pack(fill='both', expand=True)
        text.insert('1.0', chr(10).join(lines))
        text.configure(state='disabled')

'''
s=s.replace('    def _drain(self):',method+'    def _drain(self):',1)
s=s.replace('                    if scene.unsupported:', '''                    if scene.unsupported or scene.diagnostics:
                        messagebox.showwarning(APP_NAME, '일부 객체 또는 블록 내부 도형을 표시하지 못했습니다. 보기 > 도면 점검 결과에서 확인하세요.')
                    if scene.unsupported:''',1)
p.write_text(s,encoding='utf8')
print('v3.22: complete layers, block geometry, attributes and diagnostics applied')
