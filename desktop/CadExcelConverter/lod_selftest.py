from types import SimpleNamespace

from viewer import Scene, VisualEntity, _lod_group, _zoom_lod


def ent(index, layer, bbox=(10.0, 10.0, 20.0, 20.0)):
    return VisualEntity(
        index=index,
        entity_type="LINE",
        layer=layer,
        handle=f"H{index}",
        primitives=[("line", [(bbox[0], bbox[1]), (bbox[2], bbox[3])])],
        bbox=bbox,
    )


def main():
    # Exact group contract.
    samples = [
        ("CN_F_Cable_FOC", 0),
        ("CN_C_CellBound", 1),
        ("CN_C_CellNo", 2),
        ("CN_C_ONU", 3),
        ("TL_SPRD_RW", 4),
        ("CN_C_Cable_500F", 5),
        ("CN_C_AmpTBA", 6),
        ("CN_F_Closure", 7),
        ("CN_C_Passive", 8),
        ("건물_건물군", 9),
        ("CN_M_User_Test", 10),
        ("CN_L_Pole_Line_Conduit", 11),
        ("0", 12),
        ("CN_C_ID_Tap", 14),
        ("CN_F_ID_OTE", 14),
        ("CN_L_Pole_ID", 14),
        ("CN_Pole_ID", 14),
        ("TEXT_MISC", 14),
    ]
    for i, (layer, expected) in enumerate(samples):
        got = _lod_group(ent(i, layer))
        assert got == expected, (layer, got, expected)

    # Stage-specific indices must remain independently queryable.
    entities = [ent(i, layer) for i, (layer, _group) in enumerate(samples)]
    scene = Scene(entities, (0.0, 0.0, 100.0, 100.0), {})
    scene.build_index()
    viewport = (0.0, 0.0, 100.0, 100.0)

    upto5 = scene.query_lod_upto(viewport, 5)
    groups5 = {_lod_group(scene.entities[i]) for i in upto5}
    assert groups5 == {0, 1, 2, 3, 4, 5}, groups5
    assert all(_lod_group(scene.entities[i]) <= 5 for i in upto5)

    upto12 = scene.query_lod_upto(viewport, 12)
    groups12 = {_lod_group(scene.entities[i]) for i in upto12}
    assert groups12 == set(range(0, 13)) - {13}, groups12
    assert not any(_lod_group(scene.entities[i]) == 14 for i in upto12)

    upto14 = scene.query_lod_upto(viewport, 14)
    assert any(scene.entities[i].layer == "CN_F_Cable_FOC" for i in upto14)
    assert any(scene.entities[i].layer == "CN_C_Cable_500F" for i in upto14)
    assert any(scene.entities[i].layer == "CN_C_ID_Tap" for i in upto14)
    assert any(scene.entities[i].layer == "CN_F_ID_OTE" for i in upto14)

    # Wheel threshold contract:
    # 0..4 use 5-notch intervals, from coax stage onward use 2,
    # and final ID/TEXT waits 5 additional notches.
    ref = 1.0
    viewer = SimpleNamespace(lod_reference_scale=ref, fit_scale=ref, scale=ref)
    assert _zoom_lod(viewer) == 0

    viewer.scale = ref * (1.15 ** 25) * 1.000001
    assert _zoom_lod(viewer) == 5, _zoom_lod(viewer)

    viewer.scale = ref * (1.15 ** 47.999)
    assert _zoom_lod(viewer) == 13, _zoom_lod(viewer)

    viewer.scale = ref * (1.15 ** 48) * 1.000001
    assert _zoom_lod(viewer) == 14, _zoom_lod(viewer)

    print("LOD self-test OK: stage mapping, cumulative 0..N visibility, cable retention, and delayed final ID/TEXT verified")


if __name__ == "__main__":
    main()
