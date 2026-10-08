from pathlib import Path

p=Path('viewer.py')
s=p.read_text(encoding='utf8')
color_fix='''_original_display_color_for_layer = _display_color_for_layer


def _display_color_for_layer(doc, layer_name, aci=None, true_color=None):
    # Explicit CAD entity colors always win over the conduit display default.
    if true_color is not None or aci not in (None, 0, 256):
        return _original_display_color_for_layer(doc, layer_name, aci, true_color)
    try:
        layer = doc.layers.get(layer_name)
        layer_rgb = getattr(layer.dxf, 'true_color', None)
        if layer_rgb is not None:
            value = int(layer_rgb)
            return f'#{(value >> 16) & 255:02x}{(value >> 8) & 255:02x}{value & 255:02x}'
        layer_aci = abs(int(layer.dxf.color))
    except Exception:
        layer_aci = 7
    if str(layer_name).upper() == 'CN_L_POLE_LINE_CONDUIT' and layer_aci in (0, 7, 256):
        return '#00ffff'  # CAD cyan: conduit display color requested by the user.
    return _original_display_color_for_layer(doc, layer_name, aci, true_color)

'''
marker='def build_scene(input_path, log=None, progress=None):'
if marker not in s:raise RuntimeError('Scene build marker missing')
s=s.replace(marker,color_fix+marker,1)
p.write_text(s,encoding='utf8')
p=Path('main.py')
s=p.read_text(encoding='utf8').replace('v3.22','v3.23')
p.write_text(s,encoding='utf8')
print('v3.23 conduit color applied: CAD cyan; explicit entity/layer colors preserved')
