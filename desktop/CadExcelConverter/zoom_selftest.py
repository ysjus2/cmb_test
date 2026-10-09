from types import SimpleNamespace
import tkinter as tk
from viewer import DXFViewer, Scene, VisualEntity
from zoom_policy import detail_level, layer_level, ZOOM_STEP, MAX_LEVEL, intersects

def main():
    assert detail_level(1, 1) == 0
    assert detail_level(.5, 1) == 0
    assert intersects((-100, 0, 100, 0), (-1, -1, 1, 1))
    assert not intersects((20, 20, 30, 30), (-1, -1, 1, 1))
    root = tk.Tk()
    root.geometry('1000x700')
    viewer = DXFViewer(root)
    viewer.pack(fill='both', expand=True)
    root.update()
    layers = ['TL_SCCO_SIG', 'CN_F_Cable_FOC', 'CN_C_Cable_500F', 'CN_C_ONU', 'CN_L_Pole_ID']
    entities = [VisualEntity(i, 'LINE', layer, str(i), primitives=[('line', [(-100, i), (100, i)])], bbox=(-100, i, 100, i)) for i, layer in enumerate(layers)]
    entities[1].primitives.append(('text', (0, 1, 'fiber ID')))
    entities[-1].primitives = [('text', (0, 4, 'POLE ID'))]
    entities.append(VisualEntity(5, 'SOLID', '0', '5', primitives=[('polygon', [(-10, -10), (10, -10), (10, 10), (-10, 10)])], bbox=(-10, -10, 10, 10)))
    viewer.load_scene(Scene(entities, (-100, -20, 100, 20), {}))
    reference = viewer.lod_reference_scale
    assert {i for i, ids in viewer.entity_items.items() if ids} == {0, 1}
    previous = set()
    for level in range(MAX_LEVEL + 1):
        viewer.scale = reference * ZOOM_STEP ** level
        # Keep the crossing cables and labels in view at every detail level.
        viewer.ox = 500
        viewer.oy = 350
        for ent in entities:
            ent.bbox = (-100, 0, 100, 0)
            ent.primitives = [('line', [(-100, 0), (100, 0)])] if ent.index < 4 else ent.primitives
        viewer.redraw()
        shown = {i for i, ids in viewer.entity_items.items() if ids}
        assert 1 in shown, (level, shown)
        if level >= 5:
            assert 2 in shown, (level, shown)
        assert previous <= shown, (level, previous, shown)
        previous = shown
        assert bool(viewer.canvas.find_withtag('annotation')) == (level == MAX_LEVEL)
    order = viewer.canvas.find_all()
    cables = viewer.canvas.find_withtag('cable')
    fills = viewer.canvas.find_withtag('area_fill')
    assert fills and cables
    assert max(order.index(i) for i in fills) < min(order.index(i) for i in cables)
    viewer.fit_view()
    assert detail_level(viewer.scale, viewer.lod_reference_scale) == 0
    assert {i for i, ids in viewer.entity_items.items() if ids} == {0, 1}
    root.destroy()
    print('ZOOM SELFTEST OK: initial overview, 15 levels, cumulative cables, labels, crossing viewport, stacking, reset')

if __name__ == '__main__':
    main()
