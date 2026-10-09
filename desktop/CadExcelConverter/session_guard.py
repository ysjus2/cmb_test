from __future__ import annotations

import os
import threading
import time

from server_client_windows import CMBServerClient


class TkIdleSessionGuard:
    def __init__(self, root, on_expired, client=None, default_minutes=10):
        self.root = root
        self.on_expired = on_expired
        self.client = client or CMBServerClient()
        if client is None:
            self.client.access_token = os.getenv("CMB_AUTH_ACCESS", "").strip()
            self.client.refresh_token = os.getenv("CMB_AUTH_REFRESH", "").strip()

        self.idle_minutes = int(default_minutes)
        self.last_activity = time.monotonic()
        self.last_server_touch = 0.0
        self.enabled = True
        self.expired = False

        try:
            policy = self.client.session_policy() or {}
            self.idle_minutes = max(1, int(policy.get("idle_minutes", default_minutes)))
        except Exception:
            self.idle_minutes = int(default_minutes)

        for event in (
            "<ButtonPress>",
            "<ButtonRelease>",
            "<KeyPress>",
            "<MouseWheel>",
            "<Motion>",
        ):
            root.bind_all(event, self._activity, add="+")
        root.after(5000, self._check)

    def _activity(self, event=None):
        if not self.enabled or self.expired:
            return
        now = time.monotonic()
        self.last_activity = now
        if now - self.last_server_touch >= 30:
            self.last_server_touch = now
            threading.Thread(target=self._touch_server, daemon=True).start()

    def _touch_server(self):
        try:
            self.client.touch_session()
        except Exception:
            pass

    def pause(self):
        self.enabled = False

    def resume(self):
        self.last_activity = time.monotonic()
        self.enabled = True
        self._touch_server_async()

    def _touch_server_async(self):
        now = time.monotonic()
        self.last_server_touch = now
        threading.Thread(target=self._touch_server, daemon=True).start()

    def _check(self):
        try:
            if (
                self.enabled
                and not self.expired
                and time.monotonic() - self.last_activity >= self.idle_minutes * 60
            ):
                self.expired = True
                try:
                    self.client.logout()
                except Exception:
                    pass
                self.on_expired()
                return
        finally:
            try:
                if self.root.winfo_exists() and not self.expired:
                    self.root.after(5000, self._check)
            except Exception:
                pass
