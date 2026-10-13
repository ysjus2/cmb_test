from __future__ import annotations

import json
import hashlib
import io
import os
import ssl
import sys
import threading
import contextlib
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
        if os.path.exists(ca):
            self.ssl_context = ssl.create_default_context(cafile=ca)
        else:
            parsed = urllib.parse.urlparse(self.base_url)
            host = (parsed.hostname or "").strip().lower()
            # 개발용 내부 CMB 서버는 자체서명 인증서를 사용한다.
            # 번들 CA가 없는 개발 빌드에서만 해당 고정 사설 IP에 한해
            # 인증서 체인 검증을 생략한다. 다른 서버에는 기본 검증을 유지한다.
            if host == "192.168.246.54":
                self.ssl_context = ssl._create_unverified_context()
            else:
                self.ssl_context = ssl.create_default_context()
        self.access_token = ""
        self.refresh_token = ""
        self.on_session_expired = None
        self._refresh_lock = threading.RLock()
        self.shared_state_path = os.getenv("CMB_AUTH_STATE_PATH", "").strip()
        self._sync_from_shared_state()

    @contextlib.contextmanager
    def _shared_state_lock(self):
        path = self.shared_state_path
        if not path:
            yield
            return
        lock_path = path + ".lock"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                fh.write(b"0")
                fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            if os.name == "nt":
                try:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:
                    pass
            fh.close()

    def _sync_from_shared_state_unlocked(self):
        path = self.shared_state_path
        if not path or not os.path.isfile(path):
            return False
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            access = str(data.get("access_token") or "")
            refresh = str(data.get("refresh_token") or "")
            changed = access != self.access_token or refresh != self.refresh_token
            if access:
                self.access_token = access
            if refresh:
                self.refresh_token = refresh
            return changed
        except Exception:
            return False

    def _sync_from_shared_state(self):
        if not self.shared_state_path:
            return False
        with self._shared_state_lock():
            return self._sync_from_shared_state_unlocked()

    def _sync_to_shared_state_unlocked(self):
        path = self.shared_state_path
        if not path:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(
            target.name + f".{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temp.write_text(
            json.dumps(
                {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(str(temp), str(target))

    def _sync_to_shared_state(self):
        if not self.shared_state_path:
            return
        with self._shared_state_lock():
            self._sync_to_shared_state_unlocked()

    def clear_shared_state(self):
        path = self.shared_state_path
        if not path:
            return
        with self._shared_state_lock():
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    @property
    def authenticated(self):
        return bool(self.access_token)

    class _ProgressBody(io.BytesIO):
        def __init__(self, data, callback=None, chunk_size=256 * 1024):
            super().__init__(data)
            self._total = len(data)
            self._sent = 0
            self._callback = callback
            self._chunk_size = int(chunk_size)

        def read(self, size=-1):
            if size is None or size < 0 or size > self._chunk_size:
                size = self._chunk_size
            chunk = super().read(size)
            if chunk:
                self._sent += len(chunk)
                if callable(self._callback):
                    try:
                        self._callback(self._sent, self._total)
                    except Exception:
                        pass
            return chunk

    def _raw_json_upload(self, path, payload, progress_callback=None, timeout=None):
        self._sync_from_shared_state()
        if not self.access_token:
            raise ServerError("로그인이 필요합니다.", status=401)

        body_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        body = self._ProgressBody(body_bytes, callback=progress_callback)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body_bytes)),
            "Authorization": "Bearer " + self.access_token,
        }
        req = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=timeout) as resp:
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

    def _upload_request(self, path, payload, progress_callback=None, retry_refresh=True):
        failed_access = self.access_token
        try:
            return self._raw_json_upload(
                path,
                payload,
                progress_callback=progress_callback,
                timeout=None,
            )
        except ServerError as exc:
            if exc.status == 401 and retry_refresh and self.refresh_token:
                try:
                    with self._refresh_lock:
                        with self._shared_state_lock():
                            self._sync_from_shared_state_unlocked()
                            if self.access_token == failed_access:
                                self._refresh_locked(sync_shared=False)
                                self._sync_to_shared_state_unlocked()
                    # 토큰 갱신 후에는 전송을 처음부터 다시 시작한다.
                    if callable(progress_callback):
                        try:
                            progress_callback(0, 0)
                        except Exception:
                            pass
                    return self._upload_request(
                        path,
                        payload,
                        progress_callback=progress_callback,
                        retry_refresh=False,
                    )
                except ServerError as refresh_exc:
                    if refresh_exc.status == 401:
                        self._notify_session_expired()
                    raise
            if exc.status == 401:
                self._notify_session_expired()
            raise

    def _raw_request(self, method, path, payload=None, auth=True, timeout=60):
        body = None
        headers = {"Accept": "application/json"}

        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        if auth:
            self._sync_from_shared_state()
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
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=timeout) as resp:
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

    def _notify_session_expired(self):
        callback = self.on_session_expired
        if callable(callback):
            try:
                callback()
            except Exception:
                pass

    def _request(self, method, path, payload=None, auth=True, retry_refresh=True, timeout=60):
        failed_access = self.access_token
        try:
            return self._raw_request(method, path, payload, auth=auth, timeout=timeout)
        except ServerError as exc:
            if auth and exc.status == 401 and retry_refresh and self.refresh_token:
                try:
                    # 다른 프로세스가 이미 refresh token을 회전했을 수 있으므로
                    # 공용 세션 상태를 먼저 다시 읽고, 여전히 같은 access일 때만 refresh한다.
                    with self._refresh_lock:
                        with self._shared_state_lock():
                            self._sync_from_shared_state_unlocked()
                            if self.access_token == failed_access:
                                self._refresh_locked(sync_shared=False)
                                self._sync_to_shared_state_unlocked()
                    return self._request(
                        method,
                        path,
                        payload,
                        auth=True,
                        retry_refresh=False,
                        timeout=timeout,
                    )
                except ServerError as refresh_exc:
                    if refresh_exc.status == 401:
                        self._notify_session_expired()
                    raise
            if auth and exc.status == 401:
                self._notify_session_expired()
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
        self._sync_to_shared_state()
        if not self.access_token:
            raise ServerError("로그인 응답에 access_token이 없습니다.")
        return self.me()

    def refresh(self):
        with self._refresh_lock:
            return self._refresh_locked()

    def _refresh_locked(self, sync_shared=True):
        if not self.refresh_token:
            raise ServerError("갱신할 로그인 세션이 없습니다.", status=401)
        tokens = self._raw_request(
            "POST",
            "/auth/refresh",
            {"refresh_token": self.refresh_token},
            auth=False,
        )
        access = str(tokens.get("access_token") or "")
        if not access:
            raise ServerError("갱신 응답에 access_token이 없습니다.")
        self.access_token = access
        self.refresh_token = str(tokens.get("refresh_token") or self.refresh_token)
        if sync_shared:
            self._sync_to_shared_state()
        return tokens

    def logout(self):
        try:
            if self.access_token:
                self._request("POST", "/auth/logout", retry_refresh=False)
        finally:
            self.access_token = ""
            self.refresh_token = ""
            self.clear_shared_state()

    def me(self):
        return self._request("GET", "/me")

    def regions(self):
        return self._request("GET", "/regions")

    def online_layers(self, region):
        q = urllib.parse.quote(region, safe="")
        return self._request("GET", f"/online/{q}/layers")

    def online_versions(self, region):
        q = urllib.parse.quote(region, safe="")
        try:
            raw = self._request("GET", f"/online/{q}/versions")
            if isinstance(raw, dict):
                return {
                    str(k).upper(): str(v)
                    for k, v in raw.items()
                    if str(k).strip() and str(v).strip()
                }
        except ServerError as exc:
            if exc.status != 404:
                raise

        # 구버전 서버 호환: /online/{region}/layers 메타데이터로
        # 그룹별 서명을 만들어 캐시 무효화에 사용한다.
        info = self.online_layers(region) or {}
        rows = info.get("layers") or []
        grouped = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            group = str(row.get("group_id") or "").strip().upper()
            if not group:
                continue
            stable = {
                key: row.get(key)
                for key in (
                    "group_id", "layer", "revision", "revision_id",
                    "version", "package_sha256", "object_count",
                    "count", "updated_at",
                )
                if row.get(key) is not None
            }
            grouped.setdefault(group, []).append(stable)

        versions = {}
        for group, items in grouped.items():
            payload = json.dumps(
                sorted(items, key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False)),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            versions[group] = "meta:" + hashlib.sha256(payload).hexdigest()
        return versions

    def online_symbols(self, region):
        q = urllib.parse.quote(region, safe="")
        return self._request("GET", f"/online/{q}/symbols")

    def online_objects(self, region, bbox, limit=5000, layers=None):
        q = urllib.parse.quote(region, safe="")
        bb = urllib.parse.quote(bbox, safe=",.-")
        path = f"/online/{q}/objects?bbox={bb}&limit={int(limit)}"
        if layers:
            if isinstance(layers, (list, tuple, set)):
                layers = ",".join(str(x).strip() for x in layers if str(x).strip())
            layers = str(layers or "").strip()
            if layers:
                path += "&layers=" + urllib.parse.quote(layers, safe=",")
        return self._request("GET", path, timeout=15)

    def online_grid_objects(self, region, grid_id, limit=20000, layers=None):
        q = urllib.parse.quote(str(region).strip(), safe="")
        g = urllib.parse.quote(str(grid_id).strip().upper(), safe="")
        path = f"/online/{q}/grid/{g}/objects?limit={int(limit)}"
        if layers:
            if isinstance(layers, (list, tuple, set)):
                layers = ",".join(str(x).strip() for x in layers if str(x).strip())
            layers = str(layers or "").strip()
            if layers:
                path += "&layers=" + urllib.parse.quote(layers, safe=",")
        return self._request("GET", path, timeout=15)

    def online_polemap(self, region, west, south, east, north):
        q = urllib.parse.quote(str(region).strip(), safe="")
        query = urllib.parse.urlencode({
            "west": float(west),
            "south": float(south),
            "east": float(east),
            "north": float(north),
        })
        return self._request("GET", f"/online/{q}/polemap?{query}", timeout=10)

    def online_polemap_version(self, region):
        q = urllib.parse.quote(str(region).strip(), safe="")
        return self._request("GET", f"/online/{q}/polemap/version", timeout=10)

    def replace_polemap(self, region, payload):
        q = urllib.parse.quote(str(region).strip(), safe="")
        return self._request(
            "POST",
            f"/admin/polemap/{q}/replace",
            payload,
            timeout=None,
        )

    def group_status_v2(self, region):
        q = urllib.parse.quote(str(region).strip(), safe="")
        return self._request("GET", f"/admin/drawings/{q}/group-status-v2")

    def upload_group(self, payload, progress_callback=None):
        try:
            # 대용량 DXF 업로드/DB 교체는 전주처럼 수시간이 걸릴 수 있다.
            # 고정 timeout을 두지 않고 실제 연결 오류 또는 서버 응답까지 기다린다.
            return self._upload_request(
                "/admin/drawings/upload",
                payload,
                progress_callback=progress_callback,
            )
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

            return self._upload_request(
                "/admin/drawings/upload",
                retry,
                progress_callback=progress_callback,
                retry_refresh=False,
            )

    def drawing_symbols(self, region):
        q = urllib.parse.quote(region, safe="")
        return self._request("GET", f"/admin/drawings/{q}/symbols")

    def upload_symbols(self, region, payload, progress_callback=None):
        q = urllib.parse.quote(str(region).strip(), safe="")
        return self._upload_request(
            f"/admin/drawings/{q}/symbols",
            payload,
            progress_callback=progress_callback,
        )

    def revisions(self, region):
        q = urllib.parse.quote(region, safe="")
        rows = self._request("GET", f"/admin/drawings/{q}/revisions")
        if isinstance(rows, dict):
            base = list(rows.get("items") or rows.get("revisions") or [])
        else:
            base = list(rows or [])
        allowed = {"FIBER", "COAX", "CONDUIT", "POLE", "USER"}
        order = {"FIBER": 0, "COAX": 1, "CONDUIT": 2, "POLE": 3, "USER": 4}
        base = [
            row for row in base
            if str((row or {}).get("group_id") or "").upper() in allowed
        ]
        base.sort(key=lambda row: (
            order.get(str(row.get("group_id") or "").upper(), 999),
            0 if row.get("active") else 1,
            -int(row.get("revision") or 0),
        ))
        return base

    def restore_revision(self, region, revision_id, group_id=None):
        q = urllib.parse.quote(region, safe="")
        rid = urllib.parse.quote(str(revision_id).strip(), safe="")
        if str(group_id or "").upper() == "SYMBOL":
            return self._request(
                "POST",
                f"/admin/drawings/{q}/symbol-revisions/{rid}/restore",
                {},
            )
        return self._request(
            "POST",
            f"/admin/drawings/{q}/revisions/{rid}/restore",
            {},
        )

    def drawing_status(self, region):
        """Read-only regional drawing status for admin/view functions."""
        q = urllib.parse.quote(str(region).strip(), safe="")
        return self._request("GET", f"/admin/drawings/{q}/status")

    def force_delete_drawing_group(self, region, group_id):
        """Delete one drawing group only; keep region, permissions and other groups."""
        q = urllib.parse.quote(str(region).strip(), safe="")
        g = urllib.parse.quote(str(group_id).strip().upper(), safe="")
        return self._request("DELETE", f"/admin/drawings/{q}/groups/{g}/force")

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

    def update_region(self, region_id, name):
        q = urllib.parse.quote(str(region_id).strip(), safe="")
        return self._request(
            "PUT",
            f"/admin/regions/{q}",
            {"name": str(name).strip()},
        )

    def delete_region(self, region_id):
        q = urllib.parse.quote(str(region_id).strip(), safe="")
        return self._request(
            "DELETE",
            f"/admin/regions/{q}",
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

    def admin_backup_retention(self):
        return self._request("GET", "/admin/settings/backup-retention")

    def set_admin_backup_retention(self, count):
        return self._request(
            "POST",
            "/admin/settings/backup-retention",
            {"count": int(count)},
        )

    def map_display_settings(self):
        try:
            return self._request("GET", "/settings/map-display")
        except ServerError as exc:
            if exc.status == 404:
                return {"radius_m": 500, "refresh_distance_m": 200}
            raise

    def admin_map_display_settings(self):
        try:
            return self._request("GET", "/admin/settings/map-display")
        except ServerError as exc:
            if exc.status == 404:
                return {"radius_m": 500, "refresh_distance_m": 200}
            raise

    def set_admin_map_display_settings(self, radius_m, refresh_distance_m):
        return self._request(
            "POST",
            "/admin/settings/map-display",
            {
                "radius_m": int(radius_m),
                "refresh_distance_m": int(refresh_distance_m),
            },
        )

    def session_policy(self):
        return self._request("GET", "/session/policy")

    def touch_session(self):
        return self._request("POST", "/session/activity", {})
