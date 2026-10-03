from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"UI patch target not found: {label}")
    return text.replace(old, new, 1)


main_path = Path("main.py")
main = main_path.read_text(encoding="utf-8")
main = replace_once(
    main,
    'APP_NAME = "CMB DXF Viewer + Excel v3.6"',
    'APP_NAME = "CMB DXF Viewer + Excel v3.7"',
    "version",
)
main = replace_once(
    main,
    '''                        self.visible_layers.add(layer.name)\n                        self.checked_layers.add(layer.name)\n                        self.tree.insert("", "end", iid=iid, values=self._row_values(iid))\n''',
    '''                        # 지번은 객체 수가 많아 첫 화면을 가리므로 최초 로딩 때만 OFF.\n                        # 사용자가 다시 체크하면 Viewer 표시와 Excel 추출에 정상 포함된다.\n                        if layer.name.strip() != "지번":\n                            self.visible_layers.add(layer.name)\n                            self.checked_layers.add(layer.name)\n                        self.tree.insert("", "end", iid=iid, values=self._row_values(iid))\n''',
    "default parcel layer off",
)
main_path.write_text(main, encoding="utf-8")

viewer_path = Path("viewer.py")
viewer = viewer_path.read_text(encoding="utf-8")
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
viewer_path.write_text(viewer, encoding="utf-8")

print("UI policy patches applied: v3.7 / parcel layer default OFF / semantic detail values")
