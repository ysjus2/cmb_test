from types import SimpleNamespace
from unittest.mock import patch
from main import App
from viewer import Scene, VisualEntity
from converter import LayerInfo

entities = [
    VisualEntity(0, 'LINE', 'CN_F_Cable_FOC', 'F', primitives=[('line', [(0, 0), (100, 0)])], bbox=(0, 0, 100, 0)),
    VisualEntity(1, 'INSERT', 'CN_F_CLOSURE', 'C', primitives=[('circle', (0, 0, 1))], bbox=(-1, -1, 1, 1)),
    VisualEntity(2, 'LINE', 'TL_SPRD_RW', 'R', primitives=[('line', [(0, 1), (100, 1)])], bbox=(0, 1, 100, 1)),
    VisualEntity(3, 'LINE', 'CN_C_Cable_500F', 'X', primitives=[('line', [(0, 2), (100, 2)])], bbox=(0, 2, 100, 2)),
]
scene = Scene(entities, (-1, -1, 100, 2), {})
entities[0].primitives.append(('text', (50, 0, 'FO-001 cable code')))
app = App()
app.input_path = 'display-test.dxf'
app._populate_layers([LayerInfo(e.layer, 1, e.entity_type) for e in entities], scene)
app.viewer.load_scene(scene)
app.update()
network = SimpleNamespace(edges={'F': SimpleNamespace(index=0)}, positions={'C': (0, 0)})
with patch('network_extract_ui.FiberNetwork', return_value=network):
    app._begin_fiber_route()
assert app.viewer.entity_filter == {0, 1}
assert not app.viewer.entity_items.get(2)
assert not app.viewer.entity_items.get(3)
assert not app.viewer.canvas.find_withtag('annotation')
app.viewer.redraw()  # The start-device click redraw must keep the same filter.
assert not app.viewer.entity_items.get(2)
scope = {'kind': 'fiber', 'indices': {0, 1}, 'route': ['F'], 'network': network}
app._show_scope(scope)
assert app.viewer.entity_filter == {0, 1}
assert app.export_scope is scope
assert app.viewer.entity_items.get(0)
assert not app.viewer.entity_items.get(2)
assert not app.viewer.entity_items.get(3)
assert not app.viewer.canvas.find_withtag('annotation')
app._reset_network_filter()
assert app.viewer.entity_filter is None
assert not app.viewer.hide_extraction_text
app.destroy()
print('FIBER DISPLAY TEST OK: selection and result exclude terrain/coax; export scope and reset preserved')
