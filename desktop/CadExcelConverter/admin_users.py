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

        self.title("관리자 · 사용자 관리")
        self.geometry("1240x620")
        self.minsize(1080, 520)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="사용자 관리", font=("Malgun Gothic", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="1등급 관리자 전용").pack(anchor="w", pady=(2, 10))

        self.login_status = tk.StringVar(value="")
        session_line = ttk.Label(root, textvariable=self.login_status)
        session_line.pack(anchor="w", pady=(0, 8))

        tools = ttk.Frame(root)
        tools.pack(fill="x", pady=(10, 6))

        self.search_var = tk.StringVar()
        ttk.Label(tools, text="검색").pack(side="left")
        search = ttk.Entry(tools, textvariable=self.search_var, width=28)
        search.pack(side="left", padx=(6, 6))
        search.bind("<KeyRelease>", lambda e: self.apply_filter())

        self.lookup_btn = ttk.Button(
            tools, text="사용자 조회", command=self.load_users, state="disabled"
        )
        self.lookup_btn.pack(side="left")

        self.new_btn = ttk.Button(
            tools, text="신규 등록", command=self.create_user, state="disabled"
        )
        self.new_btn.pack(side="left", padx=(6, 0))

        self.reset_btn = ttk.Button(
            tools, text="비밀번호 초기화", command=self.reset_password, state="disabled"
        )
        self.reset_btn.pack(side="left", padx=(6, 0))

        self.deactivate_btn = ttk.Button(
            tools, text="퇴사처리", command=self.deactivate_user, state="disabled"
        )
        self.deactivate_btn.pack(side="left", padx=(6, 0))

        self.activate_btn = ttk.Button(
            tools, text="재입사/재사용", command=self.activate_user, state="disabled"
        )
        self.activate_btn.pack(side="left", padx=(6, 0))

        self.region_btn = ttk.Button(
            tools, text="지역/권한 관리", command=self.edit_regions, state="disabled"
        )
        self.region_btn.pack(side="left", padx=(6, 0))

        self.region_register_btn = ttk.Button(
            tools, text="지역 등록", command=self.register_region, state="disabled"
        )
        self.region_register_btn.pack(side="left", padx=(6, 0))

        self.session_btn = ttk.Button(
            tools, text="로그인 유지시간", command=self.edit_session_timeout, state="disabled"
        )
        self.session_btn.pack(side="left", padx=(6, 0))

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame,
            columns=("username", "name", "department", "level", "active"),
            show="headings",
            selectmode="browse",
        )
        for key, title, width in (
            ("username", "아이디", 150),
            ("name", "이름", 130),
            ("department", "부서", 210),
            ("level", "등급", 70),
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
        self.deactivate_btn.configure(state="normal")
        self.activate_btn.configure(state="normal")
        self.region_btn.configure(state="normal")
        self.region_register_btn.configure(state="normal")
        self.session_btn.configure(state="normal")
        self.load_users()

    def load_users(self):
        if not self.current_user:
            return
        try:
            rows = self.client.admin_users() or []
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("users") or []
            self.users = list(rows)
            self.apply_filter()
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
                for k in ("username", "name", "department", "level")
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
                    active_text,
                ),
            )
            shown += 1
        if q:
            self.status.set(f"검색 결과 {shown}명 / 전체 {len(self.users)}명")

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

        def save():
            u = username.get().strip()
            if not u:
                messagebox.showinfo(
                    "신규 등록",
                    "아이디를 입력해주세요.",
                    parent=win,
                )
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

                self.client.set_user_regions(
                    new_user_id,
                    selected_regions,
                )

                temp = str(
                    (result or {}).get("temporary_password")
                    or ""
                )

                win.destroy()
                self.load_users()

                msg = (
                    f"{u} 사용자가 등록되었습니다.\n"
                    f"지역 권한: {len(selected_regions)}개"
                )
                if temp:
                    msg += (
                        f"\n\n임시 비밀번호: {temp}"
                        "\n\n이 비밀번호는 지금 한 번만 표시됩니다."
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
        win.geometry("560x420")
        win.minsize(500, 360)
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
                "도면명은 서버에 업로드할 DXF 파일명에서 .dxf를 제외한 값입니다. "
                "예: CMB_GN_KSG.dxf → CMB_GN_KSG"
            ),
            wraplength=520,
        ).pack(anchor="w", pady=(2, 12))

        form = ttk.LabelFrame(root, text="신규 지역", padding=10)
        form.pack(fill="x")

        drawing_name = tk.StringVar()
        region_name = tk.StringVar()

        ttk.Label(form, text="도면명").grid(
            row=0, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            form,
            textvariable=drawing_name,
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
        existing.heading("drawing", text="등록 도면명")
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
            rid = drawing_name.get().strip()
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
                self.client.create_region(rid, name)
                drawing_name.set("")
                region_name.set("")
                load_regions()
                self.status.set(
                    f"지역 등록 완료 · {rid} · {name}"
                )
                messagebox.showinfo(
                    "지역 등록 완료",
                    f"도면명: {rid}\n지역명: {name}\n\n"
                    f"서버 업로드 DXF 파일명은 {rid}.dxf 이어야 합니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "지역 등록 오류",
                    str(exc),
                    parent=win,
                )

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))

        ttk.Button(
            footer,
            text="목록 새로고침",
            command=load_regions,
        ).pack(side="left")

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
                self.status.set(
                    f"{username} 지역 권한 저장 완료 · {len(selected)}개 지역"
                )
                messagebox.showinfo(
                    "지역 권한",
                    f"{username} 사용자의 지역 권한이 저장되었습니다.",
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
            messagebox.showinfo(
                '로그인 유지시간',
                f'로그인 유지시간을 {value}분으로 설정했습니다.\n새 로그인부터 적용됩니다.',
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror('로그인 유지시간', str(exc), parent=self)

    def reset_password(self):
        user = self._selected_user()
        if not user:
            messagebox.showinfo("비밀번호 초기화", "사용자를 선택해주세요.", parent=self)
            return

        user_id = user.get("id")
        username = str(user.get("username") or "").strip()
        if not username:
            return

        p1 = simpledialog.askstring(
            "비밀번호 초기화",
            f"{username} 사용자의 새 임시 비밀번호를 입력해주세요.\n(8자 이상)",
            show="*",
            parent=self,
        )
        if p1 is None:
            return
        if len(p1) < 8:
            messagebox.showinfo("비밀번호", "8자 이상으로 입력해주세요.", parent=self)
            return

        p2 = simpledialog.askstring(
            "비밀번호 확인",
            "임시 비밀번호를 다시 입력해주세요.",
            show="*",
            parent=self,
        )
        if p1 != p2:
            messagebox.showinfo("비밀번호", "비밀번호 확인이 일치하지 않습니다.", parent=self)
            return

        if not messagebox.askyesno(
            "비밀번호 초기화",
            f"{username} 사용자의 비밀번호를 초기화하시겠습니까?",
            parent=self,
        ):
            return

        try:
            self.client.reset_user_password(user_id, p1)
            self.status.set(f"{username} 비밀번호 초기화 완료")
            messagebox.showinfo(
                "비밀번호 초기화",
                f"{username} 사용자의 비밀번호가 초기화되었습니다.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("비밀번호 초기화 오류", str(exc), parent=self)
