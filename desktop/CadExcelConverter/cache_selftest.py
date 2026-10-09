import os
from pathlib import Path
import tempfile
from drawing_cache import open_drawing
from viewer import Scene, VisualEntity

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root / 'sample.dxf'
    source.write_bytes(b'first')
    calls = []
    def builder(path, **kwargs):
        calls.append(path.read_bytes())
        return Scene([VisualEntity(0, 'LINE', 'FIBER', '1', primitives=[('line', [(0, 0), (1, 1)])], bbox=(0, 0, 1, 1))], (0, 0, 1, 1), {}, [], ['FIBER', 'EMPTY'])
    layers, scene = open_drawing(source, cache_dir=root / 'cache', builder=builder)
    cached_layers, cached_scene = open_drawing(source, cache_dir=root / 'cache', builder=builder)
    assert len(calls) == 1
    assert [x.name for x in layers] == [x.name for x in cached_layers] == ['EMPTY', 'FIBER']
    assert cached_scene.entities[0].primitives[0][1][-1] == [1, 1]
    stamp = source.stat()
    source.write_bytes(b'other')
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    open_drawing(source, cache_dir=root / 'cache', builder=builder)
    assert len(calls) == 2  # Same timestamp and size, changed content.
    next((root / 'cache').glob('*.json.gz')).write_bytes(b'corrupt')
    open_drawing(source, cache_dir=root / 'cache', builder=builder)
    assert len(calls) == 3
    blocked = root / 'blocked'
    blocked.write_text('not a directory')
    _, fallback = open_drawing(source, cache_dir=blocked, builder=builder)
    assert fallback.entities and len(calls) == 4
print('CACHE TEST OK: reuse, empty layers, changed-content invalidation, corruption recovery, unwritable cache fallback')
