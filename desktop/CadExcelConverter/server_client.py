from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://192.168.246.54:8443"

class ServerError(RuntimeError):
    pass

def resource_path(name: str) -> str:
    root = getattr(sys, "_MEIPASS", None)
    if root:
        return os.path.join(root, name)
    return str(Path(__file__).resolve().with_name(name))

class CMBServerClient:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url.rstrip("/")
        ca_file = resource_path("cmb_dev_ca.crt")
        self.ssl_context = ssl.create_default_context(cafile=ca_file)
        self.access_token = None
        self.refresh_token = None

    def _request(self, method: str, path: str, payload=None, auth: bool = True):
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = ""
            raise ServerError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise ServerError(f"서버 연결 실패: {reason}") from exc
        except ssl.SSLError as exc:
            raise ServerError(f"TLS 인증서 검증 실패: {exc}") from exc

    def health(self):
        return self._request("GET", "/health", auth=False)

    def login(self, username: str, password: str):
        data = self._request(
            "POST",
            "/auth/login",
            {"username": username, "password": password},
            auth=False,
        )
        if not isinstance(data, dict) or not data.get("access_token"):
            raise ServerError("로그인 응답에 access_token이 없습니다.")
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        return data

    def me(self):
        return self._request("GET", "/me")

    def regions(self):
        return self._request("GET", "/regions")

    def region_datasets(self, region_id):
        return self._request("GET", f"/regions/{region_id}/datasets")

    def dataset_layers(self, dataset_id):
        return self._request("GET", f"/datasets/{dataset_id}/layers")

    def dataset_objects(self, dataset_id):
        return self._request("GET", f"/datasets/{dataset_id}/objects")
