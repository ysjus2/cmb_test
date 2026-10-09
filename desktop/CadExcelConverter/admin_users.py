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

        self.reset_btn = ttk.Button(
            tools, text="비밀번호 초기화", command=self.reset_password, state="disabled"
        )
        self.reset_btn.pack(side="left", padx=(6, 0))

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
                self.reset_btn.configure(state="disabled")
                return
            self.current_user = user
            self.login_status.set(
                f"{user.get('name') or user.get('username')} · 1등급 관리자"
            )
            self.lookup_btn.configure(state="normal")
            self.reset_btn.configure(state="normal")
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

    def reset_password(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("비밀번호 초기화", "사용자를 선택해주세요.", parent=self)
            return

        user = self.users[int(selected[0])]
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
            self.client.reset_user_password(username, p1)
            self.status.set(f"{username} 비밀번호 초기화 완료")
            messagebox.showinfo(
                "비밀번호 초기화",
                f"{username} 사용자의 비밀번호가 초기화되었습니다.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("비밀번호 초기화 오류", str(exc), parent=self)
