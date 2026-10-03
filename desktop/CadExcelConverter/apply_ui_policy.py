from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"UI patch target not found: {label}")
    return text.replace(old, new, 1)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = replace_once(
    main,
    'from converter import convert_selected_layers, scan_layers',
    'from converter import convert_selected_layers, scan_layers, LayerInfo',
    "LayerInfo import",
)
main = replace_once(
    main,
    'APP_NAME = "CMB DXF Viewer + Excel v3.6"',
    'APP_NAME = "CMB DXF Viewer + Excel v3.8"',
    "version",
)
main = replace_once(
    main,
    '''                        self.visible_layers.add(layer.name)\n                        self.checked_layers.add(layer.name)\n                        self.tree.insert("", "end", iid=iid, values=self._row_values(iid))\n''',
    '''                        # 지번은 객체 수가 많아 첫 화면을 가리므로 최초 로딩 때만 OFF.\n                        # 사용자가 다시 체크하면 Viewer 표시와 Excel 추출에 정상 포함된다.\n                        if layer.name.strip() != "지번":\n                            self.visible_layers.add(layer.name)\n                            self.checked_layers.add(layer.name)\n                        self.tree.insert("", "end", iid=iid, values=self._row_values(iid))\n''',
    "default parcel layer off",
)
main = replace_once(
    main,
    '''                    layers, scene = data\n                    for i, layer in enumerate(layers):\n''',
    '''                    layers, scene = data\n                    # ESSENPOLY처럼 ezdxf가 표준 layer 속성을 노출하지 않는 사용자 객체도\n                    # Viewer 복구 결과에서 레이어 목록에 다시 포함한다.\n                    known = {layer.name for layer in layers}\n                    scene_counts = {}\n                    scene_types = {}\n                    for ent in scene.entities:\n                        scene_counts[ent.layer] = scene_counts.get(ent.layer, 0) + 1\n                        scene_types.setdefault(ent.layer, set()).add(ent.entity_type)\n                    for layer_name in sorted(scene_counts, key=str.lower):\n                        if layer_name not in known:\n                            layers.append(LayerInfo(\n                                layer_name,\n                                scene_counts[layer_name],\n                                ", ".join(sorted(scene_types[layer_name])),\n                            ))\n                    layers.sort(key=lambda x: x.name.lower())\n                    for i, layer in enumerate(layers):\n''',
    "scene recovered layers in UI",
)
main_path.write_text(main, encoding="utf-8")

viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")
viewer = replace_once(
    viewer,
    'from converter import load_dxf_document\n',
    'from converter import load_dxf_document\nfrom essenpoly_recovery import recover_essenpoly_polylines\n',
    "ESSENPOLY recovery import",
)
viewer = replace_once(
    viewer,
    '''    def show_details(self):\n''',
    '''    @staticmethod\n    def _detail_label(key):\n        labels = {\n            "insert": "삽입점",\n            "location": "위치",\n            "center": "중심점",\n            "start": "시작점",\n            "end": "끝점",\n            "rotation": "회전각",\n            "angle": "각도",\n            "radius": "반지름",\n            "xscale": "X 스케일",\n            "yscale": "Y 스케일",\n            "zscale": "Z 스케일",\n            "elevation": "표고",\n            "extrusion": "돌출방향",\n            "height": "문자높이",\n            "text": "문자",\n            "name": "이름",\n            "closed": "폐합여부",\n        }\n        raw = str(key).strip()\n        return labels.get(raw.lower(), raw)\n\n    def show_details(self):\n''',
    "detail label mapping",
)
viewer = replace_once(
    viewer,
    '''                if text_value in {"0", "0.0", "0.000000", "None", "()", "[]", "{}"}:\n                    continue\n                if (key.lower(), text_value) in existing:\n                    continue\n                rows.append((key, text_value))\n''',
    '''                # 빈 컬렉션/None만 제거한다. 0은 좌표·회전·표고 등에서\n                # 실제 의미가 있을 수 있으므로 필드명과 함께 그대로 표시한다.\n                if text_value in {"None", "()", "[]", "{}"}:\n                    continue\n                if (key.lower(), text_value) in existing:\n                    continue\n                rows.append((self._detail_label(key), text_value))\n''',
    "semantic empty-value filtering",
)
viewer = replace_once(
    viewer,
    '''    if scene_box is None:\n        scene_box = [0.0, 0.0, 1.0, 1.0]\n''',
    '''    # 일부 통신망 CAD는 케이블을 ESSENPOLY 사용자 객체로 저장한다.\n    # 손상된 310 바이너리 태그와 별개로 Embedded AcDbPolyline의 10/20 좌표는\n    # 정상적으로 남아 있으므로 원본 DXF를 수정하지 않고 Viewer 표시만 복구한다.\n    recovered = recover_essenpoly_polylines(input_path)\n    by_handle = {e.handle: e for e in entities if e.handle}\n    recovered_count = 0\n    for item in recovered:\n        points = item["points"]\n        box = _points_bbox(points)\n        if box is None:\n            continue\n        layer = item["layer"]\n        color = "#d4d7dc"\n        try:\n            aci = abs(int(doc.layers.get(layer).dxf.color))\n            if 1 <= aci <= 255:\n                color = _contrast_color(_rgb_hex(aci2rgb(aci)))\n        except Exception:\n            pass\n\n        target = by_handle.get(item.get("handle", ""))\n        if target is not None and not target.primitives:\n            target.layer = layer\n            target.primitives = [("polyline", points)]\n            target.bbox = tuple(box)\n            target.color = color\n            target.attributes.update(item.get("attributes", {}))\n            if unsupported.get("ESSENPOLY", 0) > 0:\n                unsupported["ESSENPOLY"] -= 1\n                if unsupported["ESSENPOLY"] <= 0:\n                    unsupported.pop("ESSENPOLY", None)\n        elif target is None:\n            idx = len(entities)\n            entity = VisualEntity(\n                index=idx,\n                entity_type="ESSENPOLY",\n                layer=layer,\n                handle=item.get("handle", ""),\n                primitives=[("polyline", points)],\n                bbox=tuple(box),\n                color=color,\n                attributes=item.get("attributes", {}),\n            )\n            entities.append(entity)\n            if entity.handle:\n                by_handle[entity.handle] = entity\n        else:\n            continue\n        scene_box = _merge_bbox(scene_box, box)\n        recovered_count += 1\n\n    if recovered_count:\n        log(f"ESSENPOLY 케이블/선로 {recovered_count}개 Viewer 복구")\n\n    if scene_box is None:\n        scene_box = [0.0, 0.0, 1.0, 1.0]\n''',
    "ESSENPOLY scene recovery",
)
viewer_path.write_text(viewer, encoding="utf-8")

print("UI policy patches applied: v3.8 / ESSENPOLY recovery / parcel default OFF")
