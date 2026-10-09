from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://192.168.246.54:8443"


def resource_path(name):
    root = getattr(sys, "_MEIPASS", None)
    return os.path.join(root, name) if root else str(Path(__file__).resolve().with_name(name))


class ServerError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class CMBServerClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip("/")
        ca = resource_path("cmb_dev_ca.crt")
        self.ssl_context = (
            ssl.create_default_context(cafile=ca)
            if os.path.exists(ca)
            else ssl.create_default_context()
        )
        self.access_token = ""
        self.refresh_token = ""

    @property
    def authenticated(self):
        return bool(self.access_token)

    def _raw_request(self, method, path, payload=None, auth=True):
        body = None
        headers = {"Accept": "application/json"}

        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        if auth:
            if not self.access_token:
                raise ServerError("로그인이 필요합니다.", status=401)
            headers["Authorization"] = "Bearer " + self.access_token

        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(detail)
                detail = parsed.get("detail") or detail
            except Exception:
                pass
            raise ServerError(f"HTTP {exc.code}: {detail or exc.reason}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            raise ServerError(f"서버 연결 실패: {exc.reason}") from exc
        except Exception as exc:
            raise ServerError(str(exc)) from exc

    def _request(self, method, path, payload=None, auth=True, retry_refresh=True):
        try:
            return self._raw_request(method, path, payload, auth=auth)
        except ServerError as exc:
            if auth and exc.status == 401 and retry_refresh and self.refresh_token:
                self.refresh()
                return self._request(method, path, payload, auth=True, retry_refresh=False)
            raise

    def health(self):
        return self._request("GET", "/health", auth=False)

    def login(self, username, password):
        tokens = self._request(
            "POST",
            "/auth/login",
            {"username": username.strip(), "password": password},
            auth=False,
        )
        self.access_token = str(tokens.get("access_token") or "")
        self.refresh_token = str(tokens.get("refresh_token") or "")
        if not self.access_token:
            raise ServerError("로그인 응답에 access_token이 없습니다.")
        return self.me()

    def refresh(self):
        if not self.refresh_token:
            raise ServerError("갱신할 로그인 세션이 없습니다.", status=401)
        tokens = self._raw_request(
            "POST",
            "/auth/refresh",
            {"refresh_token": self.refresh_token},
            auth=False,
        )
        self.access_token = str(tokens.get("access_token") or "")
        self.refresh_token = str(tokens.get("refresh_token") or self.refresh_token)
        return tokens

    def logout(self):
        try:
            if self.access_token:
                self._request("POST", "/auth/logout", retry_refresh=False)
        finally:
            self.access_token = ""
            self.refresh_token = ""

    def me(self):
        return self._request("GET", "/me")

    def regions(self):
        return self._request("GET", "/regions")

    def online_regions(self):
        return self._request("GET", "/online/regions")

    def online_layers(self, region):
        q = urllib.parse.quote(region, safe="")
        return self._request("GET", f"/online/{q}/layers")

    def online_objects(self, region, bbox, limit=5000):
        q = urllib.parse.quote(region, safe="")
        bb = urllib.parse.quote(bbox, safe=",.-")
        return self._request("GET", f"/online/{q}/objects?bbox={bb}&limit={int(limit)}")

    def upload_group(self, payload):
        try:
            return self._request("POST", "/admin/drawings/upload", payload)
        except ServerError as exc:
            # 서버 UploadPackage 스키마의 이전/현재 필드명 차이를 422 응답에 맞춰 보정한다.
            if exc.status != 422:
                raise

            msg = str(exc)
            retry = json.loads(json.dumps(payload, ensure_ascii=False))

            changed = False

            if "regional_object_id" in msg and "object_id" in str(retry.get("objects", [{}])[0] if retry.get("objects") else ""):
                for obj in retry.get("objects") or []:
                    if "object_id" in obj and "regional_object_id" not in obj:
                        obj["regional_object_id"] = obj.pop("object_id")
                        changed = True

            if "group_id" in msg and "group" in retry:
                retry["group_id"] = retry.pop("group")
                changed = True

            if not changed:
                raise

            return self._request(
                "POST",
                "/admin/drawings/upload",
                retry,
                retry_refresh=False,
            )

    def revisions(self, region):
        q = urllib.parse.quote(region, safe="")
        return self._request("GET", f"/admin/drawings/{q}/revisions")

    def restore_revision(self, region, revision_id):
        q = urllib.parse.quote(region, safe="")
        return self._request(
            "POST",
            f"/admin/drawings/{q}/revisions/{int(revision_id)}/restore",
            {},
        )

    def admin_users(self):
        return self._request("GET", "/admin/users")

    def create_user(self, username, name="", department="", level=5):
        return self._request(
            "POST",
            "/admin/users",
            {
                "username": str(username).strip(),
                "name": str(name).strip() or None,
                "department": str(department).strip() or None,
                "level": int(level),
            },
        )

    def deactivate_user(self, user_id):
        return self._request(
            "POST",
            f"/admin/users/{int(user_id)}/deactivate",
        )

    def activate_user(self, user_id):
        return self._request(
            "POST",
            f"/admin/users/{int(user_id)}/activate",
        )

    def reset_user_password(self, user_id, new_password):
        return self._request(
            "POST",
            f"/admin/users/{int(user_id)}/reset-password",
            {"new_password": str(new_password)},
        )

    def admin_regions(self):
        return self._request("GET", "/admin/regions")

    def create_region(self, region_id, name):
        return self._request(
            "POST",
            "/admin/regions",
            {
                "id": str(region_id).strip(),
                "name": str(name).strip(),
            },
        )

    def user_regions(self, user_id):
        return self._request(
            "GET",
            f"/admin/users/{int(user_id)}/regions",
        )

    def set_user_regions(self, user_id, region_ids):
        return self._request(
            "POST",
            f"/admin/users/{int(user_id)}/regions",
            {"region_ids": list(region_ids or [])},
        )

    def admin_session_timeout(self):
        return self._request("GET", "/admin/settings/session-timeout")

    def set_admin_session_timeout(self, minutes):
        return self._request(
            "POST",
            "/admin/settings/session-timeout",
            {"minutes": int(minutes)},
        )

    def session_policy(self):
        return self._request("GET", "/session/policy")

    def touch_session(self):
        return self._request("POST", "/session/activity", {})
