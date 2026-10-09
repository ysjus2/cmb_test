"""Persist rendered geometry as data, never executable pickle objects."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile

from converter import LayerInfo
from viewer import Scene, VisualEntity, build_scene

CACHE_VERSION = 'v330-geometry-1'

def fingerprint(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    stat = path.stat()
    return {'version': CACHE_VERSION, 'path': str(path.resolve()),
            'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': digest.hexdigest()}

def scene_layers(scene):
    names = set(scene.layer_names)
    counts, types = {}, {}
    for entity in scene.entities:
        names.add(entity.layer)
        counts[entity.layer] = counts.get(entity.layer, 0) + 1
        types.setdefault(entity.layer, set()).add(entity.entity_type)
    return [LayerInfo(name, counts.get(name, 0), ', '.join(sorted(types.get(name, set()))))
            for name in sorted(names, key=str.lower)]

def open_drawing(input_path, log=None, progress=None, cache_dir=None, builder=None):
    log = log or (lambda message: None)
    progress = progress or (lambda value, message: None)
    builder = builder or build_scene
    source = Path(input_path)
    progress(1, '도면 캐시 확인')
    signature = fingerprint(source)
    directory = Path(cache_dir) if cache_dir else Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'CMB_DXF_Viewer' / 'drawing-cache'
    key = hashlib.sha256(str(source.resolve()).casefold().encode('utf-8')).hexdigest()
    cache = directory / (key + '.json.gz')
    try:
        with gzip.open(cache, 'rt', encoding='utf-8') as stream:
            payload = json.load(stream)
        if payload['signature'] == signature:
            values = payload['scene']
            values['entities'] = [VisualEntity(**entity) for entity in values['entities']]
            scene = Scene(**values)
            if any(entity.index != index for index, entity in enumerate(scene.entities)):
                raise ValueError('Invalid cached entity indices')
            layers = scene_layers(scene)
            progress(100, '캐시에서 도면 준비 완료')
            log('도면 캐시 사용: DXF 재분석 생략')
            return layers, scene
    except (OSError, EOFError, ValueError, KeyError, TypeError):
        pass
    scene = builder(source, log=log, progress=progress)
    layers = scene_layers(scene)
    temporary = None
    try:
        if fingerprint(source) != signature:
            log('도면이 변경되어 캐시 저장을 생략했습니다.')
            return layers, scene
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=1) as stream:
            json.dump({'signature': signature, 'scene': {**vars(scene), 'entities': [vars(entity) for entity in scene.entities]}}, stream, ensure_ascii=False)
        os.replace(temporary, cache)
        temporary = None
        log('도면 캐시 저장 완료: 다음 열기부터 재사용')
    except (OSError, ValueError, TypeError) as error:
        log('캐시 저장 생략: ' + str(error))
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return layers, scene
