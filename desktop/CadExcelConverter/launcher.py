from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from server_client_windows import CMBServerClient
from admin_users import UserAdminWindow
from session_guard import TkIdleSessionGuard

SESSION_ENDED_EXIT_CODE = 41


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CMB 통합 도면 시스템")
        self.geometry("620x430")
        self.minsize(560, 390)

        self.client = CMBServerClient()
        self.user = None
        self.session_guard = None

        root = ttk.Frame(self, padding=24)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="CMB 통합 도면 시스템",
            font=("Malgun Gothic", 20, "bold"),
        ).pack(anchor="center", pady=(10, 4))
        ttk.Label(
            root,
            text="로그인 후 권한에 따라 사용할 기능이 활성화됩니다.",
        ).pack(anchor="center", pady=(0, 20))

        self.login_frame = ttk.LabelFrame(root, text="로그인", padding=14)
        self.login_frame.pack(fill="x")

        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.login_status = tk.StringVar(value="로그인이 필요합니다.")

        ttk.Label(self.login_frame, text="아이디").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.login_frame, textvariable=self.username, width=28).grid(
            row=0, column=1, padx=(8, 14), pady=4
        )
        ttk.Label(self.login_frame, text="비밀번호").grid(row=1, column=0, sticky="w")
        pw = ttk.Entry(
            self.login_frame,
            textvariable=self.password,
            show="*",
            width=28,
        )
        pw.grid(row=1, column=1, padx=(8, 14), pady=4)
        pw.bind("<Return>", lambda e: self.login())

        self.login_btn = ttk.Button(
            self.login_frame,
            text="로그인",
            command=self.login,
            width=12,
        )
        self.login_btn.grid(row=0, column=2, rowspan=2, sticky="ns")
        ttk.Label(
            self.login_frame,
            textvariable=self.login_status,
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.mode_frame = ttk.LabelFrame(root, text="실행 모드", padding=14)
        self.mode_frame.pack(fill="both", expand=True, pady=(16, 0))

        self.online_btn = ttk.Button(
            self.mode_frame,
            text="온라인 뷰어",
            command=self.open_online,
            state="disabled",
        )
        self.online_btn.pack(fill="x", ipady=7, pady=4)

        self.map_btn = ttk.Button(
            self.mode_frame,
            text="맵추출 뷰어",
            command=self.open_map_viewer,
            state="disabled",
        )
        self.map_btn.pack(fill="x", ipady=7, pady=4)

        self.admin_btn = ttk.Button(
            self.mode_frame,
            text="관리자 전용",
            command=self.open_admin,
            state="disabled",
        )
        # 관리자 버튼은 로그인 전/일반 계정에는 아예 표시하지 않는다.
        self.admin_btn.pack_forget()

        self.mode_note = tk.StringVar(value="")
        ttk.Label(
            self.mode_frame,
            textvariable=self.mode_note,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

    def login(self):
        username = self.username.get().strip()
        password = self.password.get()
        if not username or not password:
            messagebox.showinfo("로그인", "아이디와 비밀번호를 입력해주세요.", parent=self)
            return
        try:
            user = self.client.login(username, password)
            self.user = user
            self.password.set("")
            level = int(user.get("level", 5))
            name = user.get("name") or user.get("username") or username
            self.login_status.set(f"{name} · {level}등급 로그인")

            self.online_btn.configure(state="normal")
            self.map_btn.configure(state="normal")
            if level == 1:
                self.admin_btn.configure(state="normal")
                self.admin_btn.pack(fill="x", ipady=7, pady=4)
            else:
                self.admin_btn.pack_forget()

            if level <= 3:
                map_note = "도면 보기 + 추출/Excel 기능"
            else:
                map_note = "도면 보기 전용"

            self.mode_note.set(
                f"온라인 뷰어: 사용 가능\n"
                f"맵추출 뷰어: {map_note}\n"
                f"관리자 전용: {'사용 가능' if level == 1 else '1등급 관리자만 사용'}"
            )
            self.session_guard = TkIdleSessionGuard(
                self,
                self._session_expired,
                client=self.client,
            )
        except Exception as exc:
            self.user = None
            self.online_btn.configure(state="disabled")
            self.map_btn.configure(state="disabled")
            self.admin_btn.configure(state="disabled")
            messagebox.showerror("로그인 오류", str(exc), parent=self)

    def _child_env(self):
        env = os.environ.copy()
        env["CMB_AUTH_ACCESS"] = self.client.access_token
        env["CMB_AUTH_REFRESH"] = self.client.refresh_token
        env["CMB_AUTH_USER"] = json.dumps(self.user or {}, ensure_ascii=False)
        return env

    def _reset_login_state(self, message="로그인이 필요합니다."):
        self.user = None
        self.client.access_token = ""
        self.client.refresh_token = ""
        self.password.set("")
        self.login_status.set(message)
        self.online_btn.configure(state="disabled")
        self.map_btn.configure(state="disabled")
        self.admin_btn.configure(state="disabled")
        self.admin_btn.pack_forget()
        self.mode_note.set("")
        self.session_guard = None

    def _session_expired(self):
        self._reset_login_state("세션이 종료되었습니다. 다시 로그인해주세요.")
        self._restore_launcher()

    def _restore_launcher(self):
        if not self.winfo_exists():
            return
        self.deiconify()
        self.lift()
        try:
            self.focus_force()
        except Exception:
            pass

    def _watch_child(self, process):
        code = process.poll()
        if code is None:
            self.after(300, lambda: self._watch_child(process))
            return
        if code == SESSION_ENDED_EXIT_CODE:
            self._reset_login_state("세션이 종료되었습니다. 다시 로그인해주세요.")
        elif self.session_guard is not None:
            self.session_guard.resume()
        self._restore_launcher()

    def _spawn(self, flag):
        env = self._child_env()
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, flag]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve().with_name("main.py")), flag]

        if self.session_guard is not None:
            self.session_guard.pause()
        process = subprocess.Popen(cmd, env=env)
        self.withdraw()
        self.after(300, lambda: self._watch_child(process))
        return process

    def open_online(self):
        if not self.user:
            return
        try:
            self._spawn("--online-viewer")
        except Exception as exc:
            messagebox.showerror("온라인 뷰어", str(exc), parent=self)

    def open_map_viewer(self):
        if not self.user:
            return
        try:
            self._spawn("--map-viewer")
        except Exception as exc:
            messagebox.showerror("맵추출 뷰어", str(exc), parent=self)

    def open_admin(self):
        if not self.user or int(self.user.get("level", 5)) != 1:
            return

        self.withdraw()
        window = UserAdminWindow(
            self,
            client=self.client,
            current_user=self.user,
        )

        def restore(event=None):
            if event is not None and event.widget is not window:
                return
            self._restore_launcher()

        window.bind("<Destroy>", restore, add="+")
