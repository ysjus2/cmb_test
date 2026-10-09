from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from server_client_windows import CMBServerClient


class UserAdminWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.client = CMBServerClient()
        self.current_user = None
        self.users = []

        self.title("관리자 · 사용자 관리")
        self.geometry("760x580")
        self.minsize(680, 500)

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="사용자 관리", font=("Malgun Gothic", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="1등급 관리자 전용").pack(anchor="w", pady=(2, 10))

        login = ttk.LabelFrame(root, text="관리자 로그인", padding=8)
        login.pack(fill="x")

        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.login_status = tk.StringVar(value="로그인이 필요합니다.")

        ttk.Label(login, text="아이디").grid(row=0, column=0, sticky="w")
        ttk.Entry(login, textvariable=self.username, width=20).grid(row=0, column=1, padx=(6, 12))
        ttk.Label(login, text="비밀번호").grid(row=0, column=2, sticky="w")
        pw = ttk.Entry(login, textvariable=self.password, show="*", width=20)
        pw.grid(row=0, column=3, padx=(6, 12))
        pw.bind("<Return>", lambda e: self.login())
        ttk.Button(login, text="로그인", command=self.login).grid(row=0, column=4)
        ttk.Label(login, textvariable=self.login_status).grid(
            row=1, column=0, columnspan=5, sticky="w", pady=(6, 0)
        )

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

    def login(self):
        username = self.username.get().strip()
        password = self.password.get()
        if not username or not password:
            messagebox.showinfo("로그인", "아이디와 비밀번호를 입력해주세요.", parent=self)
            return
        try:
            user = self.client.login(username, password)
            self.password.set("")
            level = int(user.get("level", 5))
            if level != 1:
                self.current_user = None
                self.login_status.set("1등급 관리자만 사용자 관리가 가능합니다.")
                self.lookup_btn.configure(state="disabled")
                self.new_btn.configure(state="disabled")
                self.reset_btn.configure(state="disabled")
                self.deactivate_btn.configure(state="disabled")
                self.activate_btn.configure(state="disabled")
                self.region_btn.configure(state="disabled")
                return
            self.current_user = user
            self.login_status.set(
                f"{user.get('name') or user.get('username')} · 1등급 관리자"
            )
            self.lookup_btn.configure(state="normal")
            self.new_btn.configure(state="normal")
            self.reset_btn.configure(state="normal")
            self.deactivate_btn.configure(state="normal")
            self.activate_btn.configure(state="normal")
            self.region_btn.configure(state="normal")
            self.load_users()
        except Exception as exc:
            self.current_user = None
            messagebox.showerror("로그인 오류", str(exc), parent=self)

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
        win.geometry("420x300")
        win.transient(self)
        win.grab_set()

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)

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
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=var, width=32).grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=5)

        frame.columnconfigure(1, weight=1)

        def save():
            u = username.get().strip()
            if not u:
                messagebox.showinfo("신규 등록", "아이디를 입력해주세요.", parent=win)
                return
            try:
                lv = int(level.get().strip())
            except Exception:
                messagebox.showinfo("신규 등록", "등급은 숫자로 입력해주세요.", parent=win)
                return
            if lv < 1 or lv > 5:
                messagebox.showinfo("신규 등록", "등급은 1~5 범위로 입력해주세요.", parent=win)
                return
            try:
                result = self.client.create_user(
                    u,
                    name.get(),
                    department.get(),
                    lv,
                )
                temp = str((result or {}).get("temporary_password") or "")
                win.destroy()
                self.load_users()
                msg = f"{u} 사용자가 등록되었습니다."
                if temp:
                    msg += f"\n\n임시 비밀번호: {temp}\n\n이 비밀번호는 지금 한 번만 표시됩니다."
                messagebox.showinfo("신규 등록 완료", msg, parent=self)
            except Exception as exc:
                messagebox.showerror("신규 등록 오류", str(exc), parent=win)

        ttk.Button(frame, text="등록", command=save).grid(
            row=len(rows), column=0, columnspan=2, pady=(14, 0)
        )

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
        win.geometry("860x560")
        win.minsize(760, 500)
        win.transient(self)
        win.grab_set()

        root = ttk.Frame(win, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="지역 등록 및 사용자 지역 권한",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "지역 코드는 DXF 파일명(확장자 제외)과 완전히 동일해야 합니다. "
                "코드 형식에는 별도 제한을 두지 않습니다."
            ),
        ).pack(anchor="w", pady=(2, 10))

        content = ttk.Panedwindow(root, orient="horizontal")
        content.pack(fill="both", expand=True)

        left = ttk.LabelFrame(content, text="지역 관리", padding=10)
        right = ttk.LabelFrame(
            content,
            text=f"{username} · 사용 가능 지역",
            padding=10,
        )
        content.add(left, weight=1)
        content.add(right, weight=1)

        region_tree = ttk.Treeview(
            left,
            columns=("id", "name"),
            show="headings",
            height=14,
        )
        region_tree.heading("id", text="지역 코드")
        region_tree.heading("name", text="지역명")
        region_tree.column("id", width=190)
        region_tree.column("name", width=150)
        region_tree.pack(fill="both", expand=True)

        add_box = ttk.Frame(left)
        add_box.pack(fill="x", pady=(10, 0))

        new_id = tk.StringVar()
        new_name = tk.StringVar()

        ttk.Label(add_box, text="지역 코드").grid(
            row=0, column=0, sticky="w", pady=3
        )
        ttk.Entry(add_box, textvariable=new_id, width=24).grid(
            row=0, column=1, sticky="ew", padx=(6, 0), pady=3
        )
        ttk.Label(add_box, text="지역명").grid(
            row=1, column=0, sticky="w", pady=3
        )
        ttk.Entry(add_box, textvariable=new_name, width=24).grid(
            row=1, column=1, sticky="ew", padx=(6, 0), pady=3
        )
        add_box.columnconfigure(1, weight=1)

        check_canvas = tk.Canvas(right, highlightthickness=0)
        check_scroll = ttk.Scrollbar(
            right,
            orient="vertical",
            command=check_canvas.yview,
        )
        check_body = ttk.Frame(check_canvas)
        check_window = check_canvas.create_window(
            (0, 0),
            window=check_body,
            anchor="nw",
        )

        check_body.bind(
            "<Configure>",
            lambda e: check_canvas.configure(
                scrollregion=check_canvas.bbox("all")
            ),
        )
        check_canvas.bind(
            "<Configure>",
            lambda e: check_canvas.itemconfigure(
                check_window,
                width=e.width,
            ),
        )
        check_canvas.configure(yscrollcommand=check_scroll.set)
        check_canvas.pack(side="left", fill="both", expand=True)
        check_scroll.pack(side="right", fill="y")

        vars_by_region = {}
        current_regions = []

        def load_all():
            nonlocal current_regions
            try:
                rows = self.client.admin_regions() or []
                assigned = self.client.user_regions(user_id) or []

                if isinstance(rows, dict):
                    rows = rows.get("items") or rows.get("regions") or []
                if isinstance(assigned, dict):
                    assigned = assigned.get("items") or assigned.get("regions") or []

                current_regions = list(rows)
                assigned_ids = {
                    str(x.get("id") or x.get("region_id") or "")
                    for x in assigned
                }

                region_tree.delete(*region_tree.get_children())
                for child in check_body.winfo_children():
                    child.destroy()
                vars_by_region.clear()

                for i, region in enumerate(current_regions):
                    rid = str(region.get("id") or "").strip()
                    if not rid:
                        continue
                    name = str(region.get("name") or "")
                    region_tree.insert(
                        "",
                        "end",
                        iid=str(i),
                        values=(rid, name),
                    )

                    var = tk.BooleanVar(value=rid in assigned_ids)
                    vars_by_region[rid] = var
                    ttk.Checkbutton(
                        check_body,
                        text=f"{name or rid}  ({rid})",
                        variable=var,
                    ).pack(anchor="w", pady=4)

                if not current_regions:
                    ttk.Label(
                        check_body,
                        text="등록된 지역이 없습니다.",
                    ).pack(anchor="w", pady=6)

            except Exception as exc:
                messagebox.showerror(
                    "지역 조회 오류",
                    str(exc),
                    parent=win,
                )

        def add_region():
            rid = new_id.get().strip()
            name = new_name.get().strip()

            if not rid:
                messagebox.showinfo(
                    "지역 등록",
                    "지역 코드를 입력해주세요.",
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
                new_id.set("")
                new_name.set("")
                load_all()
                messagebox.showinfo(
                    "지역 등록",
                    f"{name} ({rid}) 지역이 등록되었습니다.\n\n"
                    f"업로드할 DXF 파일명은 정확히 {rid}.dxf 이어야 합니다.",
                    parent=win,
                )
            except Exception as exc:
                messagebox.showerror(
                    "지역 등록 오류",
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
                self.client.set_user_regions(user_id, selected)
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

        ttk.Button(
            add_box,
            text="지역 추가",
            command=add_region,
        ).grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(8, 0),
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
            text="선택 사용자 권한 저장",
            command=save_permissions,
        ).pack(side="right")
        ttk.Button(
            footer,
            text="닫기",
            command=win.destroy,
        ).pack(side="right", padx=(0, 6))

        load_all()

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
