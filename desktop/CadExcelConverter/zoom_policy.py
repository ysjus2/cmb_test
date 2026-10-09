"""Cumulative drawing detail, relative to the initial whole-drawing view."""
import math

MAX_LEVEL = 14
ZOOM_STEP = 1.35

def detail_level(scale, reference):
    if reference <= 0 or scale <= reference:
        return 0
    return min(MAX_LEVEL, max(0, int(math.log(scale / reference) / math.log(ZOOM_STEP) + 1e-8)))

def layer_level(layer):
    name = str(layer or '').strip().upper()
    if name == 'TL_SCCO_SIG' or any(k in name for k in ('F_CABLE', 'FOC', 'FIBER', 'OPTIC', '광케이블', '광선로', '시군구')):
        return 0
    for prefixes, level in (
        (('CN_C_CELLBOUND',), 1), (('CN_C_CELLNO',), 2),
        (('CN_C_ONU',), 3), (('TL_SPRD_RW',), 4),
        (('CN_C_CABLE', 'COAX', '동축'), 5), (('CN_C_AMP',), 6),
        (('CN_F_CLOSURE', 'CN_F_CENTER', 'CN_F_TERMINAL'), 7),
        (('CN_C_POWER', 'CN_C_TAP', 'CN_C_PASSIVE', 'CN_C_CONNECTOR', 'CN_C_DC_', 'CN_C_SUBSCRIBERS', 'CN_C_NMS_'), 8),
        (('건물',), 9), (('CN_M_USER_',), 10),
        (('CN_L_POLE_POLE', 'CN_L_POLE_MANHOLE', 'CN_L_POLE_HANDHOLE', 'CN_L_POLE_LINE_'), 11),
    ):
        if name.startswith(prefixes):
            return level
    if name == 'CN_L_POLE':
        return 11
    if name == '0':
        return 12
    if any(k in name for k in ('_ID', 'TEXT', 'LABEL', '지번')):
        return MAX_LEVEL
    return 13

def intersects(box, viewport):
    return box is None or not (box[2] < viewport[0] or box[0] > viewport[2] or box[3] < viewport[1] or box[1] > viewport[3])
