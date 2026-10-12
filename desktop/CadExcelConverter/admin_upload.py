from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from pyproj import Transformer

from drawing_identity import drawing_code
from server_client_windows import CMBServerClient
from backup_v2 import enrich_payload_v2

GROUPS = ("FIBER", "COAX", "POLE", "CONDUIT", "USER")
MANAGED_ITEMS = GROUPS + ("SYMBOL",)
# 전체 업로드는 자주 변경되는 도면 데이터만 교체한다.
# POLE과 SYMBOL은 선택 업로드에서만 처리한다.
FULL_UPLOAD_ITEMS = ("FIBER", "COAX", "CONDUIT", "USER")


def classify_entity(e):
    # 서버 업로드 분류는 실제 CAD 레이어명을 기준으로 단순하게 고정한다.
    layer = str(e.layer or "").strip().upper()
    block = str(e.block_name or "").strip().upper()
    text = f"{layer} {block}"

    # 지형/배경 레이어는 온라인 서버 업로드 대상이 아니다.
    if layer.startswith("TS_") or layer == "TL_SCCO_SIG":
        return None

    # ONU는 현장 운용 기준상 동축 기기로 관리한다.
    # 레이어명이 CN_F_* 계열이더라도 ONU 표기가 있으면 COAX가 우선이다.
    if "ONU" in text:
        return "COAX"

    # 광선로 / 광장비
    if (
        layer.startswith("CN_F_")
        or "F_CABLE" in text
        or "FIBER" in text
        or "FOC" in text
        or "OPTIC" in text
        or "광" in text
    ):
        return "FIBER"

    # 관로/맨홀/핸드홀은 CN_L_POLE 계열 이름을 사용하더라도 CONDUIT가 우선이다.
    if (
        layer.startswith("CN_L_POLE_MANHOLE")
        or layer.startswith("CN_L_POLE_HANDHOLE")
        or layer.startswith("CN_L_POLE_LINE_")
        or any(k in text for k in ("CONDUIT", "MANHOLE", "HANDHOLE", "관로", "맨홀", "핸드홀"))
    ):
        return "CONDUIT"

    # 실제 전주만 POLE 그룹으로 분류한다.
    if (
        layer == "CN_L_POLE"
        or layer.startswith("CN_L_POLE_POLE")
        or any(k in text for k in ("POLE", "전주", "POLE_CATV", "POLE-CATV"))
    ):
        return "POLE"

    # 동축선로 / 동축장비
    if (
        layer.startswith("CN_C_")
        or any(k in text for k in (
            "C_CABLE", "COAX", "RG06", "RG11", "PFC", "AMP", "TAP",
            "PASSIVE", "POWER", "CONNECTOR", "동축", "증폭", "분기",
        ))
    ):
        return "COAX"

    # 사용자/건물 계열
    if layer.startswith("CN_M_USER_") or "USER" in text or "건물" in text:
        return "USER"

    return None


def _symbol_kind(e):
    text = (str(e.layer or "") + " " + str(e.block_name or "") + " " + str(e.entity_type or "")).upper()
    if "ONU" in text:
        return "onu"
    if "AMP" in text:
        return "amp"
    if "MANHOLE" in text:
        return "manhole"
    if "POLE" in text:
        return "pole"
    if "TAP" in text:
        return "tap"
    if any(k in text for k in ("2WAY", "3WAY", "2-WAY", "3-WAY")):
        return "splitter"
    if "POWER" in text or " PS " in f" {text} ":
        return "power_ps"
    if any(k in text for k in ("CLOSURE", "TERMINAL", "CENTER")):
        return "closure"
    return "generic"


def _is_info_entity(e):
    layer = str(e.layer or "").strip().upper()
    block = str(e.block_name or "").strip().upper()
    entity_type = str(e.entity_type or "").strip().upper()

    if entity_type in {"TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION", "LEADER", "MLEADER"}:
        return True

    info_layer_tokens = (
        "CELLNO", "_ID", "TEXT", "LABEL", "JIBUN", "ADDRESS", "ADDR",
        "INFO", "ANNOT", "NOTE", "MEMO",
    )
    if any(token in layer for token in info_layer_tokens):
        return True

    info_block_tokens = ("TEXT", "LABEL", "ID", "ADDR", "ADDRESS", "JIBUN", "INFO", "NOTE", "TAG")
    if any(
        block == token or block.startswith(token + "_") or block.endswith("_" + token)
        for token in info_block_tokens
    ):
        return True

    return False


def _rotation_deg(e):
    data = dict(getattr(e, "dxf_data", {}) or {})
    for key in ("rotation", "ROTATION", "angle", "ANGLE"):
        value = data.get(key)
        if value not in (None, ""):
            try:
                return float(value) % 360.0
            except Exception:
                pass
    return 0.0


def _points(e):
    entity_type = str(e.entity_type or "").upper()

    # INSERT/POINT 장비는 블록 내부 선분보다 삽입점을 우선한다.
    # 그렇지 않으면 장비 블록이 LineString으로 서버에 저장되어
    # 온라인 Viewer에서 기기 심볼로 표시되지 않는다.
    if entity_type in {"INSERT", "POINT"}:
        for kind, data in e.primitives:
            if kind in {"insert", "point"}:
                return [(float(data[0]), float(data[1]))]

        if e.bbox:
            x1, y1, x2, y2 = e.bbox
            return [((x1 + x2) / 2, (y1 + y2) / 2)]

    for kind, data in e.primitives:
        if kind in {"line", "polyline", "polygon"} and len(data) >= 2:
            return [(float(x), float(y)) for x, y in data]
        if kind in {"insert", "point"}:
            return [(float(data[0]), float(data[1]))]

    if e.bbox:
        x1, y1, x2, y2 = e.bbox
        return [((x1 + x2) / 2, (y1 + y2) / 2)]

    return []


def build_payload(scene, source_path, group, epsg, region_code, memo=""):
    transformer = Transformer.from_crs(
        f"EPSG:{int(epsg)}",
        "EPSG:4326",
        always_xy=True,
    )

    region_code = str(region_code or "").strip()
    if not region_code:
        raise RuntimeError("서버 지역코드를 선택해주세요.")

    objects = []

    for e in scene.entities:
        if classify_entity(e) != group:
            continue

        pts = _points(e)
        geo = []

        for x, y in pts:
            lon, lat = transformer.transform(x, y)
            if math.isfinite(lon) and math.isfinite(lat):
                geo.append([lon, lat])

        if not geo:
            continue

        attrs = dict(e.attributes or {})
        dxf = dict(getattr(e, "dxf_data", {}) or {})

        # CAD 원본 색상/선 스타일을 서버까지 보존한다.
        # 특히 COAX 케이블의 빨강/초록/파랑은 전원 상태 의미를 가지므로
        # 그룹 고정색으로 치환하지 않는다.
        style = {}
        display_color = str(getattr(e, "color", "") or "").strip()
        if display_color.startswith("#") and len(display_color) == 7:
            try:
                style["display_color"] = display_color.lower()
                style["true_color"] = int(display_color[1:], 16)
            except Exception:
                pass
        for key in ("color", "true_color", "lineweight", "ltscale"):
            value = dxf.get(key)
            if value not in (None, ""):
                try:
                    if key in ("color", "true_color", "lineweight"):
                        style[key] = int(float(value))
                    else:
                        style[key] = float(value)
                except Exception:
                    pass
        if style:
            attrs["_cmb_style"] = style
        attrs["_cmb_dxf_data"] = dxf

        symbol_kind = _symbol_kind(e)
        attrs["_cmb_symbol_kind"] = symbol_kind
        attrs["_cmb_rotation_deg"] = _rotation_deg(e)
        # POINT는 좌표/정보 표시에 쓰이는 경우가 많으므로 POINT라는 이유만으로
        # 기기로 판정하지 않는다. 실제 INSERT 또는 인식 가능한 기기 심벌만 기기다.
        attrs["_cmb_is_device"] = bool(
            not _is_info_entity(e)
            and (
                str(e.entity_type or "").upper() == "INSERT"
                or symbol_kind != "generic"
            )
        )
        for src_key, dst_key in (
            ("xscale", "_cmb_xscale"),
            ("yscale", "_cmb_yscale"),
            ("zscale", "_cmb_zscale"),
        ):
            value = dxf.get(src_key)
            if value not in (None, ""):
                attrs[dst_key] = value
        pole_info = dict(getattr(e, "pole_info", {}) or {})
        if pole_info:
            attrs["_cmb_pole_info"] = pole_info

        objects.append({
            "source_handle": e.handle,
            "object_id": (
                f"{region_code}_{e.handle}"
                if e.handle else ""
            ),
            "layer": e.layer,
            "entity_type": e.entity_type,
            "block_name": e.block_name,
            "geometry": {
                "type": "Point" if len(geo) == 1 else "LineString",
                "coordinates": geo[0] if len(geo) == 1 else geo,
            },
            "attributes": attrs,
            "xdata": dict(e.xdata or []),
        })

    p = Path(source_path)

    payload = {
        "package_schema": "cmb-network-package-v1",
        "region_code": region_code,
        "group": group,
        "source_epsg": int(epsg),
        "source_file": p.name,
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "object_count": len(objects),
        "memo": str(memo or "").strip(),
        "objects": objects,
    }

    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["package_sha256"] = hashlib.sha256(canonical).hexdigest()

    payload = enrich_payload_v2(
        scene,
        source_path,
        group,
        payload,
        classify_entity,
    )

    canonical_v2 = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["package_sha256"] = hashlib.sha256(canonical_v2).hexdigest()

    return payload


def build_symbol_payload(scene, source_path, region_code, memo=""):
    region_code = str(region_code or "").strip()
    if not region_code:
        raise RuntimeError("서버 지역코드를 선택해주세요.")

    symbols = {}
    for e in scene.entities:
        entity_type = str(e.entity_type or "").upper()
        kind = _symbol_kind(e)
        is_device = (not _is_info_entity(e)) and (entity_type == "INSERT" or kind != "generic")
        if not is_device:
            continue

        block = str(e.block_name or "").strip()
        layer = str(e.layer or "").strip()
        key = block or f"{layer}|{kind}"
        if not key:
            continue

        dxf = dict(getattr(e, "dxf_data", {}) or {})
        symbols[key] = {
            "key": key,
            "symbol_kind": kind,
            "block_name": block,
            "layer": layer,
            "entity_type": entity_type,
            "rotation_default_deg": _rotation_deg(e),
            "xscale": dxf.get("xscale"),
            "yscale": dxf.get("yscale"),
            "zscale": dxf.get("zscale"),
        }

    p = Path(source_path)
    payload = {
        "region_code": region_code,
        "source_file": p.name,
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "memo": str(memo or "").strip(),
        "symbol_count": len(symbols),
        "symbols": list(symbols.values()),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["package_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


class AdminUploadWindow(tk.Toplevel):
    def __init__(self, master, scene, source_path, source_epsg, client=None, current_user=None):
        super().__init__(master)

        self.scene = scene
        self.source_path = source_path
        self.epsg = source_epsg
        self.client = client or CMBServerClient()
        self.current_user = current_user
        self.session_busy = False
        self._busy_generation = 0

        self.title("관리자 · 서버 도면 업로드")
        self.geometry("820x690")
        self.minsize(720, 590)
        self.protocol("WM_DELETE_WINDOW", self._close_requested)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="관리자 서버 도면 업로드",
            font=("Malgun Gothic", 16, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=f"{Path(source_path).name} · EPSG:{source_epsg}",
        ).pack(anchor="w", pady=(3, 6))

        region_box = ttk.LabelFrame(root, text="서버 지역", padding=8)
        region_box.pack(fill="x", pady=(0, 10))
        self.region_var = tk.StringVar(value="")
        self.region_combo = ttk.Combobox(
            region_box,
            textvariable=self.region_var,
            state="disabled",
            width=52,
        )
        self.region_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(
            region_box,
            text="지역 새로고침",
            command=self._load_server_regions,
        ).pack(side="left", padx=(6, 0))
        self.region_rows = []
        self.region_display_to_id = {}

        self.login_status = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.login_status).pack(anchor="w", pady=(0, 10))

        self.tree = ttk.Treeview(
            root,
            columns=("g", "n", "d"),
            show="headings",
            height=9,
        )

        for key, title, width in (
            ("g", "그룹", 100),
            ("n", "객체수", 90),
            ("d", "범위", 540),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width)

        self.tree.pack(fill="x")

        desc = {
            "FIBER": "광케이블 + 광 관련 기기",
            "COAX": "동축케이블 + ONU/AMP/TAP/PASSIVE/POWER/CONNECTOR 등 동축기기",
            "POLE": "전주 + CATV/자가주",
            "CONDUIT": "관로 + 맨홀 + 핸드홀",
            "USER": "사용자 작성 건물/지형/관리구역",
            "SYMBOL": "기기 심볼 정의 · 도면 객체와 별도 관리",
        }

        counts = {g: 0 for g in GROUPS}

        for e in scene.entities:
            g = classify_entity(e)
            if g:
                counts[g] += 1

        symbol_payload = build_symbol_payload(
            scene,
            source_path,
            "PREVIEW",
        )
        counts["SYMBOL"] = int(symbol_payload.get("symbol_count") or 0)
        self.group_counts = counts

        for g in MANAGED_ITEMS:
            scope = desc[g] if counts[g] > 0 else desc[g] + " · 객체 없음(업로드 제외)"
            self.tree.insert(
                "",
                "end",
                iid=g,
                values=(g, f"{counts[g]:,}", scope),
            )

        self.tree.selection_set("FIBER")

        memo_box = ttk.LabelFrame(
            root,
            text="업로드 메모",
            padding=8,
        )
        memo_box.pack(fill="x", pady=(10, 0))

        self.memo_var = tk.StringVar(value="")
        ttk.Entry(
            memo_box,
            textvariable=self.memo_var,
        ).pack(fill="x")
        ttk.Label(
            memo_box,
            text="선택 항목 또는 전체 업로드에 적용할 메모입니다.",
        ).pack(anchor="w", pady=(4, 0))

        row = ttk.Frame(root)
        row.pack(fill="x", pady=12)

        self.upload_one_btn = ttk.Button(
            row,
            text="선택 항목 업로드",
            command=self.upload_selected,
            state="disabled",
        )
        self.upload_one_btn.pack(side="left")

        self.upload_all_btn = ttk.Button(
            row,
            text="현재 도면 전체 업로드",
            command=self.upload_all,
            state="disabled",
        )
        self.upload_all_btn.pack(side="left", padx=6)

        ttk.Button(
            row,
            text="서버 상태 확인",
            command=self.health,
        ).pack(side="left")

        ttk.Button(
            row,
            text="현재 업로드 정보 조회",
            command=self.show_revisions,
        ).pack(side="left", padx=6)

        self.status = tk.StringVar(
            value="서버: https://192.168.246.54:8443"
        )

        ttk.Label(
            root,
            textvariable=self.status,
            anchor="w",
        ).pack(fill="x")

        # 장시간 업로드가 멈춘 것처럼 보이지 않도록 별도 진행 표시를 유지한다.
        self.upload_progress = ttk.Progressbar(
            root,
            mode="indeterminate",
            maximum=100,
        )
        self.upload_progress.pack(fill="x", pady=(8, 3))
        self.upload_progress.pack_forget()

        self.upload_detail = tk.StringVar(value="")
        self.upload_detail_label = ttk.Label(
            root,
            textvariable=self.upload_detail,
            anchor="w",
        )
        self.upload_detail_label.pack(fill="x")
        self.upload_detail_label.pack_forget()

        if self.current_user:
            self.after(0, self._apply_existing_session)
        else:
            self.after(0, self.destroy)

    def _apply_existing_session(self):
        try:
            level = int((self.current_user or {}).get("level", 5))
        except Exception:
            level = 5
        user = self.current_user or {}
        label = (
            f"{user.get('name') or user.get('username')} "
            f"· {user.get('department', '')} · {level}등급"
        )
        self.login_status.set(label)
        if level == 1:
            self.upload_one_btn.configure(state="normal")
            self.upload_all_btn.configure(state="normal")
            self.status.set("관리자 세션 연결 완료")
            self._load_server_regions()
        else:
            self.upload_one_btn.configure(state="disabled")
            self.upload_all_btn.configure(state="disabled")
            self.status.set("1등급 관리자만 업로드할 수 있습니다.")

    def _load_server_regions(self):
        self.upload_one_btn.configure(state="disabled")
        self.upload_all_btn.configure(state="disabled")
        self.region_display_to_id = {}
        try:
            rows = self.client.admin_regions() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("regions") or []

            self.region_rows = []
            self.region_display_to_id = {}
            values = []

            for row in rows:
                if not isinstance(row, dict):
                    continue
                rid = str(
                    row.get("id")
                    or row.get("region_id")
                    or row.get("region_code")
                    or ""
                ).strip()
                if not rid.startswith("CMB_GN_"):
                    continue
                name = str(
                    row.get("name")
                    or row.get("region_name")
                    or rid
                ).strip()
                display = f"{name} ({rid})" if name and name != rid else rid
                self.region_rows.append(row)
                self.region_display_to_id[display] = rid
                values.append(display)

            self.region_combo["values"] = values

            # 업로드 지역은 사용자가 선택하지 않는다.
            # 현재 DXF 파일명(stem)과 canonical 지역코드가 정확히 일치할 때만 자동 연결한다.
            # 예: CMB_GN_HP.dxf -> CMB_GN_HP
            source_region = Path(self.source_path).stem.strip()
            auto_display = next(
                (
                    display
                    for display, rid in self.region_display_to_id.items()
                    if rid == source_region
                ),
                "",
            )

            if auto_display:
                self.region_var.set(auto_display)
                self.upload_one_btn.configure(state="normal")
                self.upload_all_btn.configure(state="normal")
                self.status.set(
                    f"서버 canonical 지역 {len(values)}개 · 자동 연결: {source_region}"
                )
            else:
                self.region_var.set("")
                self.upload_one_btn.configure(state="disabled")
                self.upload_all_btn.configure(state="disabled")
                self.status.set(
                    f"서버에 현재 도면 지역이 없습니다: {source_region}"
                )
                messagebox.showerror(
                    "서버 지역 없음",
                    (
                        f"현재 도면 파일명과 일치하는 서버 지역이 없습니다.\n\n"
                        f"도면: {Path(self.source_path).name}\n"
                        f"필요 지역코드: {source_region}\n\n"
                        "지역을 임의로 선택해서 업로드할 수 없습니다."
                    ),
                    parent=self,
                )
        except Exception as exc:
            self.region_combo["values"] = []
            self.region_var.set("")
            self.status.set("서버 지역 조회 실패: " + str(exc))

    def _selected_region_code(self):
        display = self.region_var.get().strip()
        rid = self.region_display_to_id.get(display, "")
        if not rid or rid != Path(self.source_path).stem.strip():
            source_region = Path(self.source_path).stem.strip()
            raise RuntimeError(
                f"현재 도면과 일치하는 서버 지역이 없습니다: {source_region}"
            )
        return rid

    def health(self):
        try:
            self.status.set(
                "서버 응답: "
                + json.dumps(
                    self.client.health(),
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            messagebox.showerror(
                "서버",
                str(exc),
                parent=self,
            )

    def _require_admin(self):
        if not self.current_user:
            raise RuntimeError("먼저 서버에 로그인해주세요.")

        if int(self.current_user.get("level", 5)) != 1:
            raise RuntimeError(
                "도면 업로드는 1등급 관리자만 가능합니다."
            )

    def _close_requested(self):
        if self.session_busy:
            messagebox.showinfo(
                "업로드 진행 중",
                "업로드 또는 서버 처리 중에는 창을 닫을 수 없습니다.\n완료 후 닫아주세요.",
                parent=self,
            )
            return
        self.destroy()

    @staticmethod
    def _format_elapsed(seconds):
        seconds = max(0, int(seconds))
        hours, remain = divmod(seconds, 3600)
        minutes, secs = divmod(remain, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _show_upload_progress(self, phase, group, object_count=0, package_mb=None):
        try:
            if not self.upload_progress.winfo_manager():
                self.upload_progress.pack(fill="x", pady=(8, 3))
            if not self.upload_detail_label.winfo_manager():
                self.upload_detail_label.pack(fill="x")
            self.upload_progress.start(12)
        except Exception:
            pass
        size_text = f" · 패키지 {package_mb:.1f} MB" if package_mb is not None else ""
        self.upload_detail.set(
            f"{Path(self.source_path).name} · {group} · 대상 {int(object_count):,}개"
            f"{size_text} · {phase}"
        )
        self.update_idletasks()

    def _hide_upload_progress(self):
        try:
            self.upload_progress.stop()
            self.upload_progress.pack_forget()
            self.upload_detail_label.pack_forget()
        except Exception:
            pass

    def _run_background_task(self, func, phase, group, object_count=0, package_mb=None):
        """Run long work off the Tk thread while keeping visible progress alive."""
        state = {"done": False, "result": None, "error": None}
        started = time.monotonic()

        def worker():
            try:
                state["result"] = func()
            except Exception as exc:
                state["error"] = exc
            finally:
                state["done"] = True

        self._show_upload_progress(
            phase,
            group,
            object_count=object_count,
            package_mb=package_mb,
        )
        threading.Thread(target=worker, daemon=True).start()

        while not state["done"]:
            elapsed = self._format_elapsed(time.monotonic() - started)
            size_text = f" · 패키지 {package_mb:.1f} MB" if package_mb is not None else ""
            self.upload_detail.set(
                f"{Path(self.source_path).name} · {group} · 대상 {int(object_count):,}개"
                f"{size_text} · {phase} · 경과 {elapsed} · 세션 유지중"
            )
            try:
                self.update()
            except tk.TclError:
                break
            time.sleep(0.10)

        elapsed = self._format_elapsed(time.monotonic() - started)
        self.upload_detail.set(
            f"{Path(self.source_path).name} · {group} · {phase} 완료 · 경과 {elapsed}"
        )
        self.update_idletasks()

        if state["error"] is not None:
            raise state["error"]
        return state["result"]

    def _begin_busy(self):
        self.session_busy = True
        self._busy_generation += 1
        generation = self._busy_generation
        try:
            self.upload_one_btn.configure(state="disabled")
            self.upload_all_btn.configure(state="disabled")
        except Exception:
            pass

        # 업로드는 Tk 메인 스레드를 오래 점유할 수 있으므로
        # 로컬 idle guard가 사용자 입력 없음으로 로그아웃시키지 않게 일시정지한다.
        try:
            guard = getattr(self.master, "session_guard", None)
            if guard is not None:
                guard.pause()
        except Exception:
            pass

        def heartbeat():
            # 업로드 중에는 사용자 입력과 무관하게 서버 세션을 계속 활성 상태로 유지한다.
            while self.session_busy and generation == self._busy_generation:
                try:
                    self.client.touch_session()
                except Exception:
                    pass
                for _ in range(15):
                    if not self.session_busy or generation != self._busy_generation:
                        return
                    time.sleep(1)

        threading.Thread(target=heartbeat, daemon=True).start()

    def _end_busy(self):
        self.session_busy = False
        self._busy_generation += 1
        try:
            guard = getattr(self.master, "session_guard", None)
            if guard is not None:
                guard.resume()
        except Exception:
            pass
        try:
            # canonical 지역이 정상 연결된 경우에만 다시 활성화한다.
            self._selected_region_code()
            self.upload_one_btn.configure(state="normal")
            self.upload_all_btn.configure(state="normal")
        except Exception:
            pass
        self._hide_upload_progress()

    def _upload(self, group, allow_empty=False):
        self._require_admin()
        region_code = self._selected_region_code()
        self._begin_busy()

        try:
            preview_count = int((self.group_counts or {}).get(group, 0))
            self.status.set(f"{group} · 업로드 패키지 생성 중")
            payload = self._run_background_task(
                lambda: build_payload(
                    self.scene,
                    self.source_path,
                    group,
                    self.epsg,
                    region_code,
                    self.memo_var.get(),
                ),
                "패키지 생성 중",
                group,
                object_count=preview_count,
            )

            if payload["object_count"] <= 0 and not allow_empty:
                raise RuntimeError(
                    f"{group} 그룹에 업로드 가능한 객체가 없습니다."
                )

            package_bytes = len(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            package_mb = package_bytes / (1024.0 * 1024.0)
            object_count = int(payload.get("object_count") or 0)

            self.status.set(
                f"{group} · {object_count:,}개 · {package_mb:.1f} MB · 서버 전송/DB 저장 중"
            )
            result = self._run_background_task(
                lambda: self.client.upload_group(payload),
                "서버 전송/DB 저장 중",
                group,
                object_count=object_count,
                package_mb=package_mb,
            )

            self.status.set(
                f"{group} 업로드 완료 · "
                f"revision {result.get('revision')} · "
                f"{result.get('object_count')}개 · {package_mb:.1f} MB"
            )
            return result
        finally:
            self._end_busy()

    def _upload_symbol(self, allow_empty=False):
        self._require_admin()
        region_code = self._selected_region_code()
        self._begin_busy()
        try:
            preview_count = int((self.group_counts or {}).get("SYMBOL", 0))
            payload = self._run_background_task(
                lambda: build_symbol_payload(
                    self.scene,
                    self.source_path,
                    region_code,
                    self.memo_var.get(),
                ),
                "심볼 패키지 생성 중",
                "SYMBOL",
                object_count=preview_count,
            )
            if payload["symbol_count"] <= 0 and not allow_empty:
                raise RuntimeError("업로드 가능한 심볼 정의가 없습니다.")

            package_bytes = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            package_mb = package_bytes / (1024.0 * 1024.0)
            symbol_count = int(payload.get("symbol_count") or 0)

            self.status.set(
                f"SYMBOL · {symbol_count:,}개 · {package_mb:.1f} MB · 서버 전송/DB 저장 중"
            )
            result = self._run_background_task(
                lambda: self.client.upload_symbols(region_code, payload),
                "서버 전송/DB 저장 중",
                "SYMBOL",
                object_count=symbol_count,
                package_mb=package_mb,
            )
            self.status.set(
                "SYMBOL 업로드 완료 · "
                f"revision {result.get('revision')} · "
                f"{result.get('symbol_count', symbol_count)}개 · {package_mb:.1f} MB"
            )
            return result
        finally:
            self._end_busy()

    def upload_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        item = selected[0]
        try:
            if item == "SYMBOL":
                self._upload_symbol()
            else:
                self._upload(item)
        except Exception as exc:
            messagebox.showerror(
                "업로드 오류",
                str(exc),
                parent=self,
            )

    def upload_all(self):
        try:
            self._require_admin()

            uploaded = []
            failed = []

            # 전체 업로드는 FIBER/COAX/CONDUIT/USER만 순차 교체한다.
            # POLE과 SYMBOL은 선택 업로드에서만 처리한다.
            # 한 항목 실패가 다른 항목의 성공본을 되돌리지 않는다.
            for item in FULL_UPLOAD_ITEMS:
                try:
                    if item == "SYMBOL":
                        self._upload_symbol(allow_empty=True)
                    else:
                        self._upload(item, allow_empty=True)
                    uploaded.append(item)
                except Exception as exc:
                    failed.append(f"{item}: {exc}")

            if not uploaded:
                raise RuntimeError(
                    "모든 업로드 항목이 실패했습니다.\n" + "\n".join(failed)
                )

            text = "성공: " + ", ".join(uploaded)
            if failed:
                text += "\n\n실패:\n" + "\n".join(failed)

            messagebox.showinfo(
                "전체 업로드 결과",
                text,
                parent=self,
            )
            self.status.set(
                "전체 업로드 완료 · 성공 " + ", ".join(uploaded)
                + (f" · 실패 {len(failed)}개" if failed else "")
            )

        except Exception as exc:
            messagebox.showerror(
                "업로드 오류",
                str(exc),
                parent=self,
            )

    def show_revisions(self):
        if not self.current_user:
            messagebox.showinfo(
                "백업 조회",
                "먼저 서버에 로그인해주세요.",
                parent=self,
            )
            return

        if int(self.current_user.get("level", 5)) != 1:
            messagebox.showinfo(
                "백업 조회",
                "백업 조회/복원은 현재 1등급 관리자만 가능합니다.",
                parent=self,
            )
            return

        try:
            region = self._selected_region_code()
        except Exception as exc:
            messagebox.showerror("백업 조회", str(exc), parent=self)
            return

        win = tk.Toplevel(self)
        win.title(f"서버 도면 백업 · {region}")
        win.geometry("920x480")
        win.minsize(760, 400)
        win.transient(self)

        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text=f"{region} · 그룹별 현재본 + 최근 백업 2개",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=(
                "백업을 선택해 복원하면 해당 그룹의 선택 백업이 현재본이 되고, "
                "기존 현재본은 백업으로 유지됩니다."
            ),
        ).pack(anchor="w", pady=(3, 10))

        tree = ttk.Treeview(
            root,
            columns=("group", "state", "date", "count", "memo"),
            show="headings",
            height=13,
        )
        for key, title, width in (
            ("group", "종류", 90),
            ("state", "상태", 70),
            ("date", "저장일시", 155),
            ("count", "객체수", 90),
            ("memo", "메모", 420),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        row_map = {}

        def load_rows():
            for item in tree.get_children():
                tree.delete(item)
            row_map.clear()

            rows = self.client.revisions(region) or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("revisions") or []

            order = {g: i for i, g in enumerate(MANAGED_ITEMS)}
            rows = sorted(
                list(rows),
                key=lambda r: (
                    order.get(str(r.get("group_id") or "").upper(), 999),
                    0 if r.get("active") else 1,
                    -int(r.get("revision") or 0),
                ),
            )

            for idx, item in enumerate(rows):
                group = str(item.get("group_id") or "")
                state = "현재" if item.get("active") else "백업"
                created = str(item.get("created_at") or "").replace("T", " ")[:19]
                memo = str(item.get("memo") or "").strip() or "메모 없음"
                count = int(item.get("object_count") or 0)
                iid = f"rev_{idx}_{item.get('id') or item.get('revision')}"
                tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(group, state, created or "날짜 없음", f"{count:,}", memo),
                )
                row_map[iid] = item

        def restore_selected():
            selected = tree.selection()
            if not selected:
                messagebox.showinfo(
                    "백업 복원",
                    "복원할 백업을 선택해주세요.",
                    parent=win,
                )
                return

            item = row_map.get(selected[0]) or {}
            if item.get("active"):
                messagebox.showinfo(
                    "백업 복원",
                    "현재 사용 중인 도면입니다. 백업 항목을 선택해주세요.",
                    parent=win,
                )
                return

            revision_id = item.get("id")
            if revision_id in (None, ""):
                messagebox.showerror(
                    "백업 복원",
                    "서버 응답에 Revision ID가 없어 복원할 수 없습니다.",
                    parent=win,
                )
                return

            group = str(item.get("group_id") or "")
            created = str(item.get("created_at") or "").replace("T", " ")[:19]
            memo = str(item.get("memo") or "").strip() or "메모 없음"

            if not messagebox.askyesno(
                "백업 복원 확인",
                (
                    f"지역: {region}\n"
                    f"종류: {group}\n"
                    f"백업일시: {created or '날짜 없음'}\n"
                    f"메모: {memo}\n\n"
                    "이 백업을 현재 도면으로 복원하시겠습니까?\n"
                    "기존 현재본은 백업으로 유지됩니다."
                ),
                parent=win,
            ):
                return

            try:
                result = self.client.restore_revision(
                    region,
                    revision_id,
                    item.get("group_id"),
                )
                load_rows()
                self.status.set(
                    f"{group} 백업 복원 완료 · "
                    f"revision {result.get('revision') or item.get('revision')}"
                )
                messagebox.showinfo(
                    "백업 복원",
                    "선택한 백업을 현재 도면으로 복원했습니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "백업 복원 오류",
                    str(exc),
                    parent=win,
                )

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(10, 0))

        ttk.Button(
            controls,
            text="새로고침",
            command=load_rows,
        ).pack(side="left")

        ttk.Button(
            controls,
            text="선택 백업 복원",
            command=restore_selected,
        ).pack(side="right")

        try:
            load_rows()
        except Exception as exc:
            win.destroy()
            messagebox.showerror(
                "백업 조회 오류",
                str(exc),
                parent=self,
            )

