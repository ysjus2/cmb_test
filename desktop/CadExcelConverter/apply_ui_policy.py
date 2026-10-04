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
    'APP_NAME = "CMB DXF Viewer + Excel v3.10"',
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

converter_path = Path("converter.py")
converter = converter_path.read_text(encoding="utf-8")
converter = replace_once(
    converter,
    'from pyproj import Transformer\n',
    'from pyproj import Transformer\n\nfrom essenpoly_recovery import recover_essenpoly_polylines\n',
    "ESSENPOLY Excel recovery import",
)
converter = replace_once(
    converter,
    '''    transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)\n    grouped = {name: [] for name in selected}\n''',
    '''    transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)\n\n    # Viewer와 동일한 ESSENPOLY 복구 데이터를 Excel 추출에도 사용한다.\n    # 같은 handle의 사용자 객체는 빈 행 대신 실제 Embedded AcDbPolyline 좌표/XDATA로 대체한다.\n    recovered_items = recover_essenpoly_polylines(input_path)\n    recovered_by_handle = {\n        item.get("handle", ""): item\n        for item in recovered_items\n        if item.get("handle")\n    }\n    recovered_seen = set()\n\n    grouped = {name: [] for name in selected}\n''',
    "ESSENPOLY Excel recovery setup",
)
old_loop = '''        if layer in grouped:\n            entity_counts[layer] += 1\n            stats.entities += 1\n            typ = ent.dxftype()\n            handle = _norm(getattr(ent.dxf, "handle", ""))\n            block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else ""\n            attrs = _joined_attrs(_attributes(ent))\n            xdata = _xdata_text(doc, ent)\n            text = _entity_text(ent)\n            points = entity_points(ent)\n            length = _length(points)\n            if points:\n                for seq, (x, y) in enumerate(points, 1):\n                    try:\n                        lon, lat = transformer.transform(x, y)\n                    except Exception:\n                        lon, lat = None, None\n                    grouped[layer].append([\n                        typ, handle, block, seq, x, y, lon, lat,\n                        length, text, attrs, xdata,\n                    ])\n                    stats.rows += 1\n            else:\n                grouped[layer].append([\n                    typ, handle, block, 0, None, None, None, None,\n                    0, text, attrs, xdata,\n                ])\n                stats.rows += 1\n                stats.skipped += 1\n'''
new_loop = '''        if layer in grouped:\n            typ = ent.dxftype()\n            handle = _norm(getattr(ent.dxf, "handle", ""))\n            recovered = recovered_by_handle.get(handle) if typ == "ESSENPOLY" else None\n\n            entity_counts[layer] += 1\n            stats.entities += 1\n            block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else ""\n            text = _entity_text(ent)\n\n            if recovered is not None:\n                recovered_seen.add(handle)\n                points = recovered.get("points", [])\n                meta = dict(recovered.get("attributes", {}))\n                if recovered.get("color_aci") is not None:\n                    meta["CAD_COLOR_ACI"] = recovered.get("color_aci")\n                if recovered.get("true_color") is not None:\n                    meta["CAD_TRUE_COLOR"] = recovered.get("true_color")\n                meta["RECOVERED_TYPE"] = "ESSENPOLY/Embedded AcDbPolyline"\n                attrs = _joined_attrs(meta)\n                xmap = recovered.get("xdata", {})\n                xdata = " | ".join(\n                    f"{appid}: " + " ; ".join(values)\n                    for appid, values in xmap.items()\n                    if values\n                )\n            else:\n                attrs = _joined_attrs(_attributes(ent))\n                xdata = _xdata_text(doc, ent)\n                points = entity_points(ent)\n\n            length = _length(points)\n            if points:\n                for seq, (x, y) in enumerate(points, 1):\n                    try:\n                        lon, lat = transformer.transform(x, y)\n                    except Exception:\n                        lon, lat = None, None\n                    grouped[layer].append([\n                        typ, handle, block, seq, x, y, lon, lat,\n                        length, text, attrs, xdata,\n                    ])\n                    stats.rows += 1\n            else:\n                grouped[layer].append([\n                    typ, handle, block, 0, None, None, None, None,\n                    0, text, attrs, xdata,\n                ])\n                stats.rows += 1\n                stats.skipped += 1\n'''
converter = replace_once(converter, old_loop, new_loop, "ESSENPOLY Excel row replacement")
converter = replace_once(
    converter,
    '''    progress(78, "Excel 시트 생성")\n''',
    '''    # recover/explore 과정에서 표준 modelspace에 남지 않은 ESSENPOLY도 원문 복구본에서 추가한다.\n    for recovered in recovered_items:\n        handle = recovered.get("handle", "")\n        layer = recovered.get("layer", "")\n        if layer not in grouped or (handle and handle in recovered_seen):\n            continue\n        points = recovered.get("points", [])\n        if not points:\n            continue\n        meta = dict(recovered.get("attributes", {}))\n        if recovered.get("color_aci") is not None:\n            meta["CAD_COLOR_ACI"] = recovered.get("color_aci")\n        if recovered.get("true_color") is not None:\n            meta["CAD_TRUE_COLOR"] = recovered.get("true_color")\n        meta["RECOVERED_TYPE"] = "ESSENPOLY/Embedded AcDbPolyline"\n        attrs = _joined_attrs(meta)\n        xmap = recovered.get("xdata", {})\n        xdata = " | ".join(\n            f"{appid}: " + " ; ".join(values)\n            for appid, values in xmap.items()\n            if values\n        )\n        length = _length(points)\n        entity_counts[layer] += 1\n        stats.entities += 1\n        for seq, (x, y) in enumerate(points, 1):\n            try:\n                lon, lat = transformer.transform(x, y)\n            except Exception:\n                lon, lat = None, None\n            grouped[layer].append([\n                "ESSENPOLY", handle, "", seq, x, y, lon, lat,\n                length, "", attrs, xdata,\n            ])\n            stats.rows += 1\n        if handle:\n            recovered_seen.add(handle)\n\n    recovered_exported = len(recovered_seen)\n    if recovered_exported:\n        log(f"ESSENPOLY 케이블/선로 {recovered_exported}개 Excel 데이터 복구")\n\n    progress(78, "Excel 시트 생성")\n''',
    "ESSENPOLY unmatched Excel export",
)
converter_path.write_text(converter, encoding="utf-8")

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
    '''def _resolve_entity_color(doc, entity, layer_name, inherited=None):\n''',
    '''def _is_optical_cable_layer(layer_name):\n    name = str(layer_name or "")\n    upper = name.upper()\n    return (\n        "F_CABLE" in upper\n        or "FOC" in upper\n        or "FIBER" in upper\n        or "OPTIC" in upper\n        or "광케이블" in name\n        or "광선로" in name\n    )\n\ndef _is_cable_layer(layer_name):\n    name = str(layer_name or "")\n    upper = name.upper()\n    return _is_optical_cable_layer(name) or "CABLE" in upper or "케이블" in name or "선로" in name\n\ndef _display_color_for_layer(doc, layer_name, aci=None, true_color=None):\n    # Cable colors carry field meaning (especially coax power state), so cable\n    # layers must keep the original CAD color without brightness substitution.\n    raw = None\n    try:\n        if true_color is not None:\n            value = int(true_color)\n            raw = f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}"\n    except Exception:\n        raw = None\n    if raw is None:\n        try:\n            if aci is not None:\n                value = abs(int(aci))\n                if 1 <= value <= 255:\n                    raw = _rgb_hex(aci2rgb(value))\n        except Exception:\n            raw = None\n    if raw is None:\n        try:\n            layer = doc.layers.get(layer_name)\n            value = abs(int(layer.dxf.color))\n            if 1 <= value <= 255:\n                raw = _rgb_hex(aci2rgb(value))\n        except Exception:\n            raw = None\n    if raw is None:\n        raw = "#d4d7dc"\n    return raw if _is_cable_layer(layer_name) else _contrast_color(raw)\n\ndef _resolve_entity_color(doc, entity, layer_name, inherited=None):\n''',
    "cable color helpers",
)
viewer = replace_once(
    viewer,
    '''            return _contrast_color(f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}")\n''',
    '''            raw = f"#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}"\n            return raw if _is_cable_layer(layer_name) else _contrast_color(raw)\n''',
    "true color preserve for cables",
)
viewer = replace_once(
    viewer,
    '''            return _contrast_color(_rgb_hex(aci2rgb(color)))\n''',
    '''            raw = _rgb_hex(aci2rgb(color))\n            return raw if _is_cable_layer(layer_name) else _contrast_color(raw)\n''',
    "ACI color preserve for cables",
)
viewer = replace_once(
    viewer,
    '''            return _contrast_color(_rgb_hex(aci2rgb(layer_color)))\n''',
    '''            raw = _rgb_hex(aci2rgb(layer_color))\n            return raw if _is_cable_layer(layer_name) else _contrast_color(raw)\n''',
    "layer color preserve for cables",
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
    '''    # 일부 통신망 CAD는 케이블을 ESSENPOLY 사용자 객체로 저장한다.\n    # 손상된 310 바이너리 태그와 별개로 Embedded AcDbPolyline의 10/20 좌표는\n    # 정상적으로 남아 있으므로 원본 DXF를 수정하지 않고 Viewer 표시만 복구한다.\n    recovered = recover_essenpoly_polylines(input_path)\n    by_handle = {e.handle: e for e in entities if e.handle}\n    recovered_count = 0\n    for item in recovered:\n        points = item["points"]\n        box = _points_bbox(points)\n        if box is None:\n            continue\n        layer = item["layer"]\n        color = _display_color_for_layer(\n            doc,\n            layer,\n            aci=item.get("color_aci"),\n            true_color=item.get("true_color"),\n        )\n\n        target = by_handle.get(item.get("handle", ""))\n        if target is not None and not target.primitives:\n            target.layer = layer\n            target.primitives = [("polyline", points)]\n            target.bbox = tuple(box)\n            target.color = color\n            target.attributes.update(item.get("attributes", {}))\n            if unsupported.get("ESSENPOLY", 0) > 0:\n                unsupported["ESSENPOLY"] -= 1\n                if unsupported["ESSENPOLY"] <= 0:\n                    unsupported.pop("ESSENPOLY", None)\n        elif target is None:\n            idx = len(entities)\n            entity = VisualEntity(\n                index=idx,\n                entity_type="ESSENPOLY",\n                layer=layer,\n                handle=item.get("handle", ""),\n                primitives=[("polyline", points)],\n                bbox=tuple(box),\n                color=color,\n                attributes=item.get("attributes", {}),\n            )\n            entities.append(entity)\n            if entity.handle:\n                by_handle[entity.handle] = entity\n        else:\n            continue\n        scene_box = _merge_bbox(scene_box, box)\n        recovered_count += 1\n\n    if recovered_count:\n        log(f"ESSENPOLY 케이블/선로 {recovered_count}개 Viewer 복구")\n\n    if scene_box is None:\n        scene_box = [0.0, 0.0, 1.0, 1.0]\n''',
    "ESSENPOLY scene recovery",
)
viewer = replace_once(
    viewer,
    '''                        if len(coords) >= 4:\n                            ids.append(c.create_line(*coords, fill=color, width=width))\n''',
    '''                        if len(coords) >= 4:\n                            # 광케이블은 CAD 내부 Polyline 정점 순서의 마지막 점을\n                            # 현재 도면의 IN 방향으로 간주해 화살표를 표시한다.\n                            # 동축 및 기타 케이블에는 방향 화살표를 표시하지 않는다.\n                            if _is_optical_cable_layer(ent.layer):\n                                ids.append(c.create_line(\n                                    *coords, fill=color, width=max(width, 2),\n                                    arrow=tk.LAST, arrowshape=(10, 12, 5),\n                                ))\n                            else:\n                                ids.append(c.create_line(*coords, fill=color, width=width))\n''',
    "fiber IN direction arrow",
)
viewer_path.write_text(viewer, encoding="utf-8")

print("UI policy patches applied: v3.10 / ESSENPOLY Excel export / cable colors / fiber IN arrows")
