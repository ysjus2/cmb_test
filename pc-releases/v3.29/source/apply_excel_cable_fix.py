from pathlib import Path


converter_path = Path("converter.py")
text = converter_path.read_text(encoding="utf-8")
start = text.index("def convert_selected_layers(")
end = text.index("\ndef convert_file(", start)

replacement = r'''def convert_selected_layers(
    input_path,
    output_path,
    selected_layers,
    source_epsg=5174,
    oda_exe=None,
    log=None,
    progress=None,
):
    log = log or (lambda msg: None)
    progress = progress or (lambda percent, task: None)
    selected = list(dict.fromkeys(selected_layers))
    if not selected:
        raise ValueError("추출할 레이어를 하나 이상 선택해주세요.")

    progress(5, "DXF 읽기")
    doc = load_dxf_document(input_path, log)
    transformer = Transformer.from_crs(f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)
    grouped = {name: [] for name in selected}
    entity_counts = {name: 0 for name in selected}
    stats = ConversionStats(layers=len(selected))

    # IMPORTANT:
    # 손상 DXF를 ezdxf recover로 읽으면 ESSENPOLY의 원래 레이어가 '0'으로
    # 바뀌는 도면이 있다. 따라서 ESSENPOLY는 modelspace 값을 신뢰하지 않고
    # 원본 ASCII DXF에서 복구한 실제 layer/handle/point/xdata를 직접 출력한다.
    recovered_items = recover_essenpoly_polylines(input_path)
    recovered_handles = {item.get("handle", "") for item in recovered_items if item.get("handle")}

    entities = list(doc.modelspace())
    total = max(1, len(entities))
    for index, ent in enumerate(entities, 1):
        typ = ent.dxftype()
        handle = _norm(getattr(ent.dxf, "handle", ""))

        # ESSENPOLY는 아래 원문 복구 단계에서만 처리한다.
        # 여기서 처리하면 recover가 만든 layer=0 빈 행이 Excel에 섞인다.
        if typ == "ESSENPOLY" or (handle and handle in recovered_handles):
            if index == total or index % max(1, total // 100) == 0:
                progress(15 + int(index / total * 55), f"객체 분석 {index:,}/{total:,}")
            continue

        layer = _norm(getattr(ent.dxf, "layer", "0")) or "0"
        if layer in grouped:
            entity_counts[layer] += 1
            stats.entities += 1
            block = _norm(getattr(ent.dxf, "name", "")) if typ == "INSERT" else ""
            attrs = _joined_attrs(_attributes(ent))
            xdata = _xdata_text(doc, ent)
            text_value = _entity_text(ent)
            points = entity_points(ent)
            length = _length(points)
            if points:
                for seq, (x, y) in enumerate(points, 1):
                    try:
                        lon, lat = transformer.transform(x, y)
                    except Exception:
                        lon, lat = None, None
                    grouped[layer].append([
                        typ, handle, block, seq, x, y, lon, lat,
                        length, text_value, attrs, xdata,
                    ])
                    stats.rows += 1
            else:
                grouped[layer].append([
                    typ, handle, block, 0, None, None, None, None,
                    0, text_value, attrs, xdata,
                ])
                stats.rows += 1
                stats.skipped += 1

        if index == total or index % max(1, total // 100) == 0:
            progress(15 + int(index / total * 55), f"객체 분석 {index:,}/{total:,}")

    # ESSENPOLY는 원본 DXF 텍스트의 실제 레이어명으로 직접 출력한다.
    recovered_count = 0
    recovered_rows = 0
    per_layer = {}
    for item in recovered_items:
        layer = _norm(item.get("layer", ""))
        if layer not in grouped:
            continue
        points = item.get("points", [])
        if len(points) < 2:
            continue

        handle = _norm(item.get("handle", ""))
        meta = dict(item.get("attributes", {}))
        if item.get("color_aci") is not None:
            meta["CAD_COLOR_ACI"] = item.get("color_aci")
        if item.get("true_color") is not None:
            meta["CAD_TRUE_COLOR"] = item.get("true_color")
        meta["RECOVERED_TYPE"] = "ESSENPOLY/Embedded AcDbPolyline"
        attrs = _joined_attrs(meta)

        xmap = item.get("xdata", {}) or {}
        xdata = " | ".join(
            f"{appid}: " + " ; ".join(str(v) for v in values)
            for appid, values in xmap.items()
            if values
        )
        length = _length(points)

        entity_counts[layer] += 1
        stats.entities += 1
        recovered_count += 1
        per_layer[layer] = per_layer.get(layer, 0) + 1

        for seq, (x, y) in enumerate(points, 1):
            try:
                lon, lat = transformer.transform(x, y)
            except Exception:
                lon, lat = None, None
            grouped[layer].append([
                "ESSENPOLY", handle, "", seq, x, y, lon, lat,
                length, "", attrs, xdata,
            ])
            stats.rows += 1
            recovered_rows += 1

    if recovered_count:
        summary = ", ".join(f"{k}:{v}" for k, v in sorted(per_layer.items()))
        log(f"ESSENPOLY Excel 직접 복구 {recovered_count}개 / {recovered_rows}행 · {summary}")

    progress(78, "Excel 시트 생성")
    wb = Workbook()
    wb.remove(wb.active)
    used, index_rows = set(), []
    for layer_index, layer in enumerate(selected, 1):
        sheet_name = _safe_sheet_name(layer, used)
        ws = wb.create_sheet(sheet_name)
        _write_sheet(ws, LAYER_HEADERS, grouped[layer])
        index_rows.append([layer, sheet_name, entity_counts[layer], len(grouped[layer])])
        progress(78 + int(layer_index / max(1, len(selected)) * 14), f"시트 {layer_index}/{len(selected)}")

    idx = wb.create_sheet("LAYER_INDEX", 0)
    _write_sheet(idx, ["원본레이어","Excel시트","객체수","출력행수"], index_rows)
    info = wb.create_sheet("INFO")
    _write_sheet(info, ["항목","값"], [
        ["원본파일", str(input_path)],
        ["입력형식", "DXF only"],
        ["원본좌표계", f"EPSG:{source_epsg}"],
        ["출력좌표계", "EPSG:4326 (WGS84)"],
        ["선택레이어수", stats.layers],
        ["대상객체수", stats.entities],
        ["출력행수", stats.rows],
        ["ESSENPOLY복구객체수", recovered_count],
        ["ESSENPOLY복구행수", recovered_rows],
        ["외부전송", "없음 - 로컬 읽기 전용 Viewer/Excel 추출"],
    ])

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    progress(96, "Excel 저장")
    wb.save(out)
    progress(100, "완료")
    log(f"완료: {out}")
    return stats
'''

text = text[:start] + replacement + text[end:]
converter_path.write_text(text, encoding="utf-8")

main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = main.replace(
    'APP_NAME = "CMB DXF Viewer + Excel v3.10"',
    'APP_NAME = "CMB DXF Viewer + Excel v3.11"',
    1,
)
main_path.write_text(main, encoding="utf-8")

print("Applied v3.11 direct ESSENPOLY Excel export fix")
