from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from server_client_windows import CMBServerClient


class UserAdminWindow(tk.Toplevel):
    def __init__(self, master, client=None, current_user=None):
        super().__init__(master)
        self.client = client or CMBServerClient()
        self.current_user = current_user
        self.users = []

        self.title("사용자 · 도면 관리")
        self.geometry("1240x620")
        self.minsize(1080, 520)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="사용자 · 도면 관리", font=("Malgun Gothic", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="1등급 관리자 전용").pack(anchor="w", pady=(2, 10))

        self.login_status = tk.StringVar(value="")
        session_line = ttk.Label(root, textvariable=self.login_status)
        session_line.pack(anchor="w", pady=(0, 2))

        self.backup_retention_text = tk.StringVar(value="도면 백업 보관: 조회 전")
        ttk.Label(
            root,
            textvariable=self.backup_retention_text,
        ).pack(anchor="w", pady=(0, 8))

        # 사용자/권한/도면을 3개 업무 그룹으로 정리한다.
        groups = ttk.Frame(root)
        groups.pack(fill="x", pady=(10, 8))
        groups.columnconfigure(0, weight=1)
        groups.columnconfigure(1, weight=1)
        groups.columnconfigure(2, weight=1)

        user_group = ttk.LabelFrame(groups, text="사용자 관리", padding=8)
        user_group.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        registration_group = ttk.LabelFrame(groups, text="등록 / 권한 관리", padding=8)
        registration_group.grid(row=0, column=1, sticky="nsew", padx=3)
        drawing_group = ttk.LabelFrame(groups, text="도면 관리", padding=8)
        drawing_group.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        # 1열: 사용자 관리
        search_row = ttk.Frame(user_group)
        search_row.pack(fill="x", pady=(0, 6))
        self.search_var = tk.StringVar()
        ttk.Label(search_row, text="검색").pack(side="left")
        search = ttk.Entry(search_row, textvariable=self.search_var, width=18)
        search.pack(side="left", padx=(6, 0), fill="x", expand=True)
        search.bind("<KeyRelease>", lambda e: self.apply_filter())

        self.lookup_btn = ttk.Button(
            user_group, text="사용자 조회", command=self.load_users, state="disabled"
        )
        self.lookup_btn.pack(fill="x", pady=2)

        self.reset_btn = ttk.Button(
            user_group, text="비밀번호 초기화", command=self.reset_password, state="disabled"
        )
        self.reset_btn.pack(fill="x", pady=2)

        self.device_reset_btn = ttk.Button(
            user_group, text="단말 초기화", command=self.reset_device, state="disabled"
        )
        self.device_reset_btn.pack(fill="x", pady=2)

        self.level_btn = ttk.Button(
            user_group, text="등급 설정", command=self.set_level, state="disabled"
        )
        self.level_btn.pack(fill="x", pady=2)

        self.activate_btn = ttk.Button(
            user_group, text="계정 활성화", command=self.activate_user, state="disabled"
        )
        self.activate_btn.pack(fill="x", pady=2)

        self.deactivate_btn = ttk.Button(
            user_group, text="계정 비활성화", command=self.deactivate_user, state="disabled"
        )
        self.deactivate_btn.pack(fill="x", pady=2)

        # 2열: 등록 / 권한 관리
        self.new_btn = ttk.Button(
            registration_group, text="신규 사용자 등록", command=self.create_user, state="disabled"
        )
        self.new_btn.pack(fill="x", pady=2)

        self.region_register_btn = ttk.Button(
            registration_group, text="지역 등록", command=self.register_region, state="disabled"
        )
        self.region_register_btn.pack(fill="x", pady=2)

        self.region_btn = ttk.Button(
            registration_group, text="지역 권한 등록", command=self.edit_regions, state="disabled"
        )
        self.region_btn.pack(fill="x", pady=2)

        ttk.Label(
            registration_group,
            text="신규 사용자는 기본 5등급으로 등록됩니다.",
            wraplength=300,
            justify="left",
        ).pack(fill="x", pady=(8, 0))

        # 도면 관리
        self.drawing_status_btn = ttk.Button(
            drawing_group, text="도면 버전 확인", command=self.view_drawing_status, state="disabled"
        )
        self.drawing_status_btn.pack(fill="x", pady=2)

        self.drawing_delete_btn = ttk.Button(
            drawing_group, text="도면 강제 삭제", command=self.open_force_delete_drawing, state="disabled"
        )
        self.drawing_delete_btn.pack(fill="x", pady=2)

        self.backup_btn = ttk.Button(
            drawing_group, text="백업 보관 설정", command=self.edit_backup_retention, state="disabled"
        )
        self.backup_btn.pack(fill="x", pady=2)

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame,
            columns=("username", "name", "department", "level", "regions", "active"),
            show="headings",
            selectmode="browse",
        )
        for key, title, width in (
            ("username", "아이디", 150),
            ("name", "이름", 130),
            ("department", "부서", 170),
            ("level", "등급", 70),
            ("regions", "배정 지역", 380),
            ("active", "상태", 80),
        ):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width)

        y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        self.status = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.status).pack(fill="x", pady=(8, 0))

        if self.current_user:
            self.after(0, self._apply_existing_session)
        else:
            self.after(0, self.destroy)

    def _apply_existing_session(self):
        try:
            level = int((self.current_user or {}).get("level", 5))
        except Exception:
            level = 5

        if level != 1:
            self.current_user = None
            return

        user = self.current_user or {}
        self.login_status.set(
            f"{user.get('name') or user.get('username')} · 1등급 관리자"
        )
        self.lookup_btn.configure(state="normal")
        self.new_btn.configure(state="normal")
        self.reset_btn.configure(state="normal")
        self.device_reset_btn.configure(state="normal")
        self.level_btn.configure(state="normal")
        self.deactivate_btn.configure(state="normal")
        self.activate_btn.configure(state="normal")
        self.region_btn.configure(state="normal")
        self.region_register_btn.configure(state="normal")
        self.drawing_status_btn.configure(state="normal")
        self.drawing_delete_btn.configure(state="normal")
        self.backup_btn.configure(state="normal")
        self._refresh_backup_retention_display()
        self.status.set("사용자 조회 버튼을 눌러 목록을 불러오세요.")

    def _refresh_backup_retention_display(self):
        try:
            result = self.client.admin_backup_retention() or {}
            count = int(result.get("count", 2))
            if count <= 0:
                self.backup_retention_text.set("도면 백업 보관: 사용 안 함 (0개)")
            else:
                self.backup_retention_text.set(f"도면 백업 보관: 최근 {count}개")
        except Exception:
            self.backup_retention_text.set("도면 백업 보관: 조회 실패")

    def load_users(self):
        if not self.current_user:
            return
        try:
            rows = self.client.admin_users() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("users") or []
            self.users = list(rows)

            region_rows = self.client.admin_regions() or []
            if isinstance(region_rows, dict):
                region_rows = region_rows.get("items") or region_rows.get("regions") or []
            region_name_by_id = {
                str(r.get("id") or r.get("region_id") or ""):
                str(r.get("name") or r.get("id") or r.get("region_id") or "")
                for r in region_rows
            }

            for user in self.users:
                uid = user.get("id")
                names = []
                if uid is not None:
                    try:
                        assigned = self.client.user_regions(uid) or []
                        if isinstance(assigned, dict):
                            assigned = assigned.get("items") or assigned.get("regions") or []
                        for item in assigned:
                            rid = str(item.get("id") or item.get("region_id") or "").strip()
                            if rid:
                                names.append(region_name_by_id.get(rid, rid))
                    except Exception:
                        names = ["조회 실패"]
                user["_region_names"] = ", ".join(names) if names else "-"

            self.apply_filter()
            self._refresh_backup_retention_display()
            self.status.set(f"사용자 {len(self.users)}명 조회 완료")
        except Exception as exc:
            messagebox.showerror("사용자 조회 오류", str(exc), parent=self)

    def apply_filter(self):
        q = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for i, user in enumerate(self.users):
            blob = " ".join(
                str(user.get(k) or "")
                for k in ("username", "name")
            ).lower()
            if q and q not in blob:
                continue
            active = user.get("active")
            if active is None:
                active = user.get("is_active")
            active_text = "사용" if active is not False else "중지"
            self.tree.insert(
                "", "end", iid=str(i),
                values=(
                    user.get("username", ""),
                    user.get("name", ""),
                    user.get("department") or "",
                    user.get("level", ""),
                    user.get("_region_names") or "-",
                    active_text,
                ),
            )
            shown += 1
        if q:
            self.status.set(
                f"아이디/이름 검색 결과 {shown}명 / 전체 {len(self.users)}명"
            )
        else:
            self.status.set(
                f"전체 사용자 {shown}명 표시"
                if self.users
                else "사용자 조회 버튼을 눌러 목록을 불러오세요."
            )

    def _selected_user(self):
        selected = self.tree.selection()
        if not selected:
            return None
        try:
            return self.users[int(selected[0])]
        except Exception:
            return None

    def create_user(self):
        if not self.current_user:
            return

        win = tk.Toplevel(self)
        win.title("신규 사용자 등록")
        win.geometry("620x620")
        win.minsize(560, 520)
        win.transient(self)
        win.grab_set()

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="신규 사용자 등록",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text="지역은 관리자에 의해 이미 등록된 지역만 선택할 수 있습니다.",
        ).pack(anchor="w", pady=(2, 10))

        form = ttk.Frame(frame)
        form.pack(fill="x")

        username = tk.StringVar()
        name = tk.StringVar()
        department = tk.StringVar()
        level = tk.StringVar(value="5")

        rows = [
            ("아이디", username),
            ("이름", name),
            ("부서", department),
            ("등급", level),
        ]
        for i, (label, var) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Entry(form, textvariable=var, width=34).grid(
                row=i,
                column=1,
                sticky="ew",
                padx=(8, 0),
                pady=5,
            )
        form.columnconfigure(1, weight=1)

        duplicate_status = tk.StringVar(value="아이디 중복검사 대기")
        ttk.Label(
            form,
            textvariable=duplicate_status,
        ).grid(
            row=len(rows),
            column=1,
            sticky="w",
            padx=(8, 0),
            pady=(0, 4),
        )
        username_check_job = {"id": None}

        region_box = ttk.LabelFrame(
            frame,
            text="사용 가능 지역 선택",
            padding=10,
        )
        region_box.pack(fill="both", expand=True, pady=(12, 0))

        canvas = tk.Canvas(region_box, highlightthickness=0)
        scroll = ttk.Scrollbar(
            region_box,
            orient="vertical",
            command=canvas.yview,
        )
        body = ttk.Frame(canvas)
        body_window = canvas.create_window(
            (0, 0),
            window=body,
            anchor="nw",
        )
        body.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(body_window, width=e.width),
        )
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        vars_by_region = {}

        def load_regions():
            try:
                rows = self.client.admin_regions() or []
                if isinstance(rows, dict):
                    rows = rows.get("items") or rows.get("regions") or []

                for child in body.winfo_children():
                    child.destroy()
                vars_by_region.clear()

                for region in rows:
                    rid = str(
                        region.get("id")
                        or region.get("region_id")
                        or ""
                    ).strip()
                    if not rid:
                        continue
                    rname = str(region.get("name") or "").strip()
                    var = tk.BooleanVar(value=False)
                    vars_by_region[rid] = var
                    ttk.Checkbutton(
                        body,
                        text=f"{rname or rid}  ({rid})",
                        variable=var,
                    ).pack(anchor="w", pady=3)

                if not vars_by_region:
                    ttk.Label(
                        body,
                        text="등록된 지역이 없습니다. 관리자 창의 '지역 등록'에서 먼저 등록해주세요.",
                    ).pack(anchor="w", pady=6)

            except Exception as exc:
                messagebox.showerror(
                    "지역 조회 오류",
                    str(exc),
                    parent=win,
                )

        def resolve_created_user_id(result, target_username):
            if isinstance(result, dict):
                for key in ("id", "user_id"):
                    if result.get(key) is not None:
                        return result.get(key)
                nested = result.get("user")
                if isinstance(nested, dict):
                    for key in ("id", "user_id"):
                        if nested.get(key) is not None:
                            return nested.get(key)

            rows = self.client.admin_users() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("users") or []
            for row in rows:
                if str(row.get("username") or "").strip() == target_username:
                    return row.get("id")
            return None

        def check_username(show_error=False):
            u = username.get().strip()
            if not u:
                duplicate_status.set("아이디를 입력해주세요.")
                return False
            try:
                rows = self.client.admin_users() or []
                if isinstance(rows, dict):
                    rows = rows.get("items") or rows.get("users") or []
                duplicate = any(
                    str(row.get("username") or "").strip().lower() == u.lower()
                    for row in rows
                )
                if duplicate:
                    duplicate_status.set("이미 사용 중인 아이디입니다.")
                    if show_error:
                        messagebox.showinfo(
                            "아이디 중복",
                            f"{u} 아이디는 이미 등록되어 있습니다.",
                            parent=win,
                        )
                    return False
                duplicate_status.set("사용 가능한 아이디입니다.")
                return True
            except Exception as exc:
                duplicate_status.set("중복검사 실패")
                if show_error:
                    messagebox.showerror(
                        "아이디 중복검사 오류",
                        str(exc),
                        parent=win,
                    )
                return False

        def schedule_username_check(*_):
            job = username_check_job.get("id")
            if job is not None:
                try:
                    win.after_cancel(job)
                except Exception:
                    pass
            username_check_job["id"] = win.after(
                350,
                lambda: check_username(False),
            )

        username.trace_add("write", schedule_username_check)

        def save():
            u = username.get().strip()
            if not u:
                messagebox.showinfo(
                    "신규 등록",
                    "아이디를 입력해주세요.",
                    parent=win,
                )
                return

            if not check_username(show_error=True):
                return

            try:
                lv = int(level.get().strip())
            except Exception:
                messagebox.showinfo(
                    "신규 등록",
                    "등급은 숫자로 입력해주세요.",
                    parent=win,
                )
                return

            if lv < 1 or lv > 5:
                messagebox.showinfo(
                    "신규 등록",
                    "등급은 1~5 범위로 입력해주세요.",
                    parent=win,
                )
                return

            selected_regions = [
                rid
                for rid, var in vars_by_region.items()
                if var.get()
            ]

            try:
                result = self.client.create_user(
                    u,
                    name.get(),
                    department.get(),
                    lv,
                )

                new_user_id = resolve_created_user_id(result, u)
                if new_user_id is None:
                    raise RuntimeError(
                        "사용자는 등록되었지만 사용자 ID를 확인하지 못해 지역 권한을 저장하지 못했습니다."
                    )

                self.client.reset_user_password(new_user_id, "cmb15443434")
                self.client.set_user_regions(
                    new_user_id,
                    selected_regions,
                )

                win.destroy()
                self.load_users()

                msg = (
                    f"{u} 사용자가 등록되었습니다.\n"
                    f"지역 권한: {len(selected_regions)}개"
                    "\n\n최초 비밀번호는 cmb15443434 입니다."
                    "\n암호를 변경하고 사용하세요."
                )

                messagebox.showinfo(
                    "신규 등록 완료",
                    msg,
                    parent=self,
                )

            except Exception as exc:
                messagebox.showerror(
                    "신규 등록 오류",
                    str(exc),
                    parent=win,
                )

        footer = ttk.Frame(frame)
        footer.pack(fill="x", pady=(12, 0))

        ttk.Button(
            footer,
            text="지역 목록 새로고침",
            command=load_regions,
        ).pack(side="left")

        ttk.Button(
            footer,
            text="등록",
            command=save,
        ).pack(side="right")

        ttk.Button(
            footer,
            text="취소",
            command=win.destroy,
        ).pack(side="right", padx=(0, 6))

        load_regions()

    def deactivate_user(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo("퇴사처리", "사용자를 선택해주세요.", parent=self)
            return
        user_id = user.get("id")
        username = str(user.get("username") or "")
        active = user.get("active")
        if active is None:
            active = user.get("is_active")
        if active is False:
            messagebox.showinfo("퇴사처리", "이미 비활성화된 사용자입니다.", parent=self)
            return
        if not messagebox.askyesno(
            "퇴사처리",
            f"{username} 사용자를 퇴사처리(비활성화)하시겠습니까?\n\n기존 로그인 세션도 종료됩니다.",
            parent=self,
        ):
            return
        try:
            self.client.deactivate_user(user_id)
            self.load_users()
            self.status.set(f"{username} 퇴사처리 완료")
        except Exception as exc:
            messagebox.showerror("퇴사처리 오류", str(exc), parent=self)

    def activate_user(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo("재입사/재사용", "사용자를 선택해주세요.", parent=self)
            return
        user_id = user.get("id")
        username = str(user.get("username") or "")
        active = user.get("active")
        if active is None:
            active = user.get("is_active")
        if active is not False:
            messagebox.showinfo("재입사/재사용", "현재 활성 사용자입니다.", parent=self)
            return
        if not messagebox.askyesno(
            "재입사/재사용",
            f"{username} 사용자를 다시 활성화하시겠습니까?",
            parent=self,
        ):
            return
        try:
            self.client.activate_user(user_id)
            self.load_users()
            self.status.set(f"{username} 재활성화 완료")
        except Exception as exc:
            messagebox.showerror("재활성화 오류", str(exc), parent=self)

    def register_region(self):
        if not self.current_user:
            return

        win = tk.Toplevel(self)
        win.title("지역 등록")
        win.geometry("620x560")
        win.minsize(560, 500)
        win.transient(self)
        win.grab_set()

        root = ttk.Frame(win, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="지역 등록",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "지역명과 도면명을 최초 1회 등록합니다. "
                "DXF 파일명에서 .dxf를 제외한 도면명이 그대로 지역코드가 됩니다. "
                "도면명 형식에는 제한이 없으며 같은 도면명은 중복 등록할 수 없습니다."
            ),
            wraplength=520,
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.LabelFrame(root, text="신규 지역", padding=10)
        form.pack(fill="x")

        region_code = tk.StringVar()
        region_name = tk.StringVar()

        ttk.Label(form, text="도면명 (= 지역코드)").grid(
            row=0, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            form,
            textvariable=region_code,
            width=38,
        ).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 0),
            pady=5,
        )

        ttk.Label(form, text="지역명").grid(
            row=1, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            form,
            textvariable=region_name,
            width=38,
        ).grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(8, 0),
            pady=5,
        )
        form.columnconfigure(1, weight=1)

        existing = ttk.Treeview(
            root,
            columns=("drawing", "name"),
            show="headings",
            height=8,
        )
        existing.heading("drawing", text="고유 지역코드")
        existing.heading("name", text="지역명")
        existing.column("drawing", width=250)
        existing.column("name", width=220)
        existing.pack(fill="both", expand=True, pady=(12, 0))

        def load_regions():
            try:
                rows = self.client.admin_regions() or []
                if isinstance(rows, dict):
                    rows = rows.get("items") or rows.get("regions") or []

                existing.delete(*existing.get_children())
                for i, region in enumerate(rows):
                    rid = str(
                        region.get("id")
                        or region.get("region_id")
                        or ""
                    ).strip()
                    name = str(region.get("name") or "").strip()
                    existing.insert(
                        "",
                        "end",
                        iid=str(i),
                        values=(rid, name),
                    )
            except Exception as exc:
                messagebox.showerror(
                    "지역 조회 오류",
                    str(exc),
                    parent=win,
                )

        def save_region():
            rid = region_code.get().strip()
            if rid.lower().endswith(".dxf"):
                rid = rid[:-4].strip()
            name = region_name.get().strip()

            if not rid:
                messagebox.showinfo(
                    "지역 등록",
                    "도면명을 입력해주세요.",
                    parent=win,
                )
                return
            if not name:
                messagebox.showinfo(
                    "지역 등록",
                    "지역명을 입력해주세요.",
                    parent=win,
                )
                return

            try:
                rows = self.client.admin_regions() or []
                if isinstance(rows, dict):
                    rows = rows.get("items") or rows.get("regions") or []

                duplicate_code = any(
                    str(
                        row.get("id")
                        or row.get("region_id")
                        or row.get("region_code")
                        or ""
                    ).strip().casefold() == rid.casefold()
                    for row in rows
                )
                if duplicate_code:
                    messagebox.showinfo(
                        "도면명 중복",
                        f"{rid} 도면명은 이미 등록되어 있습니다.\n"
                        "하나의 도면명은 하나의 지역코드로만 사용할 수 있습니다.",
                        parent=win,
                    )
                    return

                self.client.create_region(rid, name)
                region_code.set("")
                region_name.set("")
                load_regions()
                if self.users:
                    self.load_users()
                self.status.set(
                    f"지역 등록 완료 · {name} ({rid})"
                )
                messagebox.showinfo(
                    "지역 등록 완료",
                    f"지역명: {name}\n도면명/지역코드: {rid}\n\n"
                    f"업로드할 DXF 파일명은 {rid}.dxf 이어야 합니다.\n"
                    "이 도면명이 사용자 권한·업로드·온라인 조회에서 동일한 지역코드로 사용됩니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "지역 등록 오류",
                    str(exc),
                    parent=win,
                )

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(14, 8))

        def selected_region():
            sel = existing.selection()
            if not sel:
                messagebox.showinfo(
                    "지역 선택",
                    "수정하거나 삭제할 지역을 목록에서 선택해주세요.",
                    parent=win,
                )
                return None
            values = existing.item(sel[0], "values")
            if not values:
                return None
            rid = str(values[0]).strip()
            name = str(values[1]).strip() if len(values) > 1 else ""
            return rid, name

        def edit_region_name():
            selected = selected_region()
            if not selected:
                return
            rid, old_name = selected

            new_name = simpledialog.askstring(
                "지역명 수정",
                f"지역코드: {rid}\n\n새 지역명을 입력해주세요.",
                initialvalue=old_name,
                parent=win,
            )
            if new_name is None:
                return
            new_name = new_name.strip()
            if not new_name:
                messagebox.showinfo(
                    "지역명 수정",
                    "지역명을 입력해주세요.",
                    parent=win,
                )
                return
            if new_name == old_name:
                return

            try:
                self.client.update_region(rid, new_name)
                load_regions()
                if self.users:
                    self.load_users()
                self.status.set(
                    f"지역명 수정 완료 · {new_name} ({rid})"
                )
                messagebox.showinfo(
                    "지역명 수정 완료",
                    f"지역코드: {rid}\n기존 지역명: {old_name}\n새 지역명: {new_name}",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "지역명 수정 오류",
                    str(exc),
                    parent=win,
                )

        def delete_region():
            selected = selected_region()
            if not selected:
                return
            rid, name = selected

            if not messagebox.askyesno(
                "지역 삭제",
                (
                    f"다음 지역을 삭제하시겠습니까?\n\n"
                    f"지역명: {name or '-'}\n"
                    f"지역코드: {rid}\n\n"
                    "이 지역을 삭제하면 서버에 저장된 도면 Revision과 객체, "
                    "SYMBOL 데이터, 사용자-지역 권한 연결까지 함께 삭제됩니다.\n\n"
                    "잘못 등록한 지역을 정리할 때만 사용해주세요.\n"
                    "삭제 후에는 복구할 수 없습니다."
                ),
                parent=win,
            ):
                return

            try:
                self.client.delete_region(rid)
                load_regions()
                if self.users:
                    self.load_users()
                self.status.set(
                    f"지역 삭제 완료 · {name or rid} ({rid})"
                )
                messagebox.showinfo(
                    "지역 삭제 완료",
                    f"{name or rid} ({rid}) 지역을 삭제했습니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "지역 삭제 오류",
                    str(exc),
                    parent=win,
                )

        ttk.Button(
            footer,
            text="목록 새로고침",
            command=load_regions,
        ).pack(side="left")

        ttk.Button(
            footer,
            text="지역명 수정",
            command=edit_region_name,
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            footer,
            text="지역 삭제",
            command=delete_region,
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            footer,
            text="등록",
            command=save_region,
        ).pack(side="right")

        ttk.Button(
            footer,
            text="닫기",
            command=win.destroy,
        ).pack(side="right", padx=(0, 6))

        load_regions()


    def _region_choices(self):
        rows = self.client.admin_regions() or []
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("regions") or []
        result = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or row.get("region_id") or row.get("region_code") or "").strip()
            if not rid:
                continue
            name = str(row.get("name") or row.get("region_name") or rid).strip()
            result.append((rid, name))
        return result

    def view_drawing_status(self):
        """조회 전용: 지역별 현재 도면 revision/객체 수만 보여준다."""
        win = tk.Toplevel(self)
        win.title("도면 버전/업로드 현황 조회")
        win.geometry("980x560")
        win.minsize(820, 460)
        win.transient(self)

        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="도면 버전/업로드 현황", font=("Malgun Gothic", 15, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text="조회 전용 화면입니다. 이 창에서는 도면 삭제나 수정이 불가능합니다.",
        ).pack(anchor="w", pady=(2, 10))

        top = ttk.Frame(root)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="지역").pack(side="left")
        region_var = tk.StringVar()
        combo = ttk.Combobox(top, textvariable=region_var, state="readonly", width=48)
        combo.pack(side="left", padx=(6, 6))

        region_map = {}
        def load_regions():
            try:
                choices = self._region_choices()
                region_map.clear()
                values = []
                for rid, name in choices:
                    display = f"{name} ({rid})" if name and name != rid else rid
                    values.append(display)
                    region_map[display] = rid
                combo["values"] = values
                if values and not region_var.get():
                    region_var.set(values[0])
            except Exception as exc:
                messagebox.showerror("도면 현황 조회", str(exc), parent=win)

        columns=("group","revision","state","count","date","memo")
        tree=ttk.Treeview(root, columns=columns, show="headings", height=16)
        for key,title,width in (
            ("group","그룹",90),
            ("revision","저장일-차수",125),
            ("state","상태",80),
            ("count","객체수",90),
            ("date","저장일시",170),
            ("memo","메모",360),
        ):
            tree.heading(key,text=title)
            tree.column(key,width=width,anchor="w")
        tree.pack(fill="both", expand=True)

        status_var=tk.StringVar(value="")
        ttk.Label(root,textvariable=status_var).pack(fill="x",pady=(8,0))

        def refresh():
            display=region_var.get().strip()
            rid=region_map.get(display,"")
            if not rid:
                return
            try:
                for item in tree.get_children():
                    tree.delete(item)
                data=self.client.drawing_status(rid) or {}
                rows=data.get("groups") or data.get("items") or data.get("revisions") or []
                for idx,row in enumerate(rows):
                    group=str(row.get("group_id") or row.get("group") or "")
                    rev=row.get("revision")
                    created_raw=str(row.get("created_at") or "")
                    day=created_raw[:10].replace("-", "") if len(created_raw)>=10 else ""
                    display_rev=(f"{day}-{int(rev):02d}" if day and str(rev or "").isdigit() else (rev if rev is not None else "-"))
                    active=row.get("active", True)
                    state="현재" if active else "백업"
                    count=int(row.get("object_count") or row.get("count") or 0)
                    created=str(row.get("created_at") or "").replace("T"," ")[:19]
                    memo=str(row.get("memo") or "").strip()
                    tree.insert("", "end", iid=f"r{idx}", values=(group, display_rev, state, f"{count:,}", created or "-", memo or "-"))
                status_var.set(f"{rid} · 조회 완료 · {len(rows)}개 항목")
            except Exception as exc:
                messagebox.showerror("도면 현황 조회", str(exc), parent=win)

        ttk.Button(top,text="조회",command=refresh).pack(side="left")
        ttk.Button(top,text="지역 새로고침",command=load_regions).pack(side="left",padx=(6,0))
        load_regions()

    def open_force_delete_drawing(self):
        """위험 작업 전용 창: 지역별 그룹을 개별 조회/삭제한다."""
        win = tk.Toplevel(self)
        win.title("도면 항목 강제 삭제")
        win.geometry("820x600")
        win.minsize(720, 520)
        win.transient(self)

        root = ttk.Frame(win, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="도면 항목 강제 삭제", font=("Malgun Gothic", 15, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "위험 작업 전용 화면입니다. 지역 자체와 사용자 지역 권한은 유지하며, "
                "선택한 도면 항목만 삭제합니다."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(4, 12))

        region_var = tk.StringVar()
        region_map = {}
        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Label(top, text="지역").pack(side="left")
        combo = ttk.Combobox(top, textvariable=region_var, state="readonly", width=46)
        combo.pack(side="left", padx=(8, 6))
        ttk.Button(top, text="조회", command=lambda: load_status()).pack(side="left")
        ttk.Button(top, text="지역 새로고침", command=lambda: load_regions()).pack(side="left", padx=(6, 0))

        tree = ttk.Treeview(
            root,
            columns=("group", "revision", "count", "date", "memo"),
            show="headings",
            selectmode="extended",
            height=12,
        )
        for key, title, width in (
            ("group", "항목", 100),
            ("revision", "현재 Revision", 110),
            ("count", "객체수", 100),
            ("date", "저장일시", 170),
            ("memo", "메모", 300),
        ):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True, pady=(12, 8))

        note = tk.StringVar(value="삭제할 항목을 하나 이상 선택해주세요. 전체 삭제가 필요하면 전체 선택을 사용하세요.")
        ttk.Label(root, textvariable=note).pack(anchor="w")

        confirm_var = tk.StringVar()
        ttk.Label(
            root,
            text='실행하려면 아래 칸에 "지역코드/항목"을 정확히 입력해주세요. 예: CMB_GN_HP/COAX',
        ).pack(anchor="w", pady=(10, 0))
        ttk.Entry(root, textvariable=confirm_var).pack(fill="x", pady=(5, 10))

        current_rows = {}

        def load_regions():
            try:
                choices = self._region_choices()
                values = []
                region_map.clear()
                for rid, name in choices:
                    display = f"{name} ({rid})" if name and name != rid else rid
                    values.append(display)
                    region_map[display] = rid
                combo["values"] = values
                if values:
                    if region_var.get() not in values:
                        region_var.set(values[0])
                    load_status()
            except Exception as exc:
                messagebox.showerror("도면 항목 강제 삭제", str(exc), parent=win)

        def load_status():
            rid = region_map.get(region_var.get().strip(), "")
            if not rid:
                return
            try:
                for item in tree.get_children():
                    tree.delete(item)
                current_rows.clear()
                data = self.client.drawing_status(rid) or {}
                rows = data.get("groups") or data.get("items") or data.get("revisions") or []

                # 현재본만 그룹별 1줄로 표시한다.
                latest = {}
                for row in rows:
                    group = str(row.get("group_id") or row.get("group") or "").upper()
                    if not group:
                        continue
                    if not row.get("active", True):
                        continue
                    latest[group] = row

                order = ("FIBER", "COAX", "POLE", "CONDUIT", "USER", "SYMBOL")
                for group in order:
                    row = latest.get(group)
                    if row:
                        rev = row.get("revision")
                        count = int(row.get("object_count") or row.get("count") or 0)
                        created = str(row.get("created_at") or "").replace("T", " ")[:19]
                        memo = str(row.get("memo") or "").strip() or "-"
                    else:
                        rev = "-"
                        count = 0
                        created = "-"
                        memo = "현재 도면 없음"
                    iid = "g_" + group
                    tree.insert(
                        "",
                        "end",
                        iid=iid,
                        values=(group, rev if rev is not None else "-", f"{count:,}", created, memo),
                    )
                    current_rows[iid] = {"group": group, "exists": row is not None, "count": count}

                confirm_var.set("")
                note.set(f"{rid} · 항목별 현재 도면 상태")
            except Exception as exc:
                messagebox.showerror("도면 항목 조회", str(exc), parent=win)

        def selected_groups():
            selected = list(tree.selection())
            if not selected:
                messagebox.showinfo("도면 항목 삭제", "삭제할 항목을 하나 이상 선택해주세요.", parent=win)
                return "", []
            rid = region_map.get(region_var.get().strip(), "")
            infos = [current_rows.get(iid) or {} for iid in selected]
            infos = [x for x in infos if x.get("group")]
            return rid, infos

        def select_all_groups():
            tree.selection_set(tree.get_children())
            rid = region_map.get(region_var.get().strip(), "")
            if rid:
                confirm_var.set("")
                note.set(f"{rid} · 전체 항목 선택됨")

        def clear_group_selection():
            tree.selection_remove(tree.selection())
            confirm_var.set("")
            note.set("삭제할 항목을 하나 이상 선택해주세요.")

        def execute_delete():
            rid, infos = selected_groups()
            if not rid or not infos:
                return

            existing = [x for x in infos if x.get("exists")]
            if not existing:
                messagebox.showinfo("도면 항목 삭제", "선택한 항목에는 현재 도면이 없습니다.", parent=win)
                return

            groups = [str(x.get("group") or "").upper() for x in existing]
            expected = f"{rid}/" + ("ALL" if len(groups) == 6 else "+".join(groups))
            if confirm_var.get().strip().upper() != expected.upper():
                messagebox.showerror(
                    "도면 항목 삭제",
                    f"확인을 위해 {expected} 를 정확히 입력해주세요.",
                    parent=win,
                )
                return

            lines = [f"- {x.get('group')}: {int(x.get('count') or 0):,}개" for x in existing]
            ok = messagebox.askyesno(
                "최종 확인",
                (
                    f"지역: {rid}\n"
                    "삭제 항목:\n" + "\n".join(lines) + "\n\n"
                    "선택한 항목의 현재본과 백업 revision을 모두 삭제합니다.\n"
                    "선택하지 않은 항목, 다른 지역, 지역 등록, 사용자 지역 권한은 유지됩니다.\n\n"
                    "정말 삭제하시겠습니까?"
                ),
                parent=win,
            )
            if not ok:
                return

            deleted_groups = []
            failed = []
            for info in existing:
                group = str(info.get("group") or "").upper()
                try:
                    self.client.force_delete_drawing_group(rid, group)
                    deleted_groups.append(group)
                except Exception as exc:
                    failed.append(f"{group}: {exc}")

            message = "삭제 완료: " + (", ".join(deleted_groups) if deleted_groups else "없음")
            if failed:
                message += "\n\n실패:\n" + "\n".join(failed)
            messagebox.showinfo("도면 항목 삭제 결과", message, parent=win)
            load_status()

        action_row = ttk.Frame(root)
        action_row.pack(fill="x")
        ttk.Button(action_row, text="전체 선택", command=select_all_groups).pack(side="left")
        ttk.Button(action_row, text="선택 해제", command=clear_group_selection).pack(side="left", padx=(6, 0))
        ttk.Button(action_row, text="선택 항목 강제 삭제", command=execute_delete).pack(side="right")
        load_regions()

    def edit_regions(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo(
                "지역/권한 관리",
                "먼저 사용자를 선택해주세요.",
                parent=self,
            )
            return

        user_id = user.get("id")
        username = str(user.get("username") or "")
        if user_id is None:
            return

        win = tk.Toplevel(self)
        win.title(f"지역/권한 관리 · {username}")
        win.geometry("620x560")
        win.minsize(540, 480)
        win.transient(self)
        win.grab_set()

        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text=f"{username} · 사용 가능 지역",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "이미 등록된 지역만 선택할 수 있습니다. "
                "새 지역 등록은 관리자 창의 '지역 등록' 버튼을 사용하세요."
            ),
            wraplength=580,
        ).pack(anchor="w", pady=(2, 10))

        box = ttk.LabelFrame(
            root,
            text="등록 지역 선택",
            padding=10,
        )
        box.pack(fill="both", expand=True)

        canvas = tk.Canvas(box, highlightthickness=0)
        scroll = ttk.Scrollbar(
            box,
            orient="vertical",
            command=canvas.yview,
        )
        body = ttk.Frame(canvas)
        body_window = canvas.create_window(
            (0, 0),
            window=body,
            anchor="nw",
        )

        body.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(body_window, width=e.width),
        )
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        vars_by_region = {}

        def load_all():
            try:
                rows = self.client.admin_regions() or []
                assigned = self.client.user_regions(user_id) or []

                if isinstance(rows, dict):
                    rows = rows.get("items") or rows.get("regions") or []
                if isinstance(assigned, dict):
                    assigned = assigned.get("items") or assigned.get("regions") or []

                assigned_ids = {
                    str(
                        x.get("id")
                        or x.get("region_id")
                        or ""
                    )
                    for x in assigned
                }

                for child in body.winfo_children():
                    child.destroy()
                vars_by_region.clear()

                for region in rows:
                    rid = str(
                        region.get("id")
                        or region.get("region_id")
                        or ""
                    ).strip()
                    if not rid:
                        continue
                    name = str(region.get("name") or "").strip()
                    var = tk.BooleanVar(value=rid in assigned_ids)
                    vars_by_region[rid] = var
                    ttk.Checkbutton(
                        body,
                        text=f"{name or rid}  ({rid})",
                        variable=var,
                    ).pack(anchor="w", pady=4)

                if not vars_by_region:
                    ttk.Label(
                        body,
                        text="등록된 지역이 없습니다.",
                    ).pack(anchor="w", pady=6)

            except Exception as exc:
                messagebox.showerror(
                    "지역 조회 오류",
                    str(exc),
                    parent=win,
                )

        def save_permissions():
            selected = [
                rid
                for rid, var in vars_by_region.items()
                if var.get()
            ]
            try:
                self.client.set_user_regions(
                    user_id,
                    selected,
                )
                # 서버 저장 직후 관리자 조회 목록의 배정 지역도 즉시 갱신한다.
                self.load_users()
                self.status.set(
                    f"{username} 지역 권한 저장 완료 · {len(selected)}개 지역"
                )
                messagebox.showinfo(
                    "지역 권한",
                    f"{username} 사용자의 지역 권한이 저장되고 조회 화면도 갱신되었습니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "지역 권한 저장 오류",
                    str(exc),
                    parent=win,
                )

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))

        ttk.Button(
            footer,
            text="지역 목록 새로고침",
            command=load_all,
        ).pack(side="left")

        ttk.Button(
            footer,
            text="전체 선택",
            command=lambda: [
                var.set(True)
                for var in vars_by_region.values()
            ],
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            footer,
            text="전체 해제",
            command=lambda: [
                var.set(False)
                for var in vars_by_region.values()
            ],
        ).pack(side="left", padx=(6, 0))

        ttk.Button(
            footer,
            text="권한 저장",
            command=save_permissions,
        ).pack(side="right")

        ttk.Button(
            footer,
            text="닫기",
            command=win.destroy,
        ).pack(side="right", padx=(0, 6))

        load_all()

    def edit_session_timeout(self):
        if not self.current_user:
            return
        try:
            result = self.client.admin_session_timeout() or {}
            current = int(result.get('minutes', 10))
        except Exception as exc:
            messagebox.showerror('로그인 유지시간', str(exc), parent=self)
            return

        value = simpledialog.askinteger(
            '로그인 유지시간',
            '비밀번호 재입력까지의 로그인 유지시간(분)\n권장값: 10분\n허용 범위: 5~120분',
            initialvalue=current,
            minvalue=5,
            maxvalue=120,
            parent=self,
        )
        if value is None:
            return

        try:
            self.client.set_admin_session_timeout(value)
            self.status.set(f'로그인 유지시간 {value}분으로 변경')
            self.session_timeout_text.set(f"로그인 유지시간: {value}분")
            messagebox.showinfo(
                '로그인 유지시간',
                f'로그인 유지시간을 {value}분으로 설정했습니다.\n새 로그인부터 적용됩니다.',
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror('로그인 유지시간', str(exc), parent=self)

    def edit_backup_retention(self):
        if not self.current_user:
            return
        try:
            result = self.client.admin_backup_retention() or {}
            current = int(result.get("count", 2))
        except Exception as exc:
            messagebox.showerror("백업 보관 설정", str(exc), parent=self)
            return

        value = simpledialog.askinteger(
            "백업 보관 설정",
            (
                "그룹별로 보관할 이전 도면 백업 개수\n\n"
                "0 = 백업 안 함\n"
                "1 = 최근 백업 1개\n"
                "2 = 최근 백업 2개\n"
                "필요 시 최대 10개까지 설정 가능\n\n"
                "변경값은 다음 정상 업로드부터 해당 그룹에 적용됩니다."
            ),
            initialvalue=current,
            minvalue=0,
            maxvalue=10,
            parent=self,
        )
        if value is None:
            return

        try:
            self.client.set_admin_backup_retention(value)
            self._refresh_backup_retention_display()
            if value == 0:
                label = "백업 사용 안 함"
            else:
                label = f"최근 백업 {value}개"
            self.status.set(f"도면 백업 보관 설정 변경 · {label}")
            messagebox.showinfo(
                "백업 보관 설정",
                (
                    f"도면 백업 보관 설정을 '{label}'으로 변경했습니다.\n\n"
                    "기존 백업은 즉시 삭제하지 않고, "
                    "각 그룹의 다음 정상 업로드 성공 시 설정 개수에 맞게 정리됩니다."
                ),
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("백업 보관 설정", str(exc), parent=self)

    def reset_device(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo("단말 초기화", "사용자를 선택해주세요.", parent=self)
            return

        user_id = user.get("id")
        username = str(user.get("username") or "").strip()

        current = self.current_user or {}
        current_id = current.get("id")
        current_username = str(current.get("username") or "").strip()

        same_id = (
            user_id is not None
            and current_id is not None
            and str(user_id) == str(current_id)
        )
        same_username = (
            bool(username)
            and bool(current_username)
            and username.casefold() == current_username.casefold()
        )
        self_reset = same_id or same_username

        if self_reset:
            message = (
                f"{username} 계정은 현재 이 관리자 프로그램에 로그인 중인 본인 계정입니다.\n\n"
                "단말 초기화를 실행하면:\n"
                "• 현재 PC의 등록 단말 정보가 삭제됩니다.\n"
                "• 현재 관리자 로그인 세션을 포함한 기존 세션이 모두 종료됩니다.\n"
                "• 이 관리자 창도 즉시 닫히고 다시 로그인해야 합니다.\n"
                "• 이후 다른 PC에서 로그인하면 그 PC가 새 Windows 단말로 등록됩니다.\n\n"
                "계속하시겠습니까?"
            )
        else:
            message = (
                f"{username} 사용자의 등록 단말을 초기화하시겠습니까?\n\n"
                "등록 단말과 기존 로그인 세션이 모두 해제됩니다.\n"
                "다음 로그인 단말이 새 단말로 등록됩니다."
            )

        if not messagebox.askyesno(
            "본인 단말 초기화 경고" if self_reset else "단말 초기화",
            message,
            parent=self,
        ):
            return

        guard = getattr(self.master, "session_guard", None)
        if self_reset and guard is not None:
            try:
                guard.pause()
            except Exception:
                pass

        try:
            result = self.client.reset_user_device(user_id) or {}
            self.status.set(f"{username} 단말 초기화 완료")

            if self_reset:
                # 서버가 현재 세션까지 revoke 했으므로 이 PC에서 더 이상
                # heartbeat/API를 보내 기존 단말이 재등록되지 않도록 즉시 로컬 세션도 폐기한다.
                try:
                    self.client.access_token = ""
                    self.client.refresh_token = ""
                    self.client.clear_shared_state()
                except Exception:
                    pass

                messagebox.showinfo(
                    "본인 단말 초기화 완료",
                    "현재 관리자 계정의 등록 단말과 로그인 세션을 모두 초기화했습니다.\n\n"
                    "이 PC의 로그인은 종료됩니다.\n"
                    "다른 PC에서 새로 로그인하면 그 PC가 새 Windows 단말로 등록됩니다.",
                    parent=self,
                )

                try:
                    if hasattr(self.master, "_reset_login_state"):
                        self.master._reset_login_state(
                            "단말 초기화로 현재 세션이 종료되었습니다. 다시 로그인해주세요."
                        )
                finally:
                    self.destroy()
                return

            messagebox.showinfo(
                "단말 초기화",
                "등록 단말과 기존 로그인 세션을 모두 초기화했습니다.\n"
                "다음 정상 로그인 단말이 새 단말로 등록됩니다.",
                parent=self,
            )
        except Exception as exc:
            if self_reset and guard is not None:
                try:
                    guard.resume()
                except Exception:
                    pass
            messagebox.showerror("단말 초기화 오류", str(exc), parent=self)

    def set_level(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo("등급 설정", "사용자를 선택해주세요.", parent=self)
            return
        user_id = user.get("id")
        username = str(user.get("username") or "").strip()
        try:
            current = int(user.get("level") or 5)
        except Exception:
            current = 5
        level = simpledialog.askinteger(
            "등급 설정",
            f"{username} 사용자의 등급을 선택해주세요.\n\n1=관리자(2시간) / 3=추출사용자(1시간) / 5=일반(30분)",
            initialvalue=current,
            minvalue=1,
            maxvalue=5,
            parent=self,
        )
        if level is None:
            return
        try:
            self.client.set_user_level(user_id, level)
            self.load_users()
            self.status.set(f"{username} 등급 {level}로 변경 완료")
        except Exception as exc:
            messagebox.showerror("등급 설정 오류", str(exc), parent=self)

    def reset_password(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo("비밀번호 초기화", "사용자를 선택해주세요.", parent=self)
            return

        user_id = user.get("id")
        username = str(user.get("username") or "").strip()
        if not username:
            return

        if not messagebox.askyesno(
            "비밀번호 초기화",
            (
                f"{username} 사용자의 비밀번호를 초기화하시겠습니까?\n\n"
                "초기 비밀번호: cmb15443434\n"
                "이 비밀번호로 로그인하면 반드시 암호 변경 화면으로 이동합니다."
            ),
            parent=self,
        ):
            return

        try:
            self.client.reset_user_password(user_id, "cmb15443434")
            self.status.set(f"{username} 비밀번호 초기화 완료")
            messagebox.showinfo(
                "비밀번호 초기화",
                (
                    "최초 비밀번호는 cmb15443434 입니다.\n"
                    "암호를 변경하고 사용하세요."
                ),
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("비밀번호 초기화 오류", str(exc), parent=self)

