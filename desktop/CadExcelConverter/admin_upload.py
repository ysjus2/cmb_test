from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from pyproj import Transformer

from drawing_identity import drawing_code
from server_client_windows import CMBServerClient

GROUPS = ("FIBER", "COAX", "POLE", "CONDUIT", "USER")


def classify_entity(e):
    u = (str(e.layer or "") + " " + str(e.block_name or "")).upper()

    if any(k in u for k in ("F_CABLE", "FIBER", "FOC", "OPTIC", "CLOSURE", "ONU", "광")):
        return "FIBER"

    if any(k in u for k in (
        "C_CABLE", "COAX", "RG06", "RG11", "PFC", "AMP", "TAP",
        "PASSIVE", "POWER", "CONNECTOR", "동축", "증폭", "분기",
    )):
        return "COAX"

    if any(k in u for k in ("POLE", "전주", "POLE_CATV", "POLE-CATV")):
        return "POLE"

    if any(k in u for k in ("CONDUIT", "MANHOLE", "HANDHOLE", "관로", "맨홀", "핸드홀")):
        return "CONDUIT"

    if "USER" in u or "CN_M_USER" in u:
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
    if "POWER" in text:
        return "power"
    if any(k in text for k in ("CLOSURE", "TERMINAL", "CENTER")):
        return "closure"
    return "generic"


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
    for kind, data in e.primitives:
        if kind in {"line", "polyline", "polygon"} and len(data) >= 2:
            return [(float(x), float(y)) for x, y in data]
        if kind in {"insert", "point"}:
            return [(float(data[0]), float(data[1]))]

    if e.bbox:
        x1, y1, x2, y2 = e.bbox
        return [((x1 + x2) / 2, (y1 + y2) / 2)]

    return []


def build_payload(scene, source_path, group, epsg, memo=""):
    transformer = Transformer.from_crs(
        f"EPSG:{int(epsg)}",
        "EPSG:4326",
        always_xy=True,
    )

    region_code = drawing_code(source_path).strip()

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
        symbol_kind = _symbol_kind(e)
        attrs["_cmb_symbol_kind"] = symbol_kind
        attrs["_cmb_rotation_deg"] = _rotation_deg(e)
        attrs["_cmb_is_device"] = bool(
            str(e.entity_type or "").upper() in {"INSERT", "POINT"}
            or symbol_kind != "generic"
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

        self.title("관리자 · 서버 도면 업로드")
        self.geometry("820x690")
        self.minsize(720, 590)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="관리자 서버 도면 업로드",
            font=("Malgun Gothic", 16, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=(
                f"지역코드 {drawing_code(source_path)} · "
                f"{Path(source_path).name} · EPSG:{source_epsg}"
            ),
        ).pack(anchor="w", pady=(3, 10))

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
            "COAX": "동축케이블 + AMP/TAP/PASSIVE/POWER/CONNECTOR 등 동축기기",
            "POLE": "전주 + CATV/자가주",
            "CONDUIT": "관로 + 맨홀 + 핸드홀",
            "USER": "사용자 작성 건물/지형/관리구역",
        }

        counts = {g: 0 for g in GROUPS}

        for e in scene.entities:
            g = classify_entity(e)
            if g:
                counts[g] += 1

        self.group_counts = counts

        for g in GROUPS:
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
            text="선택 그룹 또는 전체 업로드 시 같은 메모가 해당 변경 그룹에 저장됩니다.",
        ).pack(anchor="w", pady=(4, 0))

        row = ttk.Frame(root)
        row.pack(fill="x", pady=12)

        self.upload_one_btn = ttk.Button(
            row,
            text="선택 그룹/정보 업로드",
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
        else:
            self.upload_one_btn.configure(state="disabled")
            self.upload_all_btn.configure(state="disabled")
            self.status.set("1등급 관리자만 업로드할 수 있습니다.")

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

    def _upload(self, group):
        self._require_admin()

        region_code = drawing_code(self.source_path).strip()
        rows = self.client.admin_regions() or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("regions") or []

        registered = {
            str(
                row.get("id")
                or row.get("region_id")
                or row.get("region_code")
                or ""
            ).strip().casefold()
            for row in rows
        }

        if region_code.casefold() not in registered:
            raise RuntimeError(
                f"등록되지 않은 도면명/지역코드입니다: {region_code}\n"
                "관리자 > 지역 등록에서 이 DXF 도면명을 먼저 지역코드로 등록해주세요."
            )

        self.session_busy = True

        payload = build_payload(
            self.scene,
            self.source_path,
            group,
            self.epsg,
            self.memo_var.get(),
        )

        if payload["object_count"] <= 0:
            raise RuntimeError(
                f"{group} 그룹에 업로드 가능한 객체가 없습니다. 빈 Revision 생성은 차단됩니다."
            )

        self.status.set(
            f"{group} · {payload['object_count']:,}개 업로드 중..."
        )
        self.update_idletasks()

        try:
            result = self.client.upload_group(payload)
        finally:
            self.session_busy = False

        self.status.set(
            f"{group} 업로드 완료 · "
            f"revision {result.get('revision')} · "
            f"{result.get('object_count')}개"
        )

        return result

    def upload_selected(self):
        selected = self.tree.selection()

        if not selected:
            return

        try:
            self._upload(selected[0])
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
            skipped = []

            for group in GROUPS:
                if int(self.group_counts.get(group, 0)) <= 0:
                    skipped.append(group)
                    continue
                self._upload(group)
                uploaded.append(group)

            if not uploaded:
                raise RuntimeError(
                    "업로드 가능한 객체가 있는 그룹이 없습니다. 빈 Revision 생성은 차단됩니다."
                )

            skipped_text = (
                "\n\n객체 없음으로 건너뜀: " + ", ".join(skipped)
                if skipped else ""
            )

            messagebox.showinfo(
                "업로드",
                f"{len(uploaded)}개 그룹 업로드가 완료되었습니다."
                + skipped_text,
                parent=self,
            )

            self.status.set(
                "업로드 완료 · "
                + ", ".join(uploaded)
                + (
                    " · 객체 없음 건너뜀: " + ", ".join(skipped)
                    if skipped else ""
                )
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

        region = drawing_code(self.source_path)

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

            order = {g: i for i, g in enumerate(GROUPS)}
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
                result = self.client.restore_revision(region, int(revision_id))
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

