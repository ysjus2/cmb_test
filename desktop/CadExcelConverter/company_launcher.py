from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from server_client import BASE_URL, CMBServerClient, ServerError

APP_NAME = "CMB Network PC"
DEFAULT_LEVEL = 5

def _extract_level(me):
    if not isinstance(me, dict):
        return DEFAULT_LEVEL
    candidates = [
        me.get("level"), me.get("role_level"), me.get("permission_level"),
        me.get("grade"), me.get("user_level")
    ]
    user = me.get("user")
    if isinstance(user, dict):
        candidates += [
            user.get("level"), user.get("role_level"),
            user.get("permission_level"), user.get("grade")
        ]
    for value in candidates:
        try:
            n = int(value)
            if 1 <= n <= 5:
                return n
        except Exception:
            pass
    return DEFAULT_LEVEL

def _display_name(me, fallback):
    if not isinstance(me, dict):
        return fallback
    for key in ("name", "username", "display_name"):
        value = me.get(key)
        if value:
            return str(value)
    user = me.get("user")
    if isinstance(user, dict):
        for key in ("name", "username", "display_name"):
            value = user.get(key)
            if value:
                return str(value)
    return fallback

class LoginDialog(tk.Tk):
    def __init__(self):
        super().__init__()
        self.client = CMBServerClient()
        self.result = None
        self.title(APP_NAME + " 로그인")
        self.geometry("430x300")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._build()

    def _build(self):
        root = ttk.Frame(self, padding=24)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="CMB Network", font=("Malgun Gothic", 20, "bold")).pack(anchor="w")
        ttk.Label(root, text=BASE_URL, foreground="#555").pack(anchor="w", pady=(0, 18))

        form = ttk.Frame(root)
        form.pack(fill="x")
        ttk.Label(form, text="아이디", width=10).grid(row=0, column=0, sticky="w", pady=6)
        self.user = ttk.Entry(form)
        self.user.grid(row=0, column=1, sticky="ew", pady=6)
        ttk.Label(form, text="비밀번호", width=10).grid(row=1, column=0, sticky="w", pady=6)
        self.password = ttk.Entry(form, show="*")
        self.password.grid(row=1, column=1, sticky="ew", pady=6)
        form.columnconfigure(1, weight=1)

        self.status = tk.StringVar(value="회사 서버에 로그인해 주세요.")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", pady=(12, 8))
        self.login_btn = ttk.Button(root, text="로그인", command=self._login)
        self.login_btn.pack(fill="x", ipady=5)
        self.bind("<Return>", lambda e: self._login())
        self.user.focus_set()

    def _login(self):
        username = self.user.get().strip()
        password = self.password.get()
        if not username or not password:
            messagebox.showwarning(APP_NAME, "아이디와 비밀번호를 입력해 주세요.", parent=self)
            return
        self.login_btn.config(state="disabled")
        self.status.set("서버 확인 중...")
        self.update_idletasks()
        try:
            self.client.health()
            self.client.login(username, password)
            me = self.client.me()
            level = _extract_level(me)
            self.result = (self.client, level, _display_name(me, username), me)
            self.destroy()
        except Exception as exc:
            self.status.set("로그인 실패")
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            self.login_btn.config(state="normal")


class UserRegistrationDialog(tk.Toplevel):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self.title("사용자 등록")
        self.geometry("470x360")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self._build()

    def _build(self):
        root = ttk.Frame(self, padding=22)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="사용자 등록", font=("Malgun Gothic", 17, "bold")).pack(anchor="w")
        ttk.Label(root, text="1등급 관리자 전용", foreground="#666").pack(anchor="w", pady=(0, 16))

        form = ttk.Frame(root)
        form.pack(fill="x")

        ttk.Label(form, text="이름 *", width=12).grid(row=0, column=0, sticky="w", pady=7)
        self.name = ttk.Entry(form)
        self.name.grid(row=0, column=1, sticky="ew", pady=7)

        ttk.Label(form, text="아이디 *", width=12).grid(row=1, column=0, sticky="w", pady=7)
        self.username = ttk.Entry(form)
        self.username.grid(row=1, column=1, sticky="ew", pady=7)

        ttk.Label(form, text="부서 *", width=12).grid(row=2, column=0, sticky="w", pady=7)
        self.department = ttk.Entry(form)
        self.department.grid(row=2, column=1, sticky="ew", pady=7)

        ttk.Label(form, text="등급", width=12).grid(row=3, column=0, sticky="w", pady=7)
        self.level = ttk.Combobox(form, state="readonly", values=["", "1", "2", "3", "4", "5"])
        self.level.grid(row=3, column=1, sticky="ew", pady=7)
        self.level.current(0)

        form.columnconfigure(1, weight=1)

        ttk.Label(
            root,
            text="등급을 지정하지 않으면 서버 기본값을 사용합니다.",
            foreground="#666"
        ).pack(anchor="w", pady=(8, 14))

        row = ttk.Frame(root)
        row.pack(fill="x")
        ttk.Button(row, text="취소", command=self.destroy).pack(side="right")
        self.save_btn = ttk.Button(row, text="등록", command=self._save)
        self.save_btn.pack(side="right", padx=(0, 8))

        self.name.focus_set()

    def _save(self):
        name = self.name.get().strip()
        username = self.username.get().strip()
        department = self.department.get().strip()
        level_text = self.level.get().strip()

        if not name:
            messagebox.showwarning(APP_NAME, "이름을 입력해 주세요.", parent=self)
            return
        if not username:
            messagebox.showwarning(APP_NAME, "아이디를 입력해 주세요.", parent=self)
            return
        if not department:
            messagebox.showwarning(APP_NAME, "부서를 입력해 주세요.", parent=self)
            return

        level = None
        if level_text:
            try:
                level = int(level_text)
            except ValueError:
                messagebox.showwarning(APP_NAME, "등급은 1~5만 사용할 수 있습니다.", parent=self)
                return
            if level < 1 or level > 5:
                messagebox.showwarning(APP_NAME, "등급은 1~5만 사용할 수 있습니다.", parent=self)
                return

        self.save_btn.config(state="disabled")
        self.update_idletasks()
        try:
            result = self.client.create_user(name, username, department, level)
            temporary_password = ""
            if isinstance(result, dict):
                temporary_password = str(result.get("temporary_password") or "")

            if temporary_password:
                self.clipboard_clear()
                self.clipboard_append(temporary_password)
                messagebox.showinfo(
                    APP_NAME,
                    "사용자 등록이 완료되었습니다.\n\n"
                    f"이름: {name}\n"
                    f"아이디: {username}\n"
                    f"부서: {department}\n"
                    f"등급: {result.get('level', level or 5)}\n\n"
                    f"임시 비밀번호: {temporary_password}\n\n"
                    "임시 비밀번호를 클립보드에 복사했습니다. "
                    "이 창을 닫기 전에 사용자에게 전달해 주세요.",
                    parent=self
                )
            else:
                messagebox.showwarning(
                    APP_NAME,
                    "사용자는 등록되었지만 서버가 임시 비밀번호를 반환하지 않았습니다.",
                    parent=self
                )
            self.destroy()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self)
            self.save_btn.config(state="normal")


class ServerBrowser(tk.Toplevel):
    def __init__(self, master, client):
        super().__init__(master)
        self.client = client
        self.title("서버 지도/데이터")
        self.geometry("1100x720")
        self.regions_data = []
        self.datasets_data = []
        self.object_rows = {}
        self._build()
        self._load_regions()

    def _build(self):
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="지역").pack(side="left")
        self.region = ttk.Combobox(bar, state="readonly", width=35)
        self.region.pack(side="left", padx=6)
        self.region.bind("<<ComboboxSelected>>", lambda e: self._load_datasets())
        ttk.Label(bar, text="데이터셋").pack(side="left", padx=(12, 0))
        self.dataset = ttk.Combobox(bar, state="readonly", width=42)
        self.dataset.pack(side="left", padx=6)
        self.dataset.bind("<<ComboboxSelected>>", lambda e: self._load_dataset())

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=3)

        self.layers = ttk.Treeview(left, columns=("name","count"), show="headings")
        self.layers.heading("name", text="레이어")
        self.layers.heading("count", text="객체수")
        self.layers.column("name", width=260)
        self.layers.column("count", width=90, anchor="center")
        self.layers.pack(fill="both", expand=True)

        self.objects = ttk.Treeview(right, columns=("type","name","detail"), show="headings")
        for c,t,w in (("type","종류",120),("name","이름/ID",220),("detail","상세",430)):
            self.objects.heading(c,text=t); self.objects.column(c,width=w)
        self.objects.pack(fill="both", expand=True)
        self.objects.bind("<Double-1>", self._show_object)

        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, padding=(8,4)).pack(fill="x")

    @staticmethod
    def _items(data):
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items","regions","datasets","layers","objects","data","results"):
                value=data.get(key)
                if isinstance(value,list):
                    return value
        return []

    @staticmethod
    def _id(item):
        if not isinstance(item,dict): return item
        for k in ("id","region_id","dataset_id","uuid"):
            if item.get(k) is not None: return item.get(k)
        return None

    @staticmethod
    def _name(item):
        if not isinstance(item,dict): return str(item)
        for k in ("name","title","label","code","id"):
            if item.get(k) not in (None,""): return str(item.get(k))
        return "(이름 없음)"

    def _load_regions(self):
        try:
            self.regions_data=self._items(self.client.regions())
            self.region["values"]=[self._name(x) for x in self.regions_data]
            if self.regions_data:
                self.region.current(0); self._load_datasets()
            self.status.set(f"지역 {len(self.regions_data)}개")
        except Exception as exc:
            messagebox.showerror(APP_NAME,str(exc),parent=self)

    def _load_datasets(self):
        i=self.region.current()
        if i<0:return
        rid=self._id(self.regions_data[i])
        try:
            self.datasets_data=self._items(self.client.region_datasets(rid))
            self.dataset["values"]=[self._name(x) for x in self.datasets_data]
            if self.datasets_data:
                self.dataset.current(0); self._load_dataset()
            else:
                self.layers.delete(*self.layers.get_children())
                self.objects.delete(*self.objects.get_children())
        except Exception as exc:
            messagebox.showerror(APP_NAME,str(exc),parent=self)

    def _load_dataset(self):
        i=self.dataset.current()
        if i<0:return
        did=self._id(self.datasets_data[i])
        try:
            layers=self._items(self.client.dataset_layers(did))
            objects=self._items(self.client.dataset_objects(did))
            self.layers.delete(*self.layers.get_children())
            for x in layers:
                count=""
                if isinstance(x,dict):
                    count=x.get("count",x.get("object_count",""))
                self.layers.insert("","end",values=(self._name(x),count))
            self.objects.delete(*self.objects.get_children())
            self.object_rows.clear()
            for idx,x in enumerate(objects):
                if isinstance(x,dict):
                    typ=str(x.get("type",x.get("category",x.get("layer",""))))
                    name=str(x.get("name",x.get("id",x.get("object_id",""))))
                    detail=", ".join(f"{k}={v}" for k,v in list(x.items())[:6] if v not in (None,""))
                else:
                    typ="";name=str(x);detail=""
                iid=f"O{idx}"
                self.object_rows[iid]=x
                self.objects.insert("","end",iid=iid,values=(typ,name,detail))
            self.status.set(f"레이어 {len(layers)}개 · 객체 {len(objects)}개")
        except Exception as exc:
            messagebox.showerror(APP_NAME,str(exc),parent=self)

    def _show_object(self,event=None):
        sel=self.objects.selection()
        if not sel:return
        obj=self.object_rows.get(sel[0])
        if obj is None:
            return
        try:
            text=json.dumps(obj,ensure_ascii=False,indent=2,default=str)
        except Exception:
            text=str(obj)
        messagebox.showinfo("객체 상세",text,parent=self)

class Portal(tk.Tk):
    def __init__(self, client, level, username, me):
        super().__init__()
        self.client=client
        self.level=level
        self.username=username
        self.me=me
        self.title(APP_NAME)
        self.geometry("720x430")
        self._build()

    def _build(self):
        root=ttk.Frame(self,padding=24)
        root.pack(fill="both",expand=True)
        ttk.Label(root,text="CMB Network PC",font=("Malgun Gothic",22,"bold")).pack(anchor="w")
        ttk.Label(root,text=f"{self.username} · 권한 {self.level}등급 · {BASE_URL}").pack(anchor="w",pady=(4,22))

        ttk.Button(root,text="서버 지도 / 데이터 보기",command=lambda:ServerBrowser(self,self.client)).pack(fill="x",ipady=9,pady=5)

        if self.level <= 3:
            ttk.Button(root,text="로컬 DXF 열기 / Excel 변환",command=self._open_dxf).pack(fill="x",ipady=9,pady=5)

        if self.level == 1:
            ttk.Separator(root).pack(fill="x",pady=16)
            ttk.Label(root,text="관리자 기능",font=("Malgun Gothic",12,"bold")).pack(anchor="w")
            ttk.Button(
                root,
                text="사용자 등록",
                command=lambda: UserRegistrationDialog(self, self.client)
            ).pack(fill="x", ipady=7, pady=(8, 4))
            ttk.Label(
                root,
                text="서버 업로드/수정 기능은 서버 API 준비 후 이 영역에만 추가됩니다.",
                foreground="#555"
            ).pack(anchor="w",pady=(4,0))

        ttk.Label(root,text="권한이 없는 기능은 화면에 표시되지 않습니다.",foreground="#666").pack(side="bottom",anchor="w")

    def _open_dxf(self):
        self.destroy()
        from main import App
        App().mainloop()

def run():
    login=LoginDialog()
    login.mainloop()
    if not login.result:
        return
    client, level, username, me=login.result
    Portal(client,level,username,me).mainloop()

if __name__ == "__main__":
    run()
