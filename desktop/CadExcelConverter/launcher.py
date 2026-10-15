from __future__ import annotations

import json
import os
import subprocess
import sys
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from server_client_windows import CMBServerClient
from admin_users import UserAdminWindow
from session_guard import TkIdleSessionGuard

SESSION_ENDED_EXIT_CODE = 41
KAKAO_KEY_MISSING_EXIT_CODE = 42
KAKAO_KEY_FETCH_ERROR_EXIT_CODE = 43
DEFAULT_GEOMETRY = "620x430"
ADMIN_GEOMETRY = "620x610"
SINGLE_INSTANCE_HOST = "127.0.0.1"
SINGLE_INSTANCE_PORT = 47631


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CMB 통합 도면 시스템")
        self.geometry(DEFAULT_GEOMETRY)
        self.minsize(560, 390)

        session_dir = Path(
            os.getenv("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        ) / "CMB_DXF_Viewer"
        session_dir.mkdir(parents=True, exist_ok=True)
        self.session_state_path = session_dir / f"session_{os.getpid()}.json"
        os.environ["CMB_AUTH_STATE_PATH"] = str(self.session_state_path)

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
        self.username_entry = ttk.Entry(
            self.login_frame,
            textvariable=self.username,
            width=28,
        )
        self.username_entry.grid(
            row=0, column=1, padx=(8, 14), pady=4
        )
        ttk.Label(self.login_frame, text="비밀번호").grid(row=1, column=0, sticky="w")
        self.password_entry = ttk.Entry(
            self.login_frame,
            textvariable=self.password,
            show="*",
            width=28,
        )
        self.password_entry.grid(row=1, column=1, padx=(8, 14), pady=4)
        self.password_entry.bind("<Return>", lambda e: self.login())

        self.login_btn = ttk.Button(
            self.login_frame,
            text="로그인",
            command=self.login,
            width=12,
        )
        self.login_btn.grid(row=0, column=2, rowspan=2, sticky="ns")

        self.logout_btn = ttk.Button(
            self.login_frame,
            text="로그아웃",
            command=self.logout,
            width=12,
        )
        self.logout_btn.grid(row=0, column=3, rowspan=2, sticky="ns", padx=(6, 0))
        self.logout_btn.grid_remove()

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
            state="normal",
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

    def start_single_instance_listener(self, server_socket):
        self._single_instance_socket = server_socket

        def listen():
            while True:
                try:
                    conn, _addr = server_socket.accept()
                except OSError:
                    return
                try:
                    data = conn.recv(64)
                    if data.startswith(b"ACTIVATE"):
                        self.after(0, self._activate_existing_instance)
                except Exception:
                    pass
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass

        threading.Thread(target=listen, daemon=True).start()

    def _activate_existing_instance(self):
        self._restore_launcher()
        try:
            self.attributes("-topmost", True)
            self.after(180, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    def login(self):
        username = self.username.get().strip()
        password = self.password.get()
        if not username or not password:
            messagebox.showinfo("로그인", "아이디와 비밀번호를 입력해주세요.", parent=self)
            return
        try:
            user = self.client.login(username, password)
            if password == "cmb15443434":
                self._force_password_change(password)
                return
            self.user = user
            self.password.set("")
            level = int(user.get("level", 5))
            name = user.get("name") or user.get("username") or username
            self.login_status.set(f"{name} · {level}등급 로그인")
            self.username_entry.configure(state="disabled")
            self.password_entry.configure(state="disabled")
            self.login_btn.configure(state="disabled")
            self.logout_btn.grid()

            self.online_btn.configure(state="normal")
            self.map_btn.configure(state="normal")
            if level == 1:
                self.admin_btn.configure(state="normal")
                self.admin_btn.pack(fill="x", ipady=7, pady=4)
                self.geometry(ADMIN_GEOMETRY)
            else:
                self.admin_btn.pack_forget()
                self.geometry(DEFAULT_GEOMETRY)

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
            self.username_entry.configure(state="normal")
            self.password_entry.configure(state="normal")
            self.login_btn.configure(state="normal")
            self.logout_btn.grid_remove()
            self.online_btn.configure(state="disabled")
            self.map_btn.configure(state="normal")
            self.admin_btn.configure(state="disabled")

            msg = str(exc)
            status = getattr(exc, "status", None)
            upper = msg.upper()
            if "ACCOUNT_DISABLED" in upper or "사용 정지" in msg or "비활성" in msg:
                display_msg = "사용 정지된 계정입니다. 관리자에게 문의해주세요."
                self.login_status.set("사용 정지 계정 · 관리자 문의")
            elif status == 401:
                display_msg = "아이디 또는 비밀번호를 확인해주세요."
                self.login_status.set("로그인 실패 · 아이디/비밀번호 확인")
            else:
                display_msg = msg
                self.login_status.set("로그인 오류")
            messagebox.showerror("로그인 오류", display_msg, parent=self)

    def _force_password_change(self, current_password):
        win = tk.Toplevel(self)
        win.title("비밀번호 변경 필수")
        win.geometry("460x340")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        win.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(win, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text=(
                "최초 비밀번호는 cmb15443434 입니다.\n"
                "암호를 변경하고 사용하세요.\n\n"
                "비밀번호 규칙\n"
                "• 10자 이상\n"
                "• 초기 비밀번호(cmb15443434)와 다르게 설정\n"
                "• 새 비밀번호와 확인 값이 서로 일치해야 함"
            ),
            justify="left",
        ).pack(anchor="w", pady=(0, 14))

        p1 = tk.StringVar()
        p2 = tk.StringVar()
        ttk.Label(frame, text="새 비밀번호").pack(anchor="w")
        e1 = ttk.Entry(frame, textvariable=p1, show="*")
        e1.pack(fill="x", pady=(2, 8))
        ttk.Label(frame, text="새 비밀번호 확인").pack(anchor="w")
        e2 = ttk.Entry(frame, textvariable=p2, show="*")
        e2.pack(fill="x", pady=(2, 12))

        status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=status).pack(anchor="w")

        def apply_change():
            new_password = p1.get()
            if len(new_password) < 10:
                status.set("새 비밀번호는 10자 이상으로 입력해주세요.")
                return
            if new_password == "cmb15443434":
                status.set("초기 비밀번호와 다른 비밀번호를 사용해주세요.")
                return
            if new_password != p2.get():
                status.set("새 비밀번호 확인이 일치하지 않습니다.")
                return
            try:
                self.client.change_password(current_password, new_password)
                try:
                    self.client.logout()
                except Exception:
                    pass
                win.destroy()
                self._reset_login_state("비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요.")
                messagebox.showinfo(
                    "비밀번호 변경 완료",
                    "비밀번호가 변경되었습니다.\n새 비밀번호로 다시 로그인해주세요.",
                    parent=self,
                )
            except Exception as exc:
                msg = str(exc)
                if getattr(exc, "status", None) == 404:
                    status.set("비밀번호 변경 API 연결 오류입니다. 서버 프록시 설정을 확인해주세요.")
                else:
                    status.set(msg)

        ttk.Button(frame, text="비밀번호 변경", command=apply_change).pack(fill="x", pady=(8, 0))
        self.password.set("")
        self.login_status.set("비밀번호 변경이 필요합니다.")
        win.wait_window()

    def logout(self):
        try:
            if self.client.authenticated:
                self.client.logout()
        except Exception:
            pass
        self._reset_login_state("로그아웃되었습니다. 다시 로그인해주세요.")

    def _child_env(self):
        env = os.environ.copy()
        env["CMB_AUTH_ACCESS"] = self.client.access_token
        env["CMB_AUTH_REFRESH"] = self.client.refresh_token
        env["CMB_AUTH_USER"] = json.dumps(self.user or {}, ensure_ascii=False)
        env["CMB_AUTH_STATE_PATH"] = str(self.session_state_path)
        return env

    def _reset_login_state(self, message="로그인이 필요합니다."):
        self.user = None
        self.client.access_token = ""
        self.client.refresh_token = ""
        try:
            self.client.clear_shared_state()
        except Exception:
            pass
        self.password.set("")
        self.login_status.set(message)
        self.username_entry.configure(state="normal")
        self.password_entry.configure(state="normal")
        self.login_btn.configure(state="normal")
        self.logout_btn.grid_remove()
        self.online_btn.configure(state="disabled")
        self.map_btn.configure(state="disabled")
        self.admin_btn.configure(state="disabled")
        self.admin_btn.pack_forget()
        self.geometry(DEFAULT_GEOMETRY)
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
        elif code == KAKAO_KEY_MISSING_EXIT_CODE:
            if self.session_guard is not None:
                self.session_guard.resume()
            self._restore_launcher()
            messagebox.showerror(
                "온라인 뷰어",
                "Kakao 지도 JavaScript 키가 서버에 설정되어 있지 않습니다.\n"
                "관리자에게 서버 KAKAO_JS_APP_KEY 설정을 확인해주세요.",
                parent=self,
            )
            return
        elif code == KAKAO_KEY_FETCH_ERROR_EXIT_CODE:
            if self.session_guard is not None:
                self.session_guard.resume()
            self._restore_launcher()
            detail = "서버에서 Kakao 지도 키를 가져오지 못했습니다."
            try:
                error_path = Path(
                    os.getenv("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
                ) / "CMB_DXF_Viewer" / "online_start_error.txt"
                if error_path.exists():
                    raw = error_path.read_text(encoding="utf-8").strip()
                    if raw:
                        detail += "\n\n" + raw
            except Exception:
                pass
            messagebox.showerror("온라인 뷰어", detail, parent=self)
            return
        elif self.session_guard is not None:
            self.session_guard.resume()
        self._restore_launcher()

    def _spawn(self, flag, verify_server=True):
        # 자식 Viewer가 실행되는 동안 숨겨진 Launcher의 idle/session timer는 항상 중지한다.
        # map-viewer는 서버 검증만 생략할 뿐, 부모의 백그라운드 세션 통신까지 계속 돌리면 안 된다.
        if self.session_guard is not None:
            self.session_guard.pause()

        try:
            if verify_server:
                # 온라인 Viewer만 시작 직전에 서버 세션을 검증한다.
                verified = self.client.me()
                if isinstance(verified, dict):
                    self.user = verified
            env = self._child_env()
        except Exception as exc:
            if getattr(exc, "status", None) == 401:
                # An expired/revoked server session must not leave the launcher
                # displaying a logged-in user with disabled login controls.
                self._reset_login_state("서버 세션이 종료되었습니다. 다시 로그인해주세요.")
                self._restore_launcher()
                return None
            if self.session_guard is not None:
                self.session_guard.resume()
            raise

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, flag]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve().with_name("main.py")), flag]

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
        try:
            # 서버 로그인/health/me 조회 없이 로컬 DXF Viewer를 즉시 실행한다.
            self._spawn("--map-viewer", verify_server=False)
        except Exception as exc:
            messagebox.showerror("맵추출 뷰어", str(exc), parent=self)

    def open_admin(self):
        if not self.user or int(self.user.get("level", 5)) != 1:
            return

        # 관리자 창은 같은 서버 세션을 사용한다.
        # 본인 단말 초기화 직후 숨겨진 런처 heartbeat가 기존 PC를 다시 등록하지 않도록
        # 관리자 창이 열려 있는 동안 런처 idle/session guard는 중지한다.
        if self.session_guard is not None:
            self.session_guard.pause()

        self.withdraw()
        window = UserAdminWindow(
            self,
            client=self.client,
            current_user=self.user,
        )

        def restore(event=None):
            if event is not None and event.widget is not window:
                return
            if self.user is not None and self.session_guard is not None:
                self.session_guard.resume()
            self._restore_launcher()

        window.bind("<Destroy>", restore, add="+")
