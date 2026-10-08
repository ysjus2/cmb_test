from pathlib import Path

p=Path('converter.py')
s=p.read_text(encoding='utf8')
s=s.replace('        for child in insert.virtual_entities():', '        for part_no, child in enumerate(insert.virtual_entities()):')
s=s.replace('                clone.dxf.layer = layer\n                yield clone', '                clone.dxf.layer = layer\n                clone._cmb_export_handle = f"{getattr(insert.dxf, \'handle\', \'\')}/child/{part_no}"\n                clone._cmb_parent_block = name\n                clone._cmb_parent_handle = str(getattr(insert.dxf, \'handle\', \'\') or \'\')\n                yield clone',1)
s=s.replace('        for attr in getattr(insert, \'attribs\', []):', '        for attr_no, attr in enumerate(getattr(insert, \'attribs\', [])):')
s=s.replace('                clone.dxf.layer = layer\n                yield clone', '                clone.dxf.layer = layer\n                clone._cmb_export_handle = str(attr.dxf.handle or f"{getattr(insert.dxf, \'handle\', \'\')}/attr/{attr_no}")\n                clone._cmb_parent_block = name\n                clone._cmb_parent_handle = str(getattr(insert.dxf, \'handle\', \'\') or \'\')\n                yield clone',1)
s=s.replace('handle = _norm(getattr(ent.dxf, "handle", ""))', 'handle = _norm(getattr(ent, "_cmb_export_handle", getattr(ent.dxf, "handle", "")))')
s=s.replace('block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else ""', 'block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else str(getattr(ent, "_cmb_parent_block", ""))')
s=s.replace('    out = {}\n    if entity.dxftype() == "ATTRIB":', '    out = {}\n    if getattr(entity, "_cmb_parent_handle", ""):\n        out["PARENT_HANDLE"] = entity._cmb_parent_handle\n    if entity.dxftype() == "ATTRIB":',1)
start=s.index('def _xdata_text(doc, entity):')
end=s.index('\ndef _entity_text(entity):',start)
s=s[:start]+'''def _xdata_text(doc, entity):
    chunks = []
    for appid in doc.appids:
        name = str(appid.dxf.name)
        try:
            tags = entity.get_xdata(name)
        except Exception:
            continue
        chunks.append(name + ': ' + ' ; '.join(f'{tag.code}:{tag.value}' for tag in tags))
    return ' | '.join(chunks)

'''+s[end:]
p.write_text(s,encoding='utf8')
