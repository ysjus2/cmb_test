DEFAULT_HIDDEN_LAYERS = frozenset({'지번', 'cn_l_pole_id', 'cn_c_tap_window'})

def is_default_hidden(layer_name):
    return str(layer_name or '').strip().casefold() in DEFAULT_HIDDEN_LAYERS
