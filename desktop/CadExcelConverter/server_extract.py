from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from pyproj import Transformer

from server_client_windows import CMBServerClient

GROUPS = ("FIBER", "COAX", "POLE", "CONDUIT", "USER")
GROUP_LABELS = {
    "FIBER": "광",
    "COAX": "동축",
    "POLE": "전주",
    "CONDUIT": "관로",
    "USER": "사용자 지정영역(USER)",
}


def _feature_id(feature):
    p = feature.get("properties") or {}
    return (
        feature.get("id")
        or p.get("regional_object_id")
        or p.get("entity_id")
        or json.dumps(feature.get("geometry") or {}, sort_keys=True, ensure_ascii=False)
    )


def _fetch_bbox_recursive(client, region, bbox, depth=0, max_depth=7):
    west, south, east, north = bbox
    raw = client.online_objects(
        region,
        f"{west},{south},{east},{north}",
        limit=5000,
    ) or {}
    features = list(raw.get("features") or [])
    if len(features) < 5000 or depth >= max_depth:
        return features

    mx = (west + east) / 2.0
    my = (south + north) / 2.0
    cells = [
        (west, south, mx, my),
        (mx, south, east, my),
        (west, my, mx, north),
        (mx, my, east, north),
    ]
    merged = {}
    for cell in cells:
        for feature in _fetch_bbox_recursive(
            client,
            region,
            cell,
            depth + 1,
            max_depth,
        ):
            merged[str(_feature_id(feature))] = feature
    return list(merged.values())


def fetch_region_features(client, region):
    info = client.online_layers(region) or {}
    bounds = info.get("bounds")
    if not bounds:
        return info, []

    bbox = (
        float(bounds["west"]),
        float(bounds["south"]),
        float(bounds["east"]),
        float(bounds["north"]),
    )
    return info, _fetch_bbox_recursive(client, region, bbox)


def export_dxf(path, features, target_epsg=5174):
    import ezdxf

    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    transform = Transformer.from_crs(
        "EPSG:4326",
        f"EPSG:{int(target_epsg)}",
        always_xy=True,
    )

    for feature in features:
        p = feature.get("properties") or {}
        layer = str(p.get("layer") or "SERVER").replace("/", "_")[:240]

        if layer not in doc.layers:
            try:
                doc.layers.add(layer)
            except Exception:
                layer = "SERVER"

        attrs = p.get("attributes") or {}
        fields = attrs.get("fields") if isinstance(attrs, dict) else None
        if not isinstance(fields, dict):
            fields = attrs if isinstance(attrs, dict) else {}

        source_geom = fields.get("_cmb_source_geometry")
        source_epsg = fields.get("_cmb_source_epsg")

        # 신규 업로드 자료: 변환 전 원본 CAD 좌표를 그대로 사용한다.
        if isinstance(source_geom, dict):
            typ = source_geom.get("type")
            coords = source_geom.get("coordinates") or []

            if typ == "Point" and len(coords) >= 2:
                msp.add_point(
                    (float(coords[0]), float(coords[1])),
                    dxfattribs={"layer": layer},
                )
                continue

            if typ == "LineString" and len(coords) >= 2:
                pts = [(float(x), float(y)) for x, y in coords]
                msp.add_lwpolyline(pts, dxfattribs={"layer": layer})
                continue

        # 과거 업로드 자료: 원 CAD 좌표가 없으므로 WGS84를 역변환한다.
        g = feature.get("geometry") or {}
        typ = g.get("type")
        coords = g.get("coordinates") or []

        fallback_transform = transform
        try:
            if source_epsg:
                fallback_transform = Transformer.from_crs(
                    "EPSG:4326",
                    f"EPSG:{int(source_epsg)}",
                    always_xy=True,
                )
        except Exception:
            fallback_transform = transform

        if typ == "Point" and len(coords) >= 2:
            x, y = fallback_transform.transform(float(coords[0]), float(coords[1]))
            msp.add_point((x, y), dxfattribs={"layer": layer})

        elif typ == "LineString" and len(coords) >= 2:
            pts = [
                fallback_transform.transform(float(x), float(y))
                for x, y in coords
            ]
            msp.add_lwpolyline(pts, dxfattribs={"layer": layer})

        elif typ == "MultiLineString":
            for part in coords:
                if len(part) < 2:
                    continue
                pts = [
                    fallback_transform.transform(float(x), float(y))
                    for x, y in part
                ]
                msp.add_lwpolyline(pts, dxfattribs={"layer": layer})

    doc.saveas(path)


class ServerExtractWindow(tk.Toplevel):
    def __init__(
        self,
        master,
        viewer,
        client=None,
        current_user=None,
        source_epsg=5174,
    ):
        super().__init__(master)

        self.viewer = viewer
        self.client = client or CMBServerClient()
        self.current_user = current_user or {}
        self.source_epsg = int(source_epsg)
        self.region_rows = []
        self.layer_summary = {}

        self.group_vars = {
            g: tk.BooleanVar(value=False)
            for g in GROUPS
        }

        self.title("관리자 · 서버 도면 내려받기")
        self.geometry("760x500")
        self.minsize(680, 440)
        self.transient(master)

        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="서버 도면 내려받기 · 비상 복구용",
            font=("Malgun Gothic", 16, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=(
                "원본 DXF 분실 등에 대비한 전체 복구 기능입니다. "
                "지역과 종류를 선택하면 선택 종류의 서버 저장 객체 전체를 내려받습니다. "
                "영역 추출은 맵추출 뷰어의 '사용자 지정 영역 추출'을 사용합니다."
            ),
            wraplength=710,
        ).pack(anchor="w", pady=(3, 14))

        region_box = ttk.LabelFrame(
            root,
            text="지역 선택",
            padding=10,
        )
        region_box.pack(fill="x")

        self.region_var = tk.StringVar()
        self.region_combo = ttk.Combobox(
            region_box,
            textvariable=self.region_var,
            state="readonly",
            width=44,
        )
        self.region_combo.pack(side="left", fill="x", expand=True)
        self.region_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.refresh_region_info(),
        )

        ttk.Button(
            region_box,
            text="새로고침",
            command=self.load_regions,
        ).pack(side="left", padx=(8, 0))

        group_box = ttk.LabelFrame(
            root,
            text="내려받을 종류",
            padding=10,
        )
        group_box.pack(fill="x", pady=(12, 0))

        for group in GROUPS:
            ttk.Checkbutton(
                group_box,
                text=GROUP_LABELS[group],
                variable=self.group_vars[group],
                command=self._update_selection_text,
            ).pack(
                side="left",
                padx=(0, 14),
            )

        self.region_info = tk.StringVar(value="지역을 선택해주세요.")
        ttk.Label(
            root,
            textvariable=self.region_info,
            justify="left",
            wraplength=710,
        ).pack(anchor="w", pady=(14, 4))

        self.selection_text = tk.StringVar(value="선택 종류: 없음")
        ttk.Label(
            root,
            textvariable=self.selection_text,
        ).pack(anchor="w", pady=(0, 8))

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(10, 0))

        ttk.Button(
            controls,
            text="전체 종류 선택",
            command=lambda: self._set_all_groups(True),
        ).pack(side="left")

        ttk.Button(
            controls,
            text="전체 해제",
            command=lambda: self._set_all_groups(False),
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            controls,
            text="선택 종류 전체 DXF 내려받기",
            command=self.save_dxf,
        ).pack(side="right")

        self.status = tk.StringVar(value="")
        ttk.Label(
            root,
            textvariable=self.status,
        ).pack(fill="x", pady=(12, 0))

        self.after(0, self.load_regions)

    def load_regions(self):
        try:
            rows = self.client.online_regions() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("regions") or []

            self.region_rows = list(rows)
            labels = []

            for row in self.region_rows:
                rid = str(
                    row.get("id")
                    or row.get("region_id")
                    or ""
                )
                name = str(row.get("name") or rid)
                labels.append(f"{name} ({rid})")

            self.region_combo["values"] = labels

            if labels:
                self.region_combo.current(0)
                self.refresh_region_info()
            else:
                self.region_info.set("서버에 등록된 지역이 없습니다.")

            self.status.set(f"등록 지역 {len(labels)}개")

        except Exception as exc:
            messagebox.showerror(
                "지역 조회 오류",
                str(exc),
                parent=self,
            )

    def _selected_region_id(self):
        idx = self.region_combo.current()
        if idx < 0 or idx >= len(self.region_rows):
            return ""

        row = self.region_rows[idx]
        return str(
            row.get("id")
            or row.get("region_id")
            or ""
        )

    def refresh_region_info(self):
        region = self._selected_region_id()
        if not region:
            self.region_info.set("지역을 선택해주세요.")
            return

        try:
            info = self.client.online_layers(region) or {}
            layers = list(info.get("layers") or [])

            summary = {g: 0 for g in GROUPS}
            for row in layers:
                group = str(row.get("group_id") or "").upper()
                if group in summary:
                    summary[group] += int(row.get("object_count") or 0)

            self.layer_summary = summary

            parts = [
                f"{GROUP_LABELS[g]} {summary[g]:,}개"
                for g in GROUPS
            ]
            self.region_info.set(
                f"{region} · " + " / ".join(parts)
            )

        except Exception as exc:
            self.region_info.set(f"{region} · 정보 조회 실패")
            self.status.set(str(exc))

    def _set_all_groups(self, value):
        for var in self.group_vars.values():
            var.set(bool(value))
        self._update_selection_text()

    def _update_selection_text(self):
        groups = [
            GROUP_LABELS[g]
            for g, var in self.group_vars.items()
            if var.get()
        ]
        self.selection_text.set(
            "선택 종류: " + (", ".join(groups) if groups else "없음")
        )

    def _selection(self):
        region = self._selected_region_id()
        if not region:
            raise RuntimeError("지역을 선택해주세요.")

        groups = {
            group
            for group, var in self.group_vars.items()
            if var.get()
        }
        if not groups:
            raise RuntimeError(
                "광/동축/전주/관로/사용자 지정영역(USER) 중 "
                "하나 이상 선택해주세요."
            )

        return region, groups

    def _collect(self):
        region, groups = self._selection()

        self.status.set("서버 전체 객체 조회 중...")
        self.update_idletasks()

        _info, features = fetch_region_features(
            self.client,
            region,
        )

        filtered = [
            feature
            for feature in features
            if str(
                (feature.get("properties") or {}).get("group_id")
                or ""
            ).upper() in groups
        ]

        if not filtered:
            raise RuntimeError(
                "선택한 지역/종류에 서버 저장 객체가 없습니다."
            )

        self.status.set(
            f"복구 대상 {len(filtered):,}개 객체"
        )
        return region, groups, filtered

    def save_dxf(self):
        try:
            region, groups, features = self._collect()

            suffix = "_".join(
                group
                for group in GROUPS
                if group in groups
            )

            out = filedialog.asksaveasfilename(
                title="비상 복구 DXF 내려받기",
                defaultextension=".dxf",
                initialfile=f"{region}_{suffix}_RECOVERY.dxf",
                filetypes=[("DXF", "*.dxf")],
                parent=self,
            )
            if not out:
                return

            export_dxf(
                out,
                features,
                self.source_epsg,
            )

            meta = Path(out).with_suffix(".json")
            meta.write_text(
                json.dumps(
                    {
                        "region": region,
                        "groups": sorted(groups),
                        "features": features,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            messagebox.showinfo(
                "내려받기 완료",
                (
                    f"{region}\n"
                    f"종류: {', '.join(GROUP_LABELS[g] for g in GROUPS if g in groups)}\n"
                    f"객체: {len(features):,}개\n\n"
                    "DXF 복구본과 속성 보존용 JSON을 함께 저장했습니다."
                ),
                parent=self,
            )

        except Exception as exc:
            messagebox.showerror(
                "서버 도면 내려받기 오류",
                str(exc),
                parent=self,
            )
