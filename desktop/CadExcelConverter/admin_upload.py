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


def build_payload(scene, source_path, group, epsg):
    transformer = Transformer.from_crs(
        f"EPSG:{int(epsg)}",
        "EPSG:4326",
        always_xy=True,
    )

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
            "regional_object_id": (
                f"{drawing_code(source_path)}_{e.handle}"
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
        "region_code": drawing_code(source_path),
        "group": group,
        "source_epsg": int(epsg),
        "source_file": p.name,
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "object_count": len(objects),
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
    def __init__(self, master, scene, source_path, source_epsg):
        super().__init__(master)

        self.scene = scene
        self.source_path = source_path
        self.epsg = source_epsg
        self.client = CMBServerClient()
        self.current_user = None

        self.title("관리자 · 서버 도면 업로드")
        self.geometry("820x620")
        self.minsize(720, 520)

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
                f"지역 {drawing_code(source_path)} · "
                f"{Path(source_path).name} · EPSG:{source_epsg}"
            ),
        ).pack(anchor="w", pady=(3, 10))

        login = ttk.LabelFrame(root, text="서버 로그인", padding=8)
        login.pack(fill="x", pady=(0, 10))

        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.login_status = tk.StringVar(value="로그인이 필요합니다.")

        ttk.Label(login, text="아이디").grid(row=0, column=0, sticky="w")
        ttk.Entry(login, textvariable=self.username, width=22).grid(
            row=0, column=1, padx=(6, 12)
        )

        ttk.Label(login, text="비밀번호").grid(row=0, column=2, sticky="w")
        pw = ttk.Entry(login, textvariable=self.password, show="*", width=22)
        pw.grid(row=0, column=3, padx=(6, 12))
        pw.bind("<Return>", lambda e: self.login())

        ttk.Button(login, text="로그인", command=self.login).grid(
            row=0, column=4
        )

        ttk.Button(login, text="로그아웃", command=self.logout).grid(
            row=0, column=5, padx=(6, 0)
        )

        ttk.Label(
            login,
            textvariable=self.login_status,
        ).grid(
            row=1,
            column=0,
            columnspan=6,
            sticky="w",
            pady=(6, 0),
        )

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

        row = ttk.Frame(root)
        row.pack(fill="x", pady=12)

        self.upload_one_btn = ttk.Button(
            row,
            text="선택 그룹 서버 업로드",
            command=self.upload_selected,
            state="disabled",
        )
        self.upload_one_btn.pack(side="left")

        self.upload_all_btn = ttk.Button(
            row,
            text="전체 5그룹 순차 업로드",
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
            text="Revision 조회",
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

    def login(self):
        username = self.username.get().strip()
        password = self.password.get()

        if not username or not password:
            messagebox.showinfo(
                "로그인",
                "아이디와 비밀번호를 입력해주세요.",
                parent=self,
            )
            return

        try:
            user = self.client.login(username, password)
            self.current_user = user
            self.password.set("")

            level = int(user.get("level", 5))
            label = (
                f"{user.get('name') or user.get('username')} "
                f"· {user.get('department', '')} · {level}등급"
            )

            if level != 1:
                self.login_status.set(
                    label + " · 조회 전용: 도면 업로드는 1등급 관리자만 가능합니다."
                )
                self.upload_one_btn.configure(state="disabled")
                self.upload_all_btn.configure(state="disabled")
            else:
                self.login_status.set(label + " · 관리자 업로드 가능")
                self.upload_one_btn.configure(state="normal")
                self.upload_all_btn.configure(state="normal")

            self.status.set("서버 로그인 완료")

        except Exception as exc:
            self.current_user = None
            self.upload_one_btn.configure(state="disabled")
            self.upload_all_btn.configure(state="disabled")
            self.login_status.set("로그인 실패")
            messagebox.showerror("로그인 오류", str(exc), parent=self)

    def logout(self):
        try:
            self.client.logout()
        except Exception:
            pass

        self.current_user = None
        self.upload_one_btn.configure(state="disabled")
        self.upload_all_btn.configure(state="disabled")
        self.login_status.set("로그인이 필요합니다.")
        self.status.set("로그아웃 완료")

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

        payload = build_payload(
            self.scene,
            self.source_path,
            group,
            self.epsg,
        )

        if payload["object_count"] <= 0:
            raise RuntimeError(
                f"{group} 그룹에 업로드 가능한 객체가 없습니다. 빈 Revision 생성은 차단됩니다."
            )

        self.status.set(
            f"{group} · {payload['object_count']:,}개 업로드 중..."
        )
        self.update_idletasks()

        result = self.client.upload_group(payload)

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
                "Revision",
                "먼저 서버에 로그인해주세요.",
                parent=self,
            )
            return

        if int(self.current_user.get("level", 5)) != 1:
            messagebox.showinfo(
                "Revision",
                "Revision 조회는 현재 관리자 API이므로 1등급 로그인이 필요합니다.",
                parent=self,
            )
            return

        try:
            rows = self.client.revisions(
                drawing_code(self.source_path)
            ) or []

            lines = []

            for row in rows:
                active = "ACTIVE" if row.get("active") else ""
                lines.append(
                    f"{row.get('group_id')} "
                    f"r{row.get('revision')} "
                    f"{row.get('object_count')}개 "
                    f"{active}"
                )

            messagebox.showinfo(
                "서버 Revision",
                "\n".join(lines) if lines else "등록된 Revision이 없습니다.",
                parent=self,
            )

        except Exception as exc:
            messagebox.showerror(
                "Revision 조회 오류",
                str(exc),
                parent=self,
            )
