import re

DEFAULT_HIDDEN_LAYERS = frozenset({
    "지번",
    "cn_l_pole_id",
    "cn_c_tap_window",
})

_INFO_TOKENS = (
    "지번",
    "jibun",
    "address",
    "addr",
    "info",
    "annotation",
    "anno",
    "label",
    "text",
    "note",
)

_ID_SEGMENT_RE = re.compile(r"(^|[_-])id([_-]|$)", re.IGNORECASE)


def is_default_hidden(layer_name):
    name = str(layer_name or "").strip()
    folded = name.casefold()
    if folded in DEFAULT_HIDDEN_LAYERS:
        return True
    if any(token in folded for token in _INFO_TOKENS):
        return True
    # CN_F_ID_OTE, CN_C_ID_xxx 등 정보/ID 전용 레이어는 첫 화면에서 제외한다.
    if folded.startswith("cn_") and _ID_SEGMENT_RE.search(folded):
        return True
    return False
