from __future__ import annotations

import gzip
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from server_client_windows import CMBServerClient, ServerError

APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CMB_DXF_Viewer"
CFG = APP_DATA_DIR / "online.json"
CACHE_DIR = APP_DATA_DIR / "online_cache"
FIBER_CACHE_SCHEMA = 2
SESSION_ENDED_EXIT_CODE = 41
WINDOWS_RELEASE = "Windows_1.0_Coordinate_BBox"


def key():
    k = os.getenv("KAKAO_JS_APP_KEY", "").strip()
    if not k and CFG.exists():
        try:
            k = json.loads(CFG.read_text(encoding="utf-8")).get("kakao_js_key", "").strip()
        except Exception:
            pass
    if k:
        return k

    return ""


class Api:
    def __init__(self):
        self.c = CMBServerClient()
        self.region = ""
        self.region_generation = 0
        self.fiber_synced_regions = set()
        self.fiber_progress = {}
        self.user = None
        self.window = None
        self.session_ended = False
        self.cache_state = {"versions": {}, "features": {}, "coverage": []}
        self.fiber_cache = {"version": "", "features": []}
        # 앱 실행 세션 동안 지역별 서버 버전 확인은 최초 1회만 한다.
        self.checked_regions = set()
        self.version_check_lock = threading.Lock()
        self.cache_lock = threading.RLock()
        self.bbox_refreshing = set()
        self.fiber_bbox_refreshing = set()

        # CMBServerClient()는 먼저 CMB_AUTH_STATE_PATH의 공용 세션 파일에서
        # 최신 access/refresh token을 읽는다. 장시간 업로드 중 refresh token이
        # 회전할 수 있으므로 오래된 환경변수 값으로 최신 공용 상태를 덮어쓰지 않는다.
        if not self.c.access_token:
            self.c.access_token = os.getenv("CMB_AUTH_ACCESS", "").strip()
        if not self.c.refresh_token:
            self.c.refresh_token = os.getenv("CMB_AUTH_REFRESH", "").strip()
        self.c._sync_from_shared_state()
        self.c.on_session_expired = self.expire_session
        raw_user = os.getenv("CMB_AUTH_USER", "").strip()
        if raw_user:
            try:
                self.user = json.loads(raw_user)
            except Exception:
                self.user = None

    def _cache_path(self):
        safe = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in str(self.region or "")
        )
        return CACHE_DIR / f"{safe}.json.gz"

    @staticmethod
    def _feature_key(feature):
        props = feature.get("properties") or {}
        attrs = props.get("attributes") or {}
        fields = attrs.get("fields") if isinstance(attrs, dict) else None
        if not isinstance(fields, dict):
            fields = attrs if isinstance(attrs, dict) else {}

        group = str(props.get("group_id") or "").upper()
        source_handle = str(props.get("source_handle") or "").strip()
        regional_id = str(
            props.get("regional_object_id")
            or props.get("entity_id")
            or props.get("object_id")
            or ""
        ).strip()
        part_index = str(
            fields.get("_cmb_geometry_part_index")
            or (attrs.get("_cmb_geometry_part_index") if isinstance(attrs, dict) else "")
            or ""
        ).strip()

        if source_handle:
            ident = source_handle
            if part_index:
                ident = f"{ident}|part={part_index}"
        elif regional_id:
            ident = regional_id
            if part_index:
                ident = f"{ident}|part={part_index}"
        else:
            ident = json.dumps(
                feature.get("geometry") or {},
                sort_keys=True,
                ensure_ascii=False,
            )
        return f"{group}|{ident}"


    @staticmethod
    def _geometry_bounds(geometry):
        coords = (geometry or {}).get("coordinates")
        points = []

        def walk(value):
            if (
                isinstance(value, (list, tuple))
                and len(value) >= 2
                and isinstance(value[0], (int, float))
                and isinstance(value[1], (int, float))
            ):
                points.append((float(value[0]), float(value[1])))
                return
            if isinstance(value, (list, tuple)):
                for item in value:
                    walk(item)

        walk(coords)
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def _feature_intersects(cls, feature, west, south, east, north):
        bounds = cls._geometry_bounds(feature.get("geometry") or {})
        if not bounds:
            return False
        fw, fs, fe, fn = bounds
        return fe >= west and fw <= east and fn >= south and fs <= north

    def _fiber_cache_path(self):
        safe = "".join(
            ch if ch.isalnum() or ch in "._-" else "_"
            for ch in str(self.region or "")
        )
        return CACHE_DIR / f"{safe}.fiber.json.gz"

    def _load_fiber_cache(self):
        self.fiber_cache = {"version": "", "features": []}
        path = self._fiber_cache_path()
        if not path.exists():
            return
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                raw = json.load(fh)
            # 구버전 광 캐시도 즉시 화면에 사용한다.
            # 새 데이터가 완전하게 수집/검증된 뒤 저장할 때만 새 schema로 승격한다.
            self.fiber_cache = {
                "version": str(raw.get("version") or ""),
                "features": [x for x in (raw.get("features") or []) if isinstance(x, dict)],
            }
        except Exception:
            self.fiber_cache = {"version": "", "features": []}

    def _save_fiber_cache(self):
        if not self.region:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._fiber_cache_path()
            tmp = path.with_suffix(path.suffix + ".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(
                    {
                        "schema": FIBER_CACHE_SCHEMA,
                        "version": self.fiber_cache.get("version") or "",
                        "features": self.fiber_cache.get("features") or [],
                    },
                    fh,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            os.replace(tmp, path)
        except Exception:
            pass

    def _delete_fiber_cache(self):
        self.fiber_cache = {"version": "", "features": []}
        path = self._fiber_cache_path()
        for candidate in (path, path.with_suffix(path.suffix + ".tmp")):
            try:
                candidate.unlink()
            except Exception:
                pass

    def _fiber_features(self):
        return list(self.fiber_cache.get("features") or [])

    def _expected_group_count(self, group_id):
        """Return active server metadata object_count for one group when available."""
        try:
            info = self.c.online_layers(self.region) or {}
            rows = info.get("layers") or info.get("items") or []
            group = str(group_id or "").upper()
            counts = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("group_id") or "").upper() != group:
                    continue
                if row.get("active") is False:
                    continue
                value = row.get("object_count")
                if value is None:
                    value = row.get("count")
                if value is None:
                    continue
                try:
                    counts.append(int(value))
                except Exception:
                    pass
            return sum(counts) if counts else None
        except Exception:
            return None

    def fiber_progress_status(self):
        region = str(self.region or "")
        state = dict(self.fiber_progress.get(region) or {})
        if not state:
            state = {
                "ok": True,
                "region": region,
                "active": False,
                "percent": 0,
                "stage": "idle",
                "requests": 0,
                "received": 0,
                "expected": self._expected_group_count("FIBER"),
            }
        state["ok"] = True
        return state

    def cached_fiber(self):
        """Return the on-disk fiber cache immediately without touching the server."""
        if not self.region:
            return {"ok": True, "features": [], "cache": "none", "version": ""}
        self._load_fiber_cache()
        return {
            "ok": True,
            "features": self._fiber_features(),
            "cache": "hit" if self.fiber_cache.get("features") else "empty",
            "version": str(self.fiber_cache.get("version") or ""),
        }

    def _fetch_all_region_features(self, region=None, generation=None):
        # 지역 전환 중 이전 지역 전체수집이 새 지역을 오염시키지 않도록
        # 시작 시점의 region/generation을 고정한다.
        region = str(region or self.region or "")
        if generation is None:
            generation = self.region_generation

        def ensure_current():
            if region != self.region or generation != self.region_generation:
                raise RuntimeError("REGION_SWITCH_CANCELLED")

        ensure_current()

        # FIBER 전체 캐시는 해당 지역의 실제 bounds + FIBER 레이어만 수집한다.
        # 과거처럼 전체 그룹을 전국 bbox에서 받은 뒤 FIBER만 거르면
        # COAX/시설 밀도가 높은 지역에서 5,000개 제한을 불필요하게 소진한다.
        limit = 5000
        max_depth = 14

        meta = self.c.online_layers(region) or {}
        layer_rows = meta.get("layers") or meta.get("items") or []
        fiber_layers = []
        for row in layer_rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("group_id") or "").strip().upper() != "FIBER":
                continue
            layer = str(row.get("layer") or "").strip()
            if layer:
                fiber_layers.append(layer)

        if not fiber_layers:
            return []

        bounds = meta.get("bounds") if isinstance(meta, dict) else None
        try:
            west = float((bounds or {}).get("west"))
            south = float((bounds or {}).get("south"))
            east = float((bounds or {}).get("east"))
            north = float((bounds or {}).get("north"))
            if not (-180 <= west <= 180 and -180 <= east <= 180 and
                    -90 <= south <= 90 and -90 <= north <= 90 and
                    west < east and south < north):
                raise ValueError("invalid region bounds")
        except Exception:
            # 메타 bounds가 없는 구형 서버만 기존 전역 bbox로 폴백한다.
            west, south, east, north = -180.0, -90.0, 180.0, 90.0

        layer_filter = ",".join(sorted(set(fiber_layers)))
        progress_seen = {}

        def update_progress(features, stage="receiving"):
            state = self.fiber_progress.get(region)
            if state is None:
                return
            for feature in features or []:
                progress_seen[self._feature_key(feature)] = feature
            expected = state.get("expected")
            received = len(progress_seen)
            state["received"] = received
            state["stage"] = stage
            if expected and expected > 0:
                ratio = min(1.0, received / float(expected))
                state["percent"] = max(state.get("percent", 30), min(78, int(30 + ratio * 48)))
            else:
                state["percent"] = min(72, max(state.get("percent", 30), 30 + min(42, state.get("requests", 0) * 2)))

        def fetch_cell(w, s, e, n, depth=0):
            ensure_current()
            state = self.fiber_progress.get(region)
            if state is not None:
                state["requests"] = int(state.get("requests", 0)) + 1
                state["stage"] = "requesting"

            raw = self.c.online_objects(
                region,
                f"{w},{s},{e},{n}",
                limit=limit,
                layers=layer_filter,
            ) or {}
            ensure_current()
            features = [
                feature for feature in (raw.get("features") or [])
                if str(((feature.get("properties") or {}).get("group_id") or "")).upper() == "FIBER"
            ]

            if len(features) < limit:
                update_progress(features, "receiving")
                return features

            if depth >= max_depth:
                raise RuntimeError(
                    "FIBER 전체수집 제한 도달: "
                    f"depth={depth}, cell_count={len(features)}, limit={limit}, "
                    f"bbox={w},{s},{e},{n}"
                )

            mx = (w + e) / 2.0
            my = (s + n) / 2.0
            merged = {}
            for cell in (
                (w, s, mx, my),
                (mx, s, e, my),
                (w, my, mx, n),
                (mx, my, e, n),
            ):
                for feature in fetch_cell(*cell, depth + 1):
                    merged[self._feature_key(feature)] = feature
            return list(merged.values())

        merged = {}
        for feature in fetch_cell(west, south, east, north):
            merged[self._feature_key(feature)] = feature
        return list(merged.values())


    def ensure_fiber_all(self, force=False):
        if not self.region:
            return {"ok": True, "features": [], "cache": "none"}

        region = str(self.region)
        generation = self.region_generation

        # 이 지역의 서버 revision은 앱 실행 후 최초 진입 시 한 번만 확인한다.
        self._refresh_versions_if_due(force=force)
        fiber_version = str((self.cache_state.get("versions") or {}).get("FIBER") or "")
        self._load_fiber_cache()

        expected_count = self._expected_group_count("FIBER")
        self.fiber_progress[region] = {
            "region": region,
            "active": True,
            "percent": 30,
            "stage": "server_sync",
            "requests": 0,
            "received": 0,
            "expected": expected_count,
        }

        # 과거 버전에서 일부만 저장된 캐시가 동일 revision으로 남아 있을 수 있다.
        # revision 일치만으로 hit 처리하지 않고 서버 object_count와 개수까지 일치해야 한다.
        cached_features = self._fiber_features()
        cached_count = len(cached_features)
        cache_complete = (
            expected_count is None
            or expected_count <= 0
            or cached_count == expected_count
        )
        if (
            not force
            and region in self.fiber_synced_regions
            and fiber_version
            and self.fiber_cache.get("version") == fiber_version
            and cache_complete
        ):
            self.fiber_progress[region].update({
                "active": False, "percent": 100, "stage": "cache_hit",
                "received": cached_count,
            })
            return {
                "ok": True,
                "features": cached_features,
                "cache": "hit",
                "version": fiber_version,
                "expected_count": expected_count,
                "received_count": cached_count,
            }
        if not fiber_version:
            self._delete_fiber_cache()
            self.fiber_progress[region].update({
                "active": False, "percent": 100, "stage": "empty",
            })
            return {"ok": True, "features": [], "cache": "empty", "version": ""}
        try:
            all_features = self._fetch_all_region_features(region, generation)
        except RuntimeError as exc:
            if str(exc) == "REGION_SWITCH_CANCELLED":
                state = self.fiber_progress.get(region)
                if state is not None:
                    state.update({"active": False, "stage": "cancelled"})
                return {
                    "ok": False,
                    "cancelled": True,
                    "features": [],
                    "cache": "cancelled",
                    "region": region,
                }
            raise

        if region != self.region or generation != self.region_generation:
            return {
                "ok": False,
                "cancelled": True,
                "features": [],
                "cache": "cancelled",
                "region": region,
            }

        fiber_features = [
            feature for feature in all_features
            if str(((feature.get("properties") or {}).get("group_id") or "")).upper() == "FIBER"
        ]

        received_count = len(fiber_features)
        unique_key_count = len({self._feature_key(f) for f in fiber_features})
        if expected_count is not None and expected_count > 0 and received_count != expected_count:
            # 일부 광만 받은 상태를 정상 캐시로 덮어쓰지 않는다.
            state = self.fiber_progress.get(region)
            if state is not None:
                state.update({
                    "active": False, "percent": 100, "stage": "validation_failed",
                    "received": received_count,
                })
            return {
                "ok": False,
                "error": (
                    f"광 전체수집 검증 실패 · 서버 메타 {expected_count}개 / 수신 {received_count}개"
                ),
                "features": self._fiber_features(),
                "cache": "stale",
                "version": str(self.fiber_cache.get("version") or ""),
                "expected_count": expected_count,
                "received_count": received_count,
                "unique_key_count": unique_key_count,
            }

        if region != self.region or generation != self.region_generation:
            return {
                "ok": False,
                "cancelled": True,
                "features": [],
                "cache": "cancelled",
                "region": region,
            }

        self.fiber_cache = {"version": fiber_version, "features": fiber_features}
        self._save_fiber_cache()
        self.fiber_synced_regions.add(region)
        state = self.fiber_progress.get(region)
        if state is not None:
            state.update({
                "active": False, "percent": 100, "stage": "complete",
                "received": received_count,
            })
        return {
            "ok": True,
            "features": fiber_features,
            "cache": "network",
            "version": fiber_version,
            "expected_count": expected_count,
            "received_count": received_count,
            "unique_key_count": unique_key_count,
        }

    def _load_cache(self):
        self.cache_state = {"versions": {}, "features": {}, "coverage": []}
        path = self._cache_path()
        if not path.exists():
            return
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                raw = json.load(fh)
            features = {}
            for feature in raw.get("features") or []:
                if isinstance(feature, dict):
                    features[self._feature_key(feature)] = feature
            self.cache_state = {
                "versions": {
                    str(k).upper(): str(v)
                    for k, v in (raw.get("versions") or {}).items()
                },
                "features": features,
                "coverage": list(raw.get("coverage") or [])[-200:],
            }
        except Exception:
            self.cache_state = {"versions": {}, "features": {}, "coverage": []}

    def _save_cache(self):
        if not self.region:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._cache_path()
            tmp = path.with_suffix(path.suffix + ".tmp")
            raw = {
                "versions": self.cache_state.get("versions") or {},
                "features": list((self.cache_state.get("features") or {}).values()),
                "coverage": list(self.cache_state.get("coverage") or [])[-200:],
            }
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                json.dump(raw, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        except Exception:
            pass

    def _delete_cache_file(self):
        if not self.region:
            return
        path = self._cache_path()
        candidates = [
            path,
            path.with_suffix(path.suffix + ".tmp"),
        ]
        for candidate in candidates:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass

    def _apply_versions(self, versions):
        versions = {
            str(k).upper(): str(v)
            for k, v in (versions or {}).items()
            if str(k).strip() and str(v).strip()
        }
        previous = {
            str(k).upper(): str(v)
            for k, v in (self.cache_state.get("versions") or {}).items()
            if str(k).strip() and str(v).strip()
        }

        changed = {
            group
            for group in (set(previous) | set(versions))
            if previous.get(group) != versions.get(group)
        }
        version_changed = bool(previous) and previous != versions

        if version_changed:
            # 캐시 우선 정책:
            # revision이 바뀌어도 현재 화면 캐시는 즉시 삭제하지 않는다.
            # 기존 화면을 유지한 상태에서 새 범위를 내려받고, 저장이 끝난 뒤 교체한다.
            self.cache_state["versions"] = versions
            self.cache_state["coverage"] = []
            return changed

        self.cache_state["versions"] = versions
        return changed

    def _version_signature(self):
        versions = self.cache_state.get("versions") or {}
        return "|".join(f"{k}={versions[k]}" for k in sorted(versions))

    def _cache_covers(self, west, south, east, north):
        signature = self._version_signature()
        for item in self.cache_state.get("coverage") or []:
            if str(item.get("version") or "") != signature:
                continue
            try:
                if (
                    float(item["west"]) <= west
                    and float(item["south"]) <= south
                    and float(item["east"]) >= east
                    and float(item["north"]) >= north
                ):
                    return True
            except Exception:
                continue
        return False

    def _cached_features(self, west, south, east, north):
        return [
            feature
            for feature in (self.cache_state.get("features") or {}).values()
            if self._feature_intersects(feature, west, south, east, north)
        ]

    def _refresh_versions_if_due(self, force=False):
        region = str(self.region or "")
        if not region:
            return set()

        # force는 관리자/명시적 새로고침에서만 사용한다.
        if not force and region in self.checked_regions:
            return set()

        # fiber_all / objects가 동시에 시작돼도 같은 지역 서버 확인은 한 번만 수행한다.
        with self.version_check_lock:
            if not force and region in self.checked_regions:
                return set()
            versions = self.c.online_versions(region) or {}
            changed = self._apply_versions(versions)
            self.checked_regions.add(region)
            return changed

    def _handle_error(self, exc, fallback=None):
        if isinstance(exc, ServerError) and exc.status == 401:
            self.expire_session()
            result = {"ok": False, "session_ended": True}
            if isinstance(fallback, dict):
                result.update(fallback)
            return result
        result = {"ok": False, "error": str(exc)}
        if isinstance(fallback, dict):
            result.update(fallback)
        return result

    def session_policy(self):
        try:
            policy = self.c.session_policy() or {}
            return {
                "ok": True,
                "idle_minutes": int(policy.get("idle_minutes", 10)),
            }
        except Exception as exc:
            return self._handle_error(exc, {"idle_minutes": 10})

    def touch_session(self):
        try:
            self.c.touch_session()
            return {"ok": True}
        except Exception as exc:
            return self._handle_error(exc)

    def _close_session_window(self):
        self.user = None
        self.region = ""
        self.session_ended = True
        try:
            if self.window is not None:
                self.window.destroy()
        except Exception:
            pass
        return True

    def expire_session(self):
        # 401/refresh 실패는 현재 Viewer만 종료한다.
        # 다른 Viewer/런처가 공유 중인 서버 세션을 여기서 revoke하지 않는다.
        return self._close_session_window()

    def end_session(self):
        # 사용자가 명시적으로 로그아웃한 경우에만 서버 세션을 revoke한다.
        try:
            self.c.logout()
        except Exception:
            pass
        return self._close_session_window()

    def logout(self):
        return self.end_session()

    def regions(self):
        try:
            raw = self.c.regions() or []
            if isinstance(raw, dict):
                raw = raw.get("items") or raw.get("regions") or []

            items = []
            seen = set()
            for row in raw:
                if not isinstance(row, dict):
                    continue
                region_id = str(row.get("id") or "").strip()
                if not region_id:
                    continue
                key = region_id.casefold()
                if key in seen:
                    continue
                seen.add(key)
                name = str(row.get("name") or region_id).strip()
                bounds = None
                try:
                    meta = self.c.online_layers(region_id) or {}
                    raw_bounds = meta.get("bounds") if isinstance(meta, dict) else None
                    if isinstance(raw_bounds, dict):
                        keys = ("west", "south", "east", "north")
                        if all(raw_bounds.get(k) is not None for k in keys):
                            bounds = {k: float(raw_bounds.get(k)) for k in keys}
                except Exception:
                    bounds = None
                items.append({"id": region_id, "name": name or region_id, "bounds": bounds})

            return {
                "ok": True,
                "items": items,
                "count": len(items),
                "level": int((self.user or {}).get("level") or 0),
            }
        except Exception as exc:
            return self._handle_error(
                exc,
                {
                    "items": [],
                    "count": 0,
                    "level": int((self.user or {}).get("level") or 0),
                },
            )

    def select(self, region):
        new_region = str(region or "")
        if new_region != self.region:
            self.region_generation += 1
        self.region = new_region
        if not self.region:
            self.cache_state = {"versions": {}, "features": {}, "coverage": []}
            self.fiber_cache = {"version": "", "features": []}
            return {"ok": True, "bounds": None, "layers": []}
        try:
            # UI 응답 우선: 지역 선택에서는 서버를 기다리지 않는다.
            self._load_cache()
            self._load_fiber_cache()

            group_counts = {}
            for feature in (self.cache_state.get("features") or {}).values():
                group = str(((feature.get("properties") or {}).get("group_id") or "")).upper()
                if group:
                    group_counts[group] = group_counts.get(group, 0) + 1

            fiber_count = len(self.fiber_cache.get("features") or [])
            if fiber_count:
                group_counts["FIBER"] = fiber_count

            group_summary = [
                {"group_id": group, "count": count}
                for group, count in sorted(group_counts.items())
            ]

            return {
                "ok": True,
                "bounds": None,
                "layers": [],
                "group_summary": group_summary,
                "cache_ready": bool(fiber_count or self.cache_state.get("features")),
                "cache_count": len(self.cache_state.get("features") or {}) + fiber_count,
                "fiber_cache_count": fiber_count,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _fiber_layers(self):
        try:
            meta = self.c.online_layers(self.region) or {}
            rows = meta.get("layers") or meta.get("items") or []
            result = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("group_id") or "").strip().upper() != "FIBER":
                    continue
                layer = str(row.get("layer") or "").strip()
                if layer:
                    result.append(layer)
            return sorted(set(result))
        except Exception:
            return []

    def _fiber_cached_features(self, west, south, east, north):
        return [
            feature for feature in self._fiber_features()
            if self._feature_intersects(feature, west, south, east, north)
        ]

    def _fetch_fiber_bbox_network(self, west, south, east, north):
        layers = self._fiber_layers()
        limit = 5000
        max_depth = 14
        layer_filter = ",".join(layers) if layers else None

        def fetch_cell(cw, cs, ce, cn, depth=0):
            raw = self.c.online_objects(
                self.region,
                f"{cw},{cs},{ce},{cn}",
                limit=limit,
                layers=layer_filter,
            ) or {}
            features = [
                feature for feature in (raw.get("features") or [])
                if str(((feature.get("properties") or {}).get("group_id") or "")).upper() == "FIBER"
            ]
            if len(features) < limit:
                return features
            if depth >= max_depth:
                raise RuntimeError(
                    "FIBER 화면수집 제한 도달: "
                    f"depth={depth}, cell_count={len(features)}, limit={limit}, "
                    f"bbox={cw},{cs},{ce},{cn}"
                )
            mx = (cw + ce) / 2.0
            my = (cs + cn) / 2.0
            merged = {}
            for cell in (
                (cw, cs, mx, my),
                (mx, cs, ce, my),
                (cw, my, mx, cn),
                (mx, my, ce, cn),
            ):
                for feature in fetch_cell(*cell, depth + 1):
                    merged[self._feature_key(feature)] = feature
            return list(merged.values())

        merged = {}
        for feature in fetch_cell(west, south, east, north):
            merged[self._feature_key(feature)] = feature
        return list(merged.values())

    def _merge_fiber_bbox_cache(self, features):
        with self.cache_lock:
            existing = {self._feature_key(f): f for f in self._fiber_features()}
            for feature in features:
                existing[self._feature_key(feature)] = feature
            fiber_version = str((self.cache_state.get("versions") or {}).get("FIBER") or "")
            self.fiber_cache = {
                "version": fiber_version or str(self.fiber_cache.get("version") or ""),
                "features": list(existing.values()),
            }
            self._save_fiber_cache()

    def _start_fiber_bbox_refresh(self, west, south, east, north):
        key = (
            round(float(west), 6), round(float(south), 6),
            round(float(east), 6), round(float(north), 6),
        )
        with self.cache_lock:
            if key in self.fiber_bbox_refreshing:
                return False
            self.fiber_bbox_refreshing.add(key)

        region = str(self.region or "")

        def worker():
            try:
                if region != self.region:
                    return
                self._refresh_versions_if_due()
                features = self._fetch_fiber_bbox_network(west, south, east, north)
                if region != self.region:
                    return
                self._merge_fiber_bbox_cache(features)
            except Exception:
                pass
            finally:
                with self.cache_lock:
                    self.fiber_bbox_refreshing.discard(key)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def fiber_bbox(self, west, south, east, north, force=False):
        if not self.region:
            return {"ok": True, "features": [], "cache": "none", "refresh_pending": False}
        try:
            west = float(west); south = float(south); east = float(east); north = float(north)
            self._load_fiber_cache()
            cached = self._fiber_cached_features(west, south, east, north)
            if cached and not force:
                self._start_fiber_bbox_refresh(west, south, east, north)
                return {
                    "ok": True,
                    "features": cached,
                    "cache": "stale",
                    "refresh_pending": True,
                }

            self._refresh_versions_if_due(force=force)
            fresh = self._fetch_fiber_bbox_network(west, south, east, north)
            self._merge_fiber_bbox_cache(fresh)
            return {
                "ok": True,
                "features": self._fiber_cached_features(west, south, east, north),
                "cache": "network",
                "refresh_pending": False,
            }
        except Exception as exc:
            return self._handle_error(exc, {"features": [], "cache": "error", "refresh_pending": False})


    def _fetch_bbox_network(self, west, south, east, north):
        limit = 2000
        max_depth = 5

        def fetch_cell(cw, cs, ce, cn, depth=0):
            raw = self.c.online_objects(
                self.region,
                f"{cw},{cs},{ce},{cn}",
                limit=limit,
            ) or {}
            features = list(raw.get("features") or [])

            # 일반 화면은 전체 bbox 1회로 끝낸다.
            # 서버 limit에 실제로 도달한 경우에만 4분할한다.
            if len(features) < limit or depth >= max_depth:
                return features

            mx = (cw + ce) / 2.0
            my = (cs + cn) / 2.0
            merged = {}
            for cell in (
                (cw, cs, mx, my),
                (mx, cs, ce, my),
                (cw, my, mx, cn),
                (mx, my, ce, cn),
            ):
                for feature in fetch_cell(*cell, depth + 1):
                    merged[self._feature_key(feature)] = feature
            return list(merged.values())

        return fetch_cell(west, south, east, north)

    def _commit_bbox_cache(self, features, west, south, east, north):
        with self.cache_lock:
            feature_store = self.cache_state.setdefault("features", {})
            stale_keys = [
                key for key, feature in feature_store.items()
                if self._feature_intersects(feature, west, south, east, north)
                and str(((feature.get("properties") or {}).get("group_id") or "")).upper() != "FIBER"
            ]
            for key in stale_keys:
                feature_store.pop(key, None)

            for feature in features:
                if str(((feature.get("properties") or {}).get("group_id") or "")).upper() == "FIBER":
                    continue
                feature_store[self._feature_key(feature)] = feature

            self.cache_state.setdefault("coverage", []).append({
                "west": west,
                "south": south,
                "east": east,
                "north": north,
                "version": self._version_signature(),
            })
            self.cache_state["coverage"] = self.cache_state["coverage"][-200:]
            self._save_cache()

    def _start_bbox_refresh(self, west, south, east, north):
        key = (
            round(float(west), 6), round(float(south), 6),
            round(float(east), 6), round(float(north), 6),
        )
        with self.cache_lock:
            if key in self.bbox_refreshing:
                return False
            self.bbox_refreshing.add(key)

        region = str(self.region or "")

        def worker():
            try:
                if region != self.region:
                    return
                self._refresh_versions_if_due()
                features = self._fetch_bbox_network(west, south, east, north)
                if region != self.region:
                    return
                self._commit_bbox_cache(features, west, south, east, north)
            except Exception:
                pass
            finally:
                with self.cache_lock:
                    self.bbox_refreshing.discard(key)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def objects(self, west, south, east, north):
        if not self.region:
            return {"features": []}
        try:
            west = float(west)
            south = float(south)
            east = float(east)
            north = float(north)

            # 1) 최신 coverage가 있으면 순수 캐시 hit.
            if self._cache_covers(west, south, east, north):
                nearby = [
                    feature for feature in self._cached_features(west, south, east, north)
                    if str(((feature.get("properties") or {}).get("group_id") or "")).upper() != "FIBER"
                ]
                return {"features": nearby, "cache": "hit", "refresh_pending": False}

            # 2) coverage가 오래됐더라도 기존 캐시가 있으면 먼저 즉시 반환한다.
            # 서버 revision 확인/새 데이터 수신/저장은 백그라운드에서 수행한다.
            stale_nearby = [
                feature for feature in self._cached_features(west, south, east, north)
                if str(((feature.get("properties") or {}).get("group_id") or "")).upper() != "FIBER"
            ]
            if stale_nearby:
                self._start_bbox_refresh(west, south, east, north)
                return {
                    "features": stale_nearby,
                    "cache": "stale",
                    "refresh_pending": True,
                }

            # 3) 이 범위에 캐시가 전혀 없을 때만 최초 서버 수신을 기다린다.
            self._refresh_versions_if_due()
            features = self._fetch_bbox_network(west, south, east, north)
            self._commit_bbox_cache(features, west, south, east, north)
            nearby = [
                feature for feature in self._cached_features(west, south, east, north)
                if str(((feature.get("properties") or {}).get("group_id") or "")).upper() != "FIBER"
            ]
            return {"features": nearby, "cache": "network", "refresh_pending": False}
        except Exception as exc:
            handled = self._handle_error(exc, {"features": []})
            return handled


def html(k, local_token):
    return f"""<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<style>
html,body,#map,#roadview{{width:100%;height:100%;margin:0;font-family:'Malgun Gothic',sans-serif}}
#roadview{{position:absolute;inset:0;display:none;background:#111}}
#top{{position:absolute;z-index:10;top:10px;left:10px;right:10px;display:flex;gap:8px;align-items:center;pointer-events:none}}
.card{{background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:7px 9px;box-shadow:0 2px 8px rgba(0,0,0,.16);pointer-events:auto}}
#tools{{display:flex;gap:6px;align-items:center;min-width:0;width:100%}}
#toolButtons{{display:flex;gap:6px;align-items:center;flex:0 0 auto;white-space:nowrap}}
#tools select,#tools button{{height:30px}}
#statusWrap{{flex:1 1 auto;min-width:0;overflow:hidden;padding-left:4px;display:flex;flex-direction:column;gap:3px}}
#statusLine{{display:flex;align-items:center;gap:8px;min-width:0}}
#status{{display:block;flex:1 1 auto;font-size:12px;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}}
#progressText{{flex:0 0 auto;min-width:38px;text-align:right;font-size:11px;font-weight:700;color:#334155}}
#progressTrack{{height:5px;background:#e2e8f0;border-radius:999px;overflow:hidden}}
#progressBar{{height:100%;width:0%;background:#2563eb;transition:width .2s ease}}
#progressBar.busy{{background:linear-gradient(90deg,#2563eb 0%,#60a5fa 50%,#2563eb 100%);background-size:200% 100%;animation:progressPulse 1.2s linear infinite}}
@keyframes progressPulse{{from{{background-position:200% 0}}to{{background-position:0 0}}}}
#measureBox{{display:flex;flex-direction:column;gap:2px;align-items:stretch}}
#measureBox button{{height:22px!important;padding:0 8px;font-size:11px}}
#measureDistance.on{{background:#0f766e;color:#fff;border:1px solid #115e59}}
.measureDeleteMenu{{background:#fff;border:1px solid #dc2626;border-radius:5px;padding:4px;box-shadow:0 2px 8px rgba(0,0,0,.2)}}
.measureDeleteMenu button{{height:26px;border:0;background:#dc2626;color:#fff;border-radius:4px;cursor:pointer}}
.measureLabel{{background:rgba(255,255,255,.96);border:1px solid #0f766e;border-radius:4px;padding:2px 5px;font:700 11px 'Malgun Gothic';color:#115e59;white-space:nowrap}}
.layerBtn{{border:1px solid #94a3b8;background:#fff;border-radius:5px;padding:0 9px;cursor:pointer}}
.layerBtn.on{{background:#2563eb;color:#fff;border-color:#1d4ed8}}
#detail{{position:absolute;z-index:8;top:60px;right:10px;max-width:360px;background:#fff;border:1px solid #cbd5e1;border-radius:8px;padding:8px;display:none;max-height:50vh;overflow:auto;font-size:12px}}
.row{{display:grid;grid-template-columns:max-content 1fr;gap:4px 9px;margin:2px 0}}
.key{{color:#64748b}}
</style>
<script src='https://dapi.kakao.com/v2/maps/sdk.js?appkey={k}&autoload=false'></script>
</head>
<body>
<div id='map'></div>
<div id='roadview'></div>

<div id='top'>
  <div class='card' id='tools'>
    <div id='toolButtons'>
      <b>CMB 온라인 Viewer</b>
      <select id='region' title='권한 지역 선택'><option value=''>지역 선택</option></select>
      <button class='layerBtn on' data-group='FIBER'>광</button>
      <button class='layerBtn on' data-group='COAX'>동축</button>
      <button class='layerBtn' data-group='CONDUIT'>관로</button>
      <button class='layerBtn' data-group='POLE'>전주</button>
      <button class='layerBtn' data-group='USER'>USER</button>
      <button id='myLocation'>내 위치</button>
      <button id='mapHybrid' title='일반지도 / 위성지도 전환'>위성지도</button>
      <button id='roadviewBtn' title='현재 지도 중심의 로드뷰 열기'>로드뷰</button>
      <button id='reload'>새로고침</button>
      <div id='measureBox'>
        <button id='clearDistance' title='모든 거리 측정 삭제'>거리 삭제</button>
        <button id='measureDistance' title='거리 측정 시작'>거리</button>
      </div>
    </div>
    <div id='statusWrap'>
      <div id='statusLine'>
        <span id='status' title='현재 상태'>세션 확인 중</span>
        <span id='progressText'>0%</span>
      </div>
      <div id='progressTrack'><div id='progressBar'></div></div>
    </div>
  </div>
</div>

<div id='detail'></div>

<script>
const LOCAL_API_TOKEN={json.dumps(local_token)};
async function apiCall(name,payload={{}}){{
  const response=await fetch('/api/'+name,{{
    method:'POST',
    headers:{{
      'Content-Type':'application/json',
      'X-CMB-Local-Token':LOCAL_API_TOKEN
    }},
    body:JSON.stringify(payload||{{}})
  }});
  let data={{}};
  try{{data=await response.json();}}catch(e){{}}
  if(!response.ok){{
    throw new Error((data&&data.error)||('내부 Viewer API 오류 '+response.status));
  }}
  return data;
}}
let map;
let overlays=[];
const overlayGroups=new Map();
const overlayKinds=new Map();
let loadGeneration=0;
let selectedOverlay=null;
let selectedCable=null;
let selectedCableStyle=null;
let selectedCableArrows=[];
let selectedCableArrowStyles=[];
const cableArrows=new Map();
let hybridMode=false;
let roadview=null;
let roadviewClient=null;
let roadviewMode=false;
let lodReferenceSpan=null;
let idleMinutes=10;
let myLat=null,myLng=null;
let lastQueryLat=null,lastQueryLng=null,lastDetailMode=null;
let lastFiberQueryLat=null,lastFiberQueryLng=null;
const QUERY_RADIUS_METERS=500;
const QUERY_RECENTER_METERS=200;
let lastActivity=Date.now();
let idleTimer=null;
let nonFiberLoadTimer=null;
let authorizedRegions=[];
let activeRegionId='';
let regionSwitching=false;
let regionSwitchGeneration=0;
let regionResolveTimer=null;
let regionResolveGeneration=0;
const REGION_SETTLE_DELAY_MS=700;
let fiberViewportGeneration=0;
let authenticated=false;
let lastServerTouch=0;
let fiberDiag={{server:0,received:0,unique:0,cache:0,lineObjects:0,renderParts:0,deviceObjects:0}};
let distanceMode=false;
let distancePoints=[];
let activeDistanceLine=null;
let activeDistanceLabel=null;
let distanceSessions=[];
let distanceDeleteMenu=null;
let currentPointFeatures=[];
let currentFiberPointFeatures=[];
let currentLineFeatures=[];
let currentDevices=[];
let viewDiag={{region:'',centerLat:null,centerLng:null,stage:'대기',progress:''}};
let lastRegionResolveLat=null,lastRegionResolveLng=null,lastRegionResolveId='';

function currentCenterText(){{
  if(!map)return 'CENTER -';
  const c=map.getCenter();
  const lat=Number(c.getLat()),lng=Number(c.getLng());
  viewDiag.centerLat=lat; viewDiag.centerLng=lng;
  return 'CENTER '+lat.toFixed(5)+','+lng.toFixed(5);
}}

function viewDiagText(){{
  const region=String((document.getElementById('region')||{{value:''}}).value||viewDiag.region||'-');
  const parts=[
    'REGION '+region,
    currentCenterText(),
    'STAGE '+String(viewDiag.stage||'대기')
  ];
  if(viewDiag.progress)parts.push(String(viewDiag.progress));
  return parts.join(' · ');
}}

function queryBoundsFromCenter(lat,lng){{
  const radius=Math.max(100,Number(QUERY_RADIUS_METERS)||500);
  const latDelta=radius/111320;
  const lngScale=Math.max(0.2,Math.cos(Number(lat)*Math.PI/180));
  const lngDelta=radius/(111320*lngScale);
  return {{
    west:Number(lng)-lngDelta,
    south:Number(lat)-latDelta,
    east:Number(lng)+lngDelta,
    north:Number(lat)+latDelta
  }};
}}

function fiberDiagText(){{
  const d=fiberDiag||{{}};
  if(!d.server&&!d.received&&!d.cache&&!d.renderParts)return '';
  return ' · 광[서버 '+String(d.server||'?')+
    '/수신 '+String(d.received||0)+
    '/고유 '+String(d.unique||0)+
    '/캐시 '+String(d.cache||0)+
    '/선객체 '+String(d.lineObjects||0)+
    '/광기기 '+String(d.deviceObjects||0)+
    '/렌더 '+String(d.renderParts||0)+']';
}}
const MAX_LEVEL=14;
const ZOOM_STEP=1.35;
const MIN_NETWORK_LEVEL=8;
const groupEnabled={{FIBER:true,COAX:true,POLE:false,CONDUIT:false,USER:false}};

function layerLevel(layer){{
  const name=String(layer||'').trim().toUpperCase();
  if(name.startsWith('TS_')||name==='TL_SCCO_SIG'||name.includes('ANNO')) return 999;
  if(['F_CABLE','FOC','FIBER','OPTIC','광케이블','광선로'].some(k=>name.includes(k))) return 0;
  const rules=[
    [['CN_C_CELLBOUND'],1],
    [['CN_C_CELLNO'],2],
    [['CN_C_ONU'],3],
    [['TL_SPRD_RW'],4],
    [['CN_C_CABLE','COAX','동축'],5],
    [['CN_C_AMP'],6],
    [['CN_F_CLOSURE','CN_F_CENTER','CN_F_TERMINAL'],7],
    [['CN_C_POWER','CN_C_TAP','CN_C_PASSIVE','CN_C_CONNECTOR','CN_C_DC_','CN_C_SUBSCRIBERS','CN_C_NMS_'],8],
    [['건물'],9],
    [['CN_M_USER_'],10],
    [['CN_L_POLE_POLE','CN_L_POLE_MANHOLE','CN_L_POLE_HANDHOLE','CN_L_POLE_LINE_'],11]
  ];
  for(const [prefixes,level] of rules){{
    if(prefixes.some(p=>name.startsWith(p))) return level;
  }}
  if(name==='CN_L_POLE') return 11;
  if(name==='0') return 12;
  if(['_ID','TEXT','LABEL','지번'].some(k=>name.includes(k))) return MAX_LEVEL;
  return 13;
}}

function viewportSpan(){{
  if(!map) return null;
  const b=map.getBounds(),sw=b.getSouthWest(),ne=b.getNorthEast();
  const lat=(sw.getLat()+ne.getLat())/2*Math.PI/180;
  const dx=(ne.getLng()-sw.getLng())*Math.cos(lat);
  const dy=(ne.getLat()-sw.getLat());
  return Math.hypot(dx,dy);
}}

function detailLevel(){{
  const span=viewportSpan();
  if(!span||!lodReferenceSpan||span>=lodReferenceSpan) return 0;
  const ratio=lodReferenceSpan/span;
  return Math.min(MAX_LEVEL,Math.max(0,Math.floor(Math.log(ratio)/Math.log(ZOOM_STEP)+1e-8)));
}}

function setStatus(t){{document.getElementById('status').textContent=t||''}}
function setProgress(percent,busy=false){{
  const p=Math.max(0,Math.min(100,Math.round(Number(percent)||0)));
  const bar=document.getElementById('progressBar');
  const textEl=document.getElementById('progressText');
  if(bar){{
    if(bar.style)bar.style.width=String(p)+'%';
    if(bar.classList&&typeof bar.classList.toggle==='function'){{
      bar.classList.toggle('busy',!!busy && p<100);
    }}
  }}
  if(textEl)textEl.textContent=String(p)+'%';
}}
function setWorkStatus(text,percent,busy=false){{
  setStatus(text);
  setProgress(percent,busy);
}}

function noteActivity(){{
  if(!authenticated)return;
  const now=Date.now();
  lastActivity=now;
  if(now-lastServerTouch>=30000){{
    lastServerTouch=now;
    apiCall('touch_session').catch(()=>{{}});
  }}
}}

async function forceIdleLogout(){{
  if(!authenticated)return;
  authenticated=false;
  setStatus('유휴시간 만료 · 최초 로그인 화면으로 이동');
  try{{await apiCall('end_session');}}catch(e){{}}
}}

function startIdleWatch(){{
  if(idleTimer)clearInterval(idleTimer);
  lastActivity=Date.now();
  idleTimer=setInterval(()=>{{
    if(!authenticated)return;
    const limit=Math.max(1,idleMinutes)*60*1000;
    if(Date.now()-lastActivity>=limit)forceIdleLogout();
  }},5000);
}}

async function loadSessionPolicy(){{
  try{{
    const r=await apiCall('session_policy');
    if(r&&r.ok&&Number(r.idle_minutes)>0)idleMinutes=Number(r.idle_minutes);
  }}catch(e){{idleMinutes=10;}}
}}

function registerOverlay(overlay,group,kind=''){{
  if(!overlay)return overlay;
  const g=String(group||'').toUpperCase();
  const k=String(kind||'').toLowerCase();
  overlays.push(overlay);
  overlayGroups.set(overlay,g);
  if(k)overlayKinds.set(overlay,k);
  return overlay;
}}

function clearOverlays(){{
  restoreSelectedCable();
  loadGeneration++;
  fiberViewportGeneration++;
  overlays.forEach(x=>{{
    try{{x.setMap(null);}}catch(e){{}}
    overlayGroups.delete(x);
    overlayKinds.delete(x);
  }});
  overlays=[];
  cableArrows.clear();
  selectedOverlay=null;
  selectedCable=null;
  selectedCableArrows=[];
  currentPointFeatures=[];
  currentFiberPointFeatures=[];
  currentLineFeatures=[];
  currentDevices=[];
  fiberDiag={{server:0,received:0,unique:0,cache:0,lineObjects:0,renderParts:0,deviceObjects:0}};
}}

function clearNonFiberOverlays(){{
  loadGeneration++;
  const kept=[];
  overlays.forEach(x=>{{
    if(overlayGroups.get(x)==='FIBER'){{
      kept.push(x);
    }}else{{
      try{{x.setMap(null);}}catch(e){{}}
      overlayGroups.delete(x);
      overlayKinds.delete(x);
    }}
  }});
  overlays=kept;
  selectedOverlay=null;
}}

function clearGroupOverlays(group){{
  const target=String(group||'').toUpperCase();
  if(selectedCable && String(overlayGroups.get(selectedCable)||'').toUpperCase()===target){{
    restoreSelectedCable();
  }}
  if(target==='FIBER')cableArrows.clear();
  // 그룹 하나를 다시 그리는 작업은 다른 그룹의 진행 중 조회를 취소하면 안 된다.
  // 특히 FIBER 셀 렌더가 loadGeneration을 올리면 동시에 진행 중인
  // COAX/기기 loadObjects() 결과가 정상 응답이어도 폐기되는 문제가 생긴다.
  // 전체/지역 전환 취소는 clearOverlays()/clearNonFiberOverlays()에서만 수행한다.
  const kept=[];
  overlays.forEach(x=>{{
    if(overlayGroups.get(x)===target){{
      try{{x.setMap(null);}}catch(e){{}}
      overlayGroups.delete(x);
      overlayKinds.delete(x);
    }}else{{
      kept.push(x);
    }}
  }});
  overlays=kept;
  selectedOverlay=null;
}}

function hideGroupOverlays(group){{
  const target=String(group||'').toUpperCase();
  let count=0;
  overlays.forEach(x=>{{
    if(overlayGroups.get(x)!==target)return;
    try{{x.setMap(null);count++;}}catch(e){{}}
  }});
  selectedOverlay=null;
  return count;
}}

function showGroupOverlays(group){{
  const target=String(group||'').toUpperCase();
  let count=0;
  overlays.forEach(x=>{{
    if(overlayGroups.get(x)!==target)return;
    try{{x.setMap(map);count++;}}catch(e){{}}
  }});
  return count;
}}

function showDetail(p){{
  const d=document.getElementById('detail');
  const rows=[];
  const add=(k,v)=>{{if(v!==null&&v!==undefined&&String(v).trim()!=='') rows.push([k,String(v)])}};
  add('그룹',p.group_id);
  add('레이어',p.layer);
  add('객체종류',p.entity_type);
  add('블록',p.block_name);
  add('객체 ID',p.regional_object_id||p.entity_id);
  const a=p.attributes||{{}};
  const f=a.fields||a;
  const dxf=f._cmb_dxf_data||{{}};
  const pole=f._cmb_pole_info||{{}};
  const polePos=f._cmb_pole_position||{{}};
  if(polePos.pole_no)add('전주번호',polePos.pole_no);
  if(polePos.grid_id)add('전주 격자정보(상세)',polePos.grid_id);
  Object.keys(f).sort().forEach(k=>{{
    if(!k.startsWith('_cmb_')) add(k,f[k]);
  }});
  Object.keys(pole).sort().forEach(k=>add('전주/'+k,pole[k]));
  const labels={{insert:'삽입점',location:'위치',center:'중심점',start:'시작점',end:'끝점',rotation:'회전각',angle:'각도',radius:'반지름',xscale:'X 스케일',yscale:'Y 스케일',zscale:'Z 스케일',elevation:'표고',extrusion:'돌출방향',height:'문자높이',text:'문자',name:'이름',closed:'폐합여부'}};
  Object.keys(dxf).sort().forEach(k=>add(labels[String(k).toLowerCase()]||k,dxf[k]));
  if(!rows.length){{d.style.display='none';return}}
  d.innerHTML=rows.map(x=>'<div class="row"><div class="key">'+esc(x[0])+'</div><div>'+esc(x[1])+'</div></div>').join('');
  d.style.display='block';
}}

function esc(v){{
  return String(v).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}

function colorFor(group){{
  group=(group||'').toUpperCase();
  if(group==='FIBER')return '#1e88e5';
  if(group==='COAX')return '#f57c00';
  if(group==='POLE')return '#6d4c41';
  if(group==='CONDUIT')return '#00acc1';
  return '#8e24aa';
}}

function originalCableColor(p,group){{
  group=String(group||'').toUpperCase();
  const layer=String((p&&p.layer)||'').trim().toUpperCase();
  const a=(p&&p.attributes)||{{}};
  const f=a.fields||a;
  const style=f._cmb_style||{{}};

  // CAD에서 추출한 실제 선 색상을 최우선으로 복원한다.
  // 그룹 고정색으로 덮어쓰면 동축/셀테두리/연결선이 모두 같은 색이 되는 문제가 생긴다.
  const display=String(style.display_color||'').trim();
  if(/^#[0-9a-fA-F]{{6}}$/.test(display)){{
    const d=display.toLowerCase();
    // 카카오 지도에서 완전 흰색/검정색만 묻히므로 이 두 색만 레이어별 안전색으로 보정한다.
    if(d!=='#ffffff' && d!=='#000000') return d;
  }}
  const tc=Number(style.true_color);
  if(Number.isFinite(tc)&&tc>=0&&tc<=0xFFFFFF){{
    const d='#'+Math.trunc(tc).toString(16).padStart(6,'0');
    if(d!=='#ffffff' && d!=='#000000') return d;
  }}

  // 원본 색상이 화면에서 사용할 수 없을 때만 레이어 역할별 기본색을 사용한다.
  if(layer.startsWith('CN_C_CELLBOUND')) return '#00a152';
  if(layer.startsWith('CN_C_CABLE') || layer.includes('COAX') || layer.includes('동축')) return '#f57c00';
  if(layer.includes('F_CABLE') || layer.includes('FOC') || layer.includes('FIBER') ||
     layer.includes('OPTIC') || layer.includes('광케이블') || layer.includes('광선로')) return '#1e88e5';
  if(layer.includes('CONNECT') || layer.includes('LINK') || layer.includes('PASSIVE')) return '#7b1fa2';
  return colorFor(group);
}}

const SYMBOL_LIBRARY={{
  onu:{{shape:'rect',w:38.4,h:19.2,fill:'#12c978',stroke:'#075c3c',label:'ONU',labelColor:'#053b2b'}},
  amp:{{shape:'triangle',w:18,h:18,fill:'#ff8f00',stroke:'#6d3b00'}},
  pole:{{shape:'circle_x',r:2.2,fill:'#ffffff',stroke:'#6d4c41'}},
  tap:{{shape:'hexagon',w:18,h:16,fill:'#ffc928',stroke:'#6d4c00'}},
  splitter:{{shape:'circle',r:8,fill:'#ffffff',stroke:'#424242',labelColor:'#212121'}},
  pi:{{shape:'rect',w:18,h:12,fill:'#ffffff',stroke:'#424242',label:'I',labelColor:'#212121'}},
  manhole:{{shape:'double_circle',r:9,fill:'#f5f5f5',stroke:'#424242'}},
  power:{{shape:'square_circle',w:18,h:18,fill:'#e53935',stroke:'#7f0000',innerFill:'#ffffff',label:'PS',labelColor:'#7f0000'}},
  power_ps:{{shape:'square_circle',w:18,h:18,fill:'#e53935',stroke:'#7f0000',innerFill:'#ffffff',label:'PS',labelColor:'#7f0000'}},
  closure:{{shape:'closure_box',w:24,h:15,fill:'#DCEBFF',stroke:'#1F4E79'}},
  fiber_terminal:{{shape:'rect',w:18,h:18,fill:'#ffffff',stroke:'#1565c0',labelColor:'#ff1493'}},
  fiber_rn:{{shape:'text_only',w:0,h:0,fill:'#ffffff',stroke:'#424242',labelColor:'#424242'}},
  fiber_net:{{shape:'rect',w:30,h:14,fill:'#ffffff',stroke:'#424242',labelColor:'#212121'}},
  generic:{{shape:'rect',w:16,h:12,fill:'#eeeeee',stroke:'#424242'}}
}};

function storedPolePosition(f){{
  // 지도 표시/검색/캐시의 유일한 공간 기준은 GeoJSON 위·경도 geometry이다.
  // 전주번호, _cmb_pole_position, _cmb_pole_refs는 상세정보용 메타데이터로만 유지한다.
  const g=(f&&f.geometry)||{{}};
  const xy=g.coordinates||[];
  if(Array.isArray(xy)&&xy.length>=2&&
     Number.isFinite(Number(xy[0]))&&Number.isFinite(Number(xy[1]))&&
     Math.abs(Number(xy[0]))<=180&&Math.abs(Number(xy[1]))<=90){{
    return [Number(xy[0]),Number(xy[1])];
  }}
  return null;
}}

function isConnectorFeature(f){{
  const p=f.properties||{{}};
  const layer=String(p.layer||'').trim().toUpperCase();
  const block=String(p.block_name||'').trim().toUpperCase();
  const text=(layer+' '+block).toUpperCase();
  return layer.startsWith('CN_C_CONNECTOR') ||
         block.startsWith('CONNECTOR') ||
         block.startsWith('FO_VCONN') ||
         block.startsWith('FO_VOCONN') ||
         text.includes(' CONNECTOR');
}}

function isAnnoFeature(f){{
  const p=f.properties||{{}};
  const layer=String(p.layer||'').trim().toUpperCase();
  const block=String(p.block_name||'').trim().toUpperCase();
  return layer.includes('ANNO') || block.includes('ANNO');
}}

function isInfoPointFeature(f){{
  if(isAnnoFeature(f))return true;
  const p=f.properties||{{}};
  const a=p.attributes||{{}};
  const fields=a.fields||a;
  const layer=String(p.layer||'').trim().toUpperCase();
  const entityType=String(p.entity_type||'').trim().toUpperCase();
  const block=String(p.block_name||'').trim().toUpperCase();

  // 문자/주석 엔티티는 기기가 아니다.
  if(['TEXT','MTEXT','ATTRIB','ATTDEF','DIMENSION','LEADER','MLEADER'].includes(entityType))return true;

  const infoLayerTokens=[
    'CELLNO','_ID','TEXT','LABEL','JIBUN','지번','ADDRESS','ADDR',
    'NAME','NUMBER','NO_','번호','INFO','ANNO','ANNOT','NOTE','MEMO'
  ];
  if(infoLayerTokens.some(k=>layer.includes(k)))return true;

  // 정보/주석 전용 블록도 기기로 만들지 않는다.
  const infoBlockTokens=['TEXT','LABEL','ID','ADDR','ADDRESS','JIBUN','INFO','NOTE','TAG'];
  if(infoBlockTokens.some(k=>block===k || block.startsWith(k+'_') || block.endsWith('_'+k)))return true;

  const keys=Object.keys(fields||{{}}).map(k=>String(k).toUpperCase());
  const hasTextPayload=keys.some(k=>
    k==='TEXT' || k==='MTEXT' || k.includes('LABEL') || k.includes('ANNOT') ||
    k.includes('NOTE') || k.includes('MEMO') || k.includes('CAPTION')
  );
  const dxf=fields._cmb_dxf_data||{{}};
  const dxfKeys=Object.keys(dxf||{{}}).map(k=>String(k).toUpperCase());
  const dxfHasText=dxfKeys.some(k=>k==='TEXT' || k==='TAG' || k==='PROMPT' || k==='CONTENT');
  if(hasTextPayload || dxfHasText)return true;

  // 실제 기기 판정 힌트가 없고, 속성이 정보성 필드만 가진 POINT는 제외한다.
  const kindHint=String(fields._cmb_symbol_kind||'').toLowerCase();
  const deviceHint=(fields._cmb_is_device===true);
  const knownDeviceKind=['onu','amp','splitter','tap','power','power_ps','closure','pole','manhole'];
  if(!deviceHint && !knownDeviceKind.includes(kindHint)){{
    const hasInfoKeys=keys.some(k=>
      k.includes('ID') || k.includes('ADDR') || k.includes('ADDRESS') ||
      k.includes('JIBUN') || k.includes('NAME') || k.includes('NUMBER') ||
      k.includes('NO') || k.includes('TEXT') || k.includes('LABEL')
    );
    if(hasInfoKeys && entityType!=='INSERT')return true;
  }}
  return false;
}}

function symbolKind(p){{
  const a=p.attributes||{{}};
  const f=a.fields||a;
  const layer=String(p.layer||'').trim().toUpperCase();
  const block=String(p.block_name||'').trim().toUpperCase();
  const entityType=String(p.entity_type||'').trim().toUpperCase();
  const s=(layer+' '+block+' '+entityType+' '+JSON.stringify(p.attributes||{{}})).toUpperCase();
  const padded=' '+s.replace(/[-_]/g,' ')+' ';

  // CMB 도면의 실제 layer/block code가 저장된 legacy symbol_kind보다 항상 우선한다.
  if(layer.startsWith('CN_C_ONU') || padded.includes(' ONU '))return 'onu';

  if(layer.startsWith('CN_C_AMP') || block.startsWith('AMP') || padded.includes(' AMP '))return 'amp';

  if(layer.startsWith('CN_C_TAP') || block.startsWith('TAP') || padded.includes(' TAP '))return 'tap';

  if(
    block.startsWith('2SP') || padded.includes(' 2SP ') ||
    s.includes('2WAY') || s.includes('2-WAY') ||
    s.includes('2분기') || s.includes('2분배')
  )return 'splitter';

  if(
    block.startsWith('3SP') || padded.includes(' 3SP ') ||
    s.includes('3WAY') || s.includes('3-WAY') ||
    s.includes('3분기') || s.includes('3분배')
  )return 'splitter';

  if(
    layer.startsWith('CN_C_DC') || block.startsWith('DC') ||
    padded.includes(' DC ') || s.includes('DIRECTIONAL COUPLER')
  )return 'splitter';

  if(layer.startsWith('CN_C_PI') || block.startsWith('PI') || padded.includes(' PI '))return 'pi';

  if(
    layer.startsWith('CN_C_POWER') || block.startsWith('PS') ||
    padded.includes(' POWER ') || padded.includes(' PS ')
  )return 'power_ps';

  // 광기기는 layer만으로 묶지 않고 실제 block code를 우선해 구분한다.
  if(block.startsWith('NETOFD') || block.startsWith('NETFDF'))return 'fiber_net';
  if(block.startsWith('RN-') || block==='RN')return 'fiber_rn';
  if(layer.startsWith('CN_F_TERMINAL') || block.startsWith('OIM-'))return 'fiber_terminal';
  if(
    layer.startsWith('CN_F_CLOSURE') ||
    block.startsWith('SPL-') ||
    s.includes('CLOSURE')
  )return 'closure';
  // Center는 Closure와 같은 것으로 강제하지 않는다.
  if(layer.startsWith('CN_F_CENTER') || s.includes(' CENTER '))return 'generic';

  if(s.includes('MANHOLE')||s.includes('맨홀'))return 'manhole';
  if(layer==='CN_L_POLE'||layer.startsWith('CN_L_POLE_POLE')||s.includes('POLE')||s.includes('전주'))return 'pole';

  // Legacy fallback for old server rows without recognizable CMB code.
  if(f._cmb_symbol_kind){{
    const stored=String(f._cmb_symbol_kind).toLowerCase();
    if(stored==='power')return 'power_ps';
    if(['splitter','pi','onu','amp','tap','power_ps','closure','pole','manhole'].includes(stored))return stored;
  }}

  return 'generic';
}}

function rotationDeg(p){{
  const a=p.attributes||{{}};
  const f=a.fields||a;
  const v=Number(f._cmb_rotation_deg ?? 0);
  return Number.isFinite(v)?v:0;
}}

function deviceLabel(p,kind){{
  const layer=String(p.layer||'').trim().toUpperCase();
  const block=String(p.block_name||'').trim().toUpperCase();
  const s=(layer+' '+block+' '+JSON.stringify(p.attributes||{{}})).toUpperCase();
  const padded=' '+s.replace(/[-_]/g,' ')+' ';

  if(kind==='splitter'){{
    if(block.startsWith('3SP')||s.includes('3WAY')||s.includes('3-WAY')||s.includes('3분기')||s.includes('3분배'))return '3';
    if(block.startsWith('2SP')||s.includes('2WAY')||s.includes('2-WAY')||s.includes('2분기')||s.includes('2분배'))return '2';
    if(layer.startsWith('CN_C_DC')||block.startsWith('DC')||padded.includes(' DC ')||s.includes('DIRECTIONAL COUPLER'))return 'DC';
  }}
  if(kind==='fiber_net'){{
    if(block.startsWith('NETOFD'))return 'OFD';
    if(block.startsWith('NETFDF'))return 'FDF';
  }}
  if(kind==='fiber_rn'){{
    if(block.startsWith('RN-8'))return '8RN';
    if(block.startsWith('RN-4'))return '4RN';
  }}
  if(kind==='fiber_terminal'){{
    // 터미널 외형은 동일한 사각형을 사용하고 도면의 block/layer/속성에 있는 L2/L3만 표기한다.
    if(block.startsWith('OIM-L2') || /(^|[^A-Z0-9])L2([^A-Z0-9]|$)/.test(s))return 'L2';
    if(block.startsWith('OIM-L3') || /(^|[^A-Z0-9])L3([^A-Z0-9]|$)/.test(s))return 'L3';
  }}

  return (SYMBOL_LIBRARY[kind]||{{}}).label||'';
}}

function rotatePoint(x,y,cx,cy,deg){{
  const a=deg*Math.PI/180,dx=x-cx,dy=y-cy;
  return [cx+dx*Math.cos(a)-dy*Math.sin(a),cy+dx*Math.sin(a)+dy*Math.cos(a)];
}}

function pxToLatLng(x,y){{
  const prj=map.getProjection();
  return prj.coordsFromPoint(new kakao.maps.Point(x,y));
}}

function latLngToPx(latlng){{
  return map.getProjection().pointFromCoords(latlng);
}}

function deviceScaleForLevel(level){{
  const lv=Number(level||3);
  // 상세 줌에서는 기기가 선로에 묻히지 않도록 기존보다 크게 유지한다.
  if(lv<=1)return 1.65;
  if(lv===2)return 1.35;
  if(lv===3)return 1.12;
  return 0.90;
}}

function fiberArrowScaleForLevel(level){{
  const lv=Number(level||3);
  // 화살표는 기기보다 작게 유지하되 줌 레벨에 따라 단계적으로 조정한다.
  if(lv<=1)return 1.70;
  if(lv===2)return 1.45;
  if(lv===3)return 1.20;
  return 1.00;
}}

function scaledSymbolSpec(kind){{
  const base=SYMBOL_LIBRARY[kind]||SYMBOL_LIBRARY.generic;
  const scale=deviceScaleForLevel(map?map.getLevel():3);
  const d={{...base}};
  if(Number.isFinite(Number(base.w)))d.w=Number(base.w)*scale;
  if(Number.isFinite(Number(base.h)))d.h=Number(base.h)*scale;
  if(Number.isFinite(Number(base.r)))d.r=Number(base.r)*scale;
  d._scale=scale;
  return d;
}}

function polygonPoints(kind,cx,cy,deg=0){{

  const d=scaledSymbolSpec(kind);
  let pts=[];
  if(d.shape==='rect'||d.shape==='square_circle'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx-w,cy-h],[cx+w,cy-h],[cx+w,cy+h],[cx-w,cy+h]];
  }} else if(d.shape==='flat_capsule'){{
    const w=d.w/2,h=d.h/2;
    pts=[
      [cx-w*.38,cy-h],[cx+w*.38,cy-h],
      [cx+w*.78,cy-h*.72],[cx+w,cy],
      [cx+w*.78,cy+h*.72],[cx+w*.38,cy+h],
      [cx-w*.38,cy+h],[cx-w*.78,cy+h*.72],
      [cx-w,cy],[cx-w*.78,cy-h*.72]
    ];
  }} else if(d.shape==='diamond'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx,cy-h],[cx+w,cy],[cx,cy+h],[cx-w,cy]];
  }} else if(d.shape==='closure_box'){{
    const w=d.w/2,h=d.h/2,cut=Math.min(3*d._scale,h*.45);
    pts=[
      [cx-w+cut,cy-h],[cx+w-cut,cy-h],
      [cx+w,cy-h+cut],[cx+w,cy+h-cut],
      [cx+w-cut,cy+h],[cx-w+cut,cy+h],
      [cx-w,cy+h-cut],[cx-w,cy-h+cut]
    ];
  }} else if(d.shape==='triangle'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx,cy-h],[cx+w,cy+h],[cx-w,cy+h]];
  }} else if(d.shape==='hexagon'){{
    const w=d.w/2,h=d.h/2;
    pts=[[cx-w*.55,cy-h],[cx+w*.55,cy-h],[cx+w,cy],[cx+w*.55,cy+h],[cx-w*.55,cy+h],[cx-w,cy]];
  }}
  return pts.map(p=>rotatePoint(p[0],p[1],cx,cy,deg));
}}

function raySegmentIntersection(cx,cy,dx,dy,a,b){{
  const sx=b[0]-a[0],sy=b[1]-a[1];
  const det=(-dx*sy+dy*sx);
  if(Math.abs(det)<1e-9)return null;
  const s=(-sy*(a[0]-cx)+sx*(a[1]-cy))/det;
  const t=( dx*(a[1]-cy)-dy*(a[0]-cx))/det;
  if(s>=0&&t>=0&&t<=1)return [cx+s*dx,cy+s*dy];
  return null;
}}

function boundaryPoint(kind,cx,cy,tx,ty,deg=0){{
  let dx=tx-cx,dy=ty-cy;
  const len=Math.hypot(dx,dy)||1;
  dx/=len;dy/=len;
  const d=scaledSymbolSpec(kind);
  if(kind==='fiber_rn'){{
    // RN은 도형을 그리지 않고 위쪽 텍스트만 표시한다.
  }} else if(d.shape==='circle'||d.shape==='circle_x'||d.shape==='double_circle'){{
    return [cx+dx*d.r,cy+dy*d.r];
  }}
  const pts=polygonPoints(kind,cx,cy,deg);
  let best=null,bestDist=1e9;
  for(let i=0;i<pts.length;i++){{
    const hit=raySegmentIntersection(cx,cy,dx,dy,pts[i],pts[(i+1)%pts.length]);
    if(!hit)continue;
    const dist=Math.hypot(hit[0]-cx,hit[1]-cy);
    if(dist<bestDist){{best=hit;bestDist=dist}}
  }}
  return best||[cx,cy];
}}

function inferDirectionalInputFromFeature(feature,lineFeatures){{
  const p=(feature||{{}}).properties||{{}};
  const kind=symbolKind(p);
  if(!['amp','tap','splitter'].includes(kind))return null;
  const g=(feature||{{}}).geometry||{{}};
  const xy=g.coordinates||[];
  if(!Array.isArray(xy)||xy.length<2)return null;

  const center=new kakao.maps.LatLng(Number(xy[1]),Number(xy[0]));
  const centerPx=latLngToPx(center);
  const a=p.attributes||{{}};
  const fields=a.fields||a;
  const connected=new Set(
    (Array.isArray(fields._cmb_connections)?fields._cmb_connections:[])
      .map(v=>String(v||'').trim().toUpperCase())
      .filter(Boolean)
  );
  const candidates=[];

  (lineFeatures||[]).forEach(f=>{{
    const lp=f.properties||{{}};
    if(String(lp.group_id||'').toUpperCase()!=='COAX')return;
    if(isAnnoFeature(f))return;

    const handle=String(
      lp.source_handle||lp.regional_object_id||lp.entity_id||lp.object_id||''
    ).trim().toUpperCase();
    if(connected.size && handle && !connected.has(handle))return;

    const lg=f.geometry||{{}};
    const parts=lg.type==='MultiLineString'?(lg.coordinates||[]):[lg.coordinates||[]];
    parts.forEach(coords=>{{
      if(!Array.isArray(coords)||coords.length<2)return;
      const clean=coords.filter(x=>Array.isArray(x)&&x.length>=2&&
        Number.isFinite(Number(x[0]))&&Number.isFinite(Number(x[1])));
      if(clean.length<2)return;

      // 케이블의 마지막 좌표가 방향성 기기(AMP/TAP/분기기)에 닿는 경우만 입력으로 인정한다.
      const last=clean[clean.length-1];
      const prev=clean[clean.length-2];
      const lastPx=latLngToPx(new kakao.maps.LatLng(Number(last[1]),Number(last[0])));
      const prevPx=latLngToPx(new kakao.maps.LatLng(Number(prev[1]),Number(prev[0])));
      const dist=Math.hypot(lastPx.x-centerPx.x,lastPx.y-centerPx.y);
      if(dist>32)return;

      let vx=centerPx.x-prevPx.x,vy=centerPx.y-prevPx.y;
      const len=Math.hypot(vx,vy);
      if(len<2)return;
      vx/=len;vy/=len;
      candidates.push({{
        dist,vx,vy,
        color:originalCableColor(lp,'COAX')
      }});
    }});
  }});

  candidates.sort((x,y)=>x.dist-y.dist);
  const best=candidates[0];
  if(!best)return null;
  if(candidates.length>1 && Math.abs(candidates[1].dist-best.dist)<5)return null;

  const signalDeg=(Math.atan2(best.vx,-best.vy)*180/Math.PI+360)%360;
  return {{
    vx:best.vx,vy:best.vy,deg:signalDeg,dist:best.dist,
    color:best.color||'#334155'
  }};
}}

function drawDevice(center,props){{
  const kind=symbolKind(props);
  const d=scaledSymbolSpec(kind);
  const px=latLngToPx(center);
  const cx=px.x,cy=px.y;
  const parts=[];
  const deg=rotationDeg(props);

  if(d.shape==='circle'||d.shape==='circle_x'||d.shape==='double_circle'){{
    const path=[];
    for(let i=0;i<20;i++){{
      const a=Math.PI*2*i/20;
      path.push(pxToLatLng(cx+Math.cos(a)*d.r,cy+Math.sin(a)*d.r));
    }}
    const poly=new kakao.maps.Polygon({{path:path,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillColor:d.fill,fillOpacity:.95}});
    poly.setMap(map);if(typeof poly.setZIndex==='function')poly.setZIndex(30);registerOverlay(poly,props.group_id,kind);parts.push(poly);bindClick(poly,props);
    if(d.shape==='double_circle'){{
      const path2=[];
      for(let i=0;i<20;i++){{
        const a=Math.PI*2*i/20;
        path2.push(pxToLatLng(cx+Math.cos(a)*d.r*.62,cy+Math.sin(a)*d.r*.62));
      }}
      const inner=new kakao.maps.Polygon({{path:path2,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillOpacity:0}});
      inner.setMap(map);if(typeof inner.setZIndex==='function')inner.setZIndex(30);registerOverlay(inner,props.group_id,kind);parts.push(inner);bindClick(inner,props);
    }}
    if(d.shape==='circle_x'){{
      const a1=pxToLatLng(cx-d.r*.7,cy-d.r*.7),a2=pxToLatLng(cx+d.r*.7,cy+d.r*.7);
      const b1=pxToLatLng(cx-d.r*.7,cy+d.r*.7),b2=pxToLatLng(cx+d.r*.7,cy-d.r*.7);
      [ [a1,a2],[b1,b2] ].forEach(path2=>{{
        const l=new kakao.maps.Polyline({{path:path2,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1}});
        l.setMap(map);registerOverlay(l,props.group_id,kind);parts.push(l);bindClick(l,props);
      }});
    }}
  }}else{{
    const pts=polygonPoints(kind,cx,cy,deg).map(p=>pxToLatLng(p[0],p[1]));
    const poly=new kakao.maps.Polygon({{path:pts,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillColor:d.fill,fillOpacity:.95}});
    poly.setMap(map);if(typeof poly.setZIndex==='function')poly.setZIndex(30);registerOverlay(poly,props.group_id,kind);parts.push(poly);bindClick(poly,props);
      if(d.shape==='square_circle'){{
      const rr=Math.min(d.w,d.h)*.42;
      const path2=[];
      for(let i=0;i<24;i++){{
        const a=Math.PI*2*i/24;
        path2.push(pxToLatLng(cx+Math.cos(a)*rr,cy+Math.sin(a)*rr));
      }}
      const inner=new kakao.maps.Polygon({{path:path2,strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1,fillColor:d.innerFill||'#ffffff',fillOpacity:1}});
      inner.setMap(map);if(typeof inner.setZIndex==='function')inner.setZIndex(30);registerOverlay(inner,props.group_id,kind);parts.push(inner);bindClick(inner,props);
    }}
  }}

  // Closure: 좌우 좁은 면 안쪽에 작은 연결 포트 3개씩(총 6개)을 표시한다.
  if(kind==='closure'){{
    const halfW=(Number(d.w)||24)/2;
    const halfH=(Number(d.h)||15)/2;
    const portR=Math.max(0.70,0.82*(d._scale||1));
    const portInset=Math.max(1.35,1.55*(d._scale||1));
    const portX=[-halfW+portInset,halfW-portInset];
    const portY=[-halfH*.46,0,halfH*.46];
    portX.forEach(dx=>portY.forEach(dy=>{{
      const rp=rotatePoint(cx+dx,cy+dy,cx,cy,deg);
      const path=[];
      for(let i=0;i<14;i++){{
        const a=Math.PI*2*i/14;
        path.push(pxToLatLng(rp[0]+Math.cos(a)*portR,rp[1]+Math.sin(a)*portR));
      }}
      const port=new kakao.maps.Polygon({{
        path:path,strokeWeight:1,strokeColor:'#1F4E79',strokeOpacity:1,
        fillColor:'#ffffff',fillOpacity:1
      }});
      port.setMap(map);
      if(typeof port.setZIndex==='function')port.setZIndex(31);
      registerOverlay(port,props.group_id,kind);
      parts.push(port);
      bindClick(port,props);
    }}));
  }} else if(kind!=='fiber_rn' && kind!=='fiber_terminal' && kind!=='fiber_net') {{
    const a=deg*Math.PI/180;
    const dirLen=Math.max(6,(d.r||Math.max(d.w||0,d.h||0)/2)*.9);
    const dirEnd=pxToLatLng(cx+Math.sin(a)*dirLen,cy-Math.cos(a)*dirLen);
    const dirLine=new kakao.maps.Polyline({{path:[center,dirEnd],strokeWeight:2,strokeColor:d.stroke,strokeOpacity:1}});
    dirLine.setMap(map);if(typeof dirLine.setZIndex==='function')dirLine.setZIndex(31);registerOverlay(dirLine,props.group_id,kind);parts.push(dirLine);
  }}

  const labelText=deviceLabel(props,kind);
  if(labelText){{
    const isRn=(kind==='fiber_rn');
    const isRotatingLabel=(kind==='fiber_terminal'||kind==='fiber_net');
    const baseFont=(kind==='fiber_net')?6.6:(isRn?9:10);
    const fontPx=Math.max(kind==='fiber_net'?5:8,Math.round(baseFont*(d._scale||1)));
    const transform=isRn
      ? 'translate(-50%,-180%)'
      : ('translate(-50%,-50%)'+(isRotatingLabel?' rotate('+deg+'deg)':''));
    const label=new kakao.maps.CustomOverlay({{
      position:center,
      content:'<div style="white-space:nowrap;font:700 '+fontPx+'px Malgun Gothic;color:'+esc(d.labelColor||'#00363a')+';transform:'+transform+';transform-origin:center center;pointer-events:none">'+esc(labelText)+'</div>',
      yAnchor:.5,xAnchor:.5
    }});
    label.setMap(map);
    registerOverlay(label,props.group_id,kind);
    parts.push(label);
  }}

  return {{kind,center,cx,cy,props,parts,deg}};
}}

function isDeviceOverlayKind(kind){{
  return [
    'onu','amp','tap','splitter','pi','power','power_ps','closure','fiber_terminal','fiber_rn','fiber_net','pole','manhole','generic',
    'amp_input_arrow','tap_input_arrow','splitter_input_arrow'
  ].includes(String(kind||'').toLowerCase());
}}

function clearDeviceOverlaysOnly(){{
  const kept=[];
  overlays.forEach(x=>{{
    const kind=String(overlayKinds.get(x)||'').toLowerCase();
    if(isDeviceOverlayKind(kind)){{
      try{{x.setMap(null);}}catch(e){{}}
      overlayGroups.delete(x);
      overlayKinds.delete(x);
    }}else{{
      kept.push(x);
    }}
  }});
  overlays=kept;
}}

function redrawDevicesFromMemory(){{
  if(!map)return;
  clearDeviceOverlaysOnly();
  currentDevices=[];

  (currentPointFeatures||[]).forEach(f=>{{
    const p=f.properties||{{}};
    const a=storedPolePosition(f);
    if(!a)return;
    try{{
      const inferred=inferDirectionalInputFromFeature(f,currentLineFeatures||[]);
      if(inferred){{
        const attrs=p.attributes||{{}};
        const fields=attrs.fields||attrs;
        fields._cmb_rotation_deg=inferred.deg;
        p.attributes=attrs;
        p._cmb_directional_input=inferred;
      }}
      currentDevices.push(drawDevice(
        new kakao.maps.LatLng(Number(a[1]),Number(a[0])),p
      ));
    }}catch(e){{console.warn('Device redraw failed',e);}}
  }});

  // 광기기는 persistent FIBER cache에서 별도로 관리되므로
  // 줌 재렌더 시 일반 기기와 함께 반드시 다시 그린다.
  if(groupEnabled.FIBER){{
    (currentFiberPointFeatures||[]).forEach(f=>{{
      const p=f.properties||{{}};
      const a=storedPolePosition(f);
      if(!a)return;
      try{{
        currentDevices.push(drawDevice(
          new kakao.maps.LatLng(Number(a[1]),Number(a[0])),p
        ));
      }}catch(e){{console.warn('Fiber device redraw failed',e);}}
    }});
  }}

  applyDirectionalInputArrows(currentDevices,currentLineFeatures||[]);
  applyZoomVisibility(map.getLevel());
}}

function snapCablePath(coords,devices){{
  if(coords.length<2||!devices.length)return coords.map(a=>new kakao.maps.LatLng(a[1],a[0]));
  const pts=coords.map(a=>new kakao.maps.LatLng(a[1],a[0]));
  const px=pts.map(latlngToPx);
  const threshold=26;

  function snapEnd(index,neighborIndex){{
    let best=null,bestDist=1e9;
    for(const dev of devices){{
      const dist=Math.hypot(px[index].x-dev.cx,px[index].y-dev.cy);
      if(dist<threshold&&dist<bestDist){{best=dev;bestDist=dist}}
    }}
    if(!best)return;
    // 케이블은 기기 중심까지 밀어 넣지 않고 실제 심벌 외곽 경계점에 접속한다.
    // 불투명 심벌이 케이블을 덮어 선이 끊겨 보이는 현상을 줄인다.
    const neighbor=px[neighborIndex];
    const edge=boundaryPoint(
      best.kind,
      best.cx,best.cy,
      neighbor.x,neighbor.y,
      Number(best.deg||0)
    );

    // 표시상 끊김 방지:
    // 실제 연결 판단은 기기 중심 기준을 유지하되, 화면에서는 외곽 경계보다
    // 약간 안쪽(3px)까지 케이블을 연장해 심벌 아래로 겹치게 한다.
    // 이렇게 하면 projection/rounding 오차가 있어도 기기와 케이블 사이에 틈이 생기지 않는다.
    let ex=best.cx-edge[0],ey=best.cy-edge[1];
    const elen=Math.hypot(ex,ey)||1;
    ex/=elen;ey/=elen;
    const overlapPx=3;
    pts[index]=pxToLatLng(edge[0]+ex*overlapPx,edge[1]+ey*overlapPx);
  }}

  snapEnd(0,1);
  snapEnd(pts.length-1,pts.length-2);
  return pts;
}}

function coaxCableOverlayKind(feature,devices){{
  const p=(feature||{{}}).properties||{{}};
  const cableHandle=String(
    p.source_handle||p.regional_object_id||p.entity_id||p.object_id||''
  ).trim().toUpperCase();

  if(!cableHandle)return 'coax_main_cable';

  const taps=(devices||[]).filter(d=>d&&d.kind==='tap');
  for(const tap of taps){{
    const a=(tap.props||{{}}).attributes||{{}};
    const fields=a.fields||a;
    const connected=(Array.isArray(fields._cmb_connections)?fields._cmb_connections:[])
      .map(v=>String(v||'').trim().toUpperCase())
      .filter(Boolean);
    if(connected.includes(cableHandle))return 'coax_tap_cable';
  }}

  return 'coax_main_cable';
}}

function applyDirectionalInputArrows(devices,lineFeatures){{
  let count=0;
  (devices||[]).forEach(dev=>{{
    if(!dev||!['amp','tap','splitter'].includes(dev.kind))return;
    const inferred=(dev.props||{{}})._cmb_directional_input;
    if(!inferred)return;

    const vx=Number(inferred.vx),vy=Number(inferred.vy);
    if(!Number.isFinite(vx)||!Number.isFinite(vy))return;

    // 입력 케이블 끝에서 기기 쪽으로 향하는 V 화살표.
    const tip=[dev.cx-vx*4,dev.cy-vy*4];
    const base=[dev.cx-vx*12,dev.cy-vy*12];
    const px=-vy,py=vx,wing=3;
    const left=[base[0]+px*wing,base[1]+py*wing];
    const right=[base[0]-px*wing,base[1]-py*wing];

    const arrowKind=dev.kind+'_input_arrow';
    [[left,tip],[right,tip]].forEach(seg=>{{
      const l=new kakao.maps.Polyline({{
        path:[pxToLatLng(seg[0][0],seg[0][1]),pxToLatLng(seg[1][0],seg[1][1])],
        strokeWeight:2,
        strokeColor:String(inferred.color||'#334155'),
        strokeOpacity:1,
        strokeStyle:'solid'
      }});
      l.setMap(map);
      if(typeof l.setZIndex==='function')l.setZIndex(32);
      registerOverlay(l,'COAX',arrowKind);
    }});
    count++;
  }});
  return count;
}}

function restoreSelectedCable(){{
  if(selectedCable&&selectedCableStyle){{
    try{{
      selectedCable.setOptions({{
        strokeWeight:selectedCableStyle.strokeWeight,
        strokeColor:selectedCableStyle.strokeColor,
        strokeOpacity:selectedCableStyle.strokeOpacity
      }});
      if(typeof selectedCable.setZIndex==='function')selectedCable.setZIndex(selectedCableStyle.zIndex);
    }}catch(e){{}}
  }}
  (selectedCableArrows||[]).forEach((arrow,index)=>{{
    const style=(selectedCableArrowStyles||[])[index]||{{}};
    try{{
      arrow.setOptions({{
        strokeWeight:Number(style.strokeWeight||1),
        strokeColor:String(style.strokeColor||'#1e88e5'),
        strokeOpacity:Number(style.strokeOpacity??1),
        fillColor:String(style.fillColor||'#1e88e5'),
        fillOpacity:Number(style.fillOpacity??1)
      }});
      if(typeof arrow.setZIndex==='function')arrow.setZIndex(Number(style.zIndex||7));
    }}catch(e){{}}
  }});
  selectedCable=null;
  selectedCableStyle=null;
  selectedCableArrows=[];
  selectedCableArrowStyles=[];
}}

function selectCable(overlay,props,baseColor,baseWeight=4,baseZ=5){{
  if(selectedCable!==overlay)restoreSelectedCable();

  selectedCable=overlay;
  selectedCableStyle={{
    strokeWeight:Number(baseWeight||4),
    strokeColor:String(baseColor||'#334155'),
    strokeOpacity:.95,
    zIndex:Number(baseZ||5)
  }};

  // 선택 케이블은 기기보다 위로 올리고 대비색 + 굵기로 강조한다.
  let highlight='#ff00ff';
  const c=String(baseColor||'').toLowerCase();
  if(c==='#ff00ff'||c==='#f0f'||c==='magenta')highlight='#00ffff';

  try{{
    overlay.setOptions({{
      strokeWeight:Math.max(7,Number(baseWeight||4)+3),
      strokeColor:highlight,
      strokeOpacity:1
    }});
    if(typeof overlay.setZIndex==='function')overlay.setZIndex(60);
  }}catch(e){{}}

  selectedCableArrows=(cableArrows.get(overlay)||[]).slice();
  selectedCableArrowStyles=selectedCableArrows.map(arrow=>{{
    const base=arrow.__cmbBaseStyle||{{}};
    return {{
      strokeWeight:Number(base.strokeWeight||1),
      strokeColor:String(base.strokeColor||baseColor||'#1e88e5'),
      strokeOpacity:Number(base.strokeOpacity??1),
      fillColor:String(base.fillColor||baseColor||'#1e88e5'),
      fillOpacity:Number(base.fillOpacity??1),
      zIndex:Number(base.zIndex||7)
    }};
  }});
  selectedCableArrows.forEach(arrow=>{{
    try{{
      arrow.setOptions({{
        strokeWeight:2,
        strokeColor:highlight,
        strokeOpacity:1,
        fillColor:highlight,
        fillOpacity:1
      }});
      if(typeof arrow.setZIndex==='function')arrow.setZIndex(61);
    }}catch(e){{}}
  }});
  showDetail(props||{{}});
}}

function bindCableClick(overlay,props,baseColor,baseWeight=4,baseZ=5){{
  kakao.maps.event.addListener(overlay,'click',()=>{{
    selectCable(overlay,props,baseColor,baseWeight,baseZ);
  }});
}}

function bindClick(overlay,props){{
  kakao.maps.event.addListener(overlay,'click',()=>showDetail(props||{{}}));
}}

function formatDistance(meters){{
  const m=Number(meters||0);
  if(m>=1000)return (m/1000).toFixed(2)+' km';
  return m.toFixed(m<100?1:0)+' m';
}}

function distancePathMeters(points){{
  let total=0;
  for(let i=1;i<(points||[]).length;i++){{
    total+=distanceMeters(
      points[i-1].getLat(),points[i-1].getLng(),
      points[i].getLat(),points[i].getLng()
    );
  }}
  return total;
}}

function closeDistanceDeleteMenu(){{
  if(distanceDeleteMenu){{
    try{{distanceDeleteMenu.setMap(null);}}catch(e){{}}
    distanceDeleteMenu=null;
  }}
}}

function removeDistanceSession(session){{
  if(!session)return;
  try{{session.line&&session.line.setMap(null);}}catch(e){{}}
  try{{session.label&&session.label.setMap(null);}}catch(e){{}}
  distanceSessions=distanceSessions.filter(x=>x!==session);
  closeDistanceDeleteMenu();
}}

function showDistanceDeleteMenu(session,latlng){{
  closeDistanceDeleteMenu();
  const wrap=document.createElement('div');
  wrap.className='measureDeleteMenu';
  const btn=document.createElement('button');
  btn.textContent='삭제';
  btn.onclick=e=>{{
    e.stopPropagation();
    removeDistanceSession(session);
  }};
  wrap.appendChild(btn);
  distanceDeleteMenu=new kakao.maps.CustomOverlay({{
    position:latlng,
    content:wrap,
    xAnchor:.5,
    yAnchor:1.15,
    zIndex:50
  }});
  distanceDeleteMenu.setMap(map);
}}

function setDistanceMode(on){{
  distanceMode=!!on;
  const btn=document.getElementById('measureDistance');
  if(btn)btn.classList.toggle('on',distanceMode);
  if(distanceMode){{
    distancePoints=[];
    if(activeDistanceLine){{try{{activeDistanceLine.setMap(null);}}catch(e){{}}}}
    if(activeDistanceLabel){{try{{activeDistanceLabel.setMap(null);}}catch(e){{}}}}
    activeDistanceLine=null;
    activeDistanceLabel=null;
    closeDistanceDeleteMenu();
    setStatus('거리 측정 · 지도 클릭으로 점 추가 · Esc로 구간 완료');
  }}else{{
    distancePoints=[];
  }}
}}

function updateActiveDistance(){{
  if(!map||distancePoints.length<1)return;

  if(activeDistanceLine)try{{activeDistanceLine.setMap(null);}}catch(e){{}}
  if(activeDistanceLabel)try{{activeDistanceLabel.setMap(null);}}catch(e){{}}

  if(distancePoints.length>=2){{
    activeDistanceLine=new kakao.maps.Polyline({{
      path:distancePoints.slice(),
      strokeWeight:3,
      strokeColor:'#0f766e',
      strokeOpacity:1,
      strokeStyle:'solid'
    }});
    activeDistanceLine.setMap(map);
    if(typeof activeDistanceLine.setZIndex==='function')activeDistanceLine.setZIndex(45);
  }}else{{
    activeDistanceLine=null;
  }}

  const total=distancePathMeters(distancePoints);
  const content='<div class="measureLabel">'+formatDistance(total)+'</div>';
  activeDistanceLabel=new kakao.maps.CustomOverlay({{
    position:distancePoints[distancePoints.length-1],
    content:content,
    xAnchor:.5,
    yAnchor:1.35,
    zIndex:46
  }});
  activeDistanceLabel.setMap(map);
}}

function addDistancePoint(latlng){{
  if(!distanceMode||!latlng)return;
  distancePoints.push(latlng);
  updateActiveDistance();
}}

function finishDistanceMeasurement(){{
  if(!distanceMode)return;

  if(distancePoints.length>=2 && activeDistanceLine){{
    const session={{
      line:activeDistanceLine,
      label:activeDistanceLabel,
      points:distancePoints.slice(),
      total:distancePathMeters(distancePoints)
    }};
    distanceSessions.push(session);
    kakao.maps.event.addListener(session.line,'rightclick',e=>{{
      showDistanceDeleteMenu(session,e.latLng);
    }});
    setStatus('거리 '+formatDistance(session.total)+' · 완료');
  }}else{{
    if(activeDistanceLine)try{{activeDistanceLine.setMap(null);}}catch(e){{}}
    if(activeDistanceLabel)try{{activeDistanceLabel.setMap(null);}}catch(e){{}}
    setStatus('거리 측정 취소');
  }}

  activeDistanceLine=null;
  activeDistanceLabel=null;
  distancePoints=[];
  setDistanceMode(false);
}}

function clearAllDistanceMeasurements(){{
  if(activeDistanceLine)try{{activeDistanceLine.setMap(null);}}catch(e){{}}
  if(activeDistanceLabel)try{{activeDistanceLabel.setMap(null);}}catch(e){{}}
  activeDistanceLine=null;
  activeDistanceLabel=null;
  distancePoints=[];
  distanceSessions.forEach(session=>{{
    try{{session.line&&session.line.setMap(null);}}catch(e){{}}
    try{{session.label&&session.label.setMap(null);}}catch(e){{}}
  }});
  distanceSessions=[];
  closeDistanceDeleteMenu();
  setDistanceMode(false);
  setStatus('거리 측정 전체 삭제');
}}

function distanceMeters(lat1,lng1,lat2,lng2){{
  const R=6371000;
  const p1=lat1*Math.PI/180,p2=lat2*Math.PI/180;
  const dp=(lat2-lat1)*Math.PI/180;
  const dl=(lng2-lng1)*Math.PI/180;
  const a=Math.sin(dp/2)*Math.sin(dp/2)+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)*Math.sin(dl/2);
  return 2*R*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
}}

function coaxKindVisibleAtLevel(kind,mapLevel){{
  if(mapLevel===3){{
    return [
      'onu','amp','amp_input_arrow',
      'splitter','splitter_input_arrow','power','power_ps','closure',
      'coax_main_cable'
    ].includes(kind);
  }}
  if(mapLevel===2){{
    return [
      'onu','amp','amp_input_arrow','tap_input_arrow',
      'splitter','splitter_input_arrow','power','power_ps','closure',
      'tap','pi','generic','coax_main_cable','coax_tap_cable'
    ].includes(kind);
  }}
  return mapLevel<=1;
}}

function deviceVisibleAtLevel(feature,mapLevel){{
  const p=feature.properties||{{}};
  const group=String(p.group_id||'').toUpperCase();
  if(group!=='COAX')return true;
  return coaxKindVisibleAtLevel(symbolKind(p),mapLevel);
}}

function applyZoomVisibility(mapLevel){{
  overlays.forEach(x=>{{
    const group=String(overlayGroups.get(x)||'').toUpperCase();
    const kind=String(overlayKinds.get(x)||'').toLowerCase();

    let visible=true;
    if(group==='FIBER'){{
      visible=groupEnabled.FIBER===true;
      // 광 선로는 계속 표시하고 광 기기는 L3부터 표시한다.
      if(visible && kind)visible=(mapLevel<=3);
    }}else if(group==='COAX' && kind==='cell_boundary'){{
      visible=groupEnabled.COAX===true && mapLevel<=5;
    }}else if(group==='COAX' && kind==='cell_number'){{
      visible=groupEnabled.COAX===true && mapLevel<=4;
    }}else if(mapLevel>3){{
      visible=false;
    }}else if(kind){{
      visible=groupEnabled[group]===true;
      if(visible && group==='COAX'){{
        visible=coaxKindVisibleAtLevel(kind,mapLevel);
      }}
    }}else{{
      visible=groupEnabled[group]===true;
    }}

    try{{x.setMap(visible?map:null);}}catch(e){{}}
  }});
  selectedOverlay=null;
  if(selectedCable){{
    const g=String(overlayGroups.get(selectedCable)||'').toUpperCase();
    if(!groupEnabled[g] || (g!=='FIBER' && mapLevel>3))restoreSelectedCable();
  }}
}}

function isCellBoundaryFeature(f){{
  const p=f.properties||{{}};
  const layer=String(p.layer||'').trim().toUpperCase();
  return layer.startsWith('CN_C_CELLBOUND') || layer.includes('CELLBOUND');
}}

function isCellNumberFeature(f){{
  const p=f.properties||{{}};
  const layer=String(p.layer||'').trim().toUpperCase();
  return layer.startsWith('CN_C_CELLNO') || layer.includes('CELLNO');
}}

function cellNumberText(p){{
  const a=p.attributes||{{}},f=a.fields||a,d=f._cmb_dxf_data||{{}};
  const candidates=[
    f.CELLNO,f.CELL_NO,f.CELLNUMBER,f.CELL_NUMBER,
    f.NO,f.NUMBER,f.NAME,f.TEXT,f.LABEL,
    d.text,d.TEXT,d.tag,d.TAG,
    p.name,p.block_name
  ];
  for(const v of candidates){{
    if(v!==null&&v!==undefined&&String(v).trim()!=='')return String(v).trim();
  }}
  return '';
}}

function renderCellNumberFeature(f){{
  const g=f.geometry||{{}},p=f.properties||{{}};
  if(g.type!=='Point')return null;
  const xy=g.coordinates||[];
  if(!Array.isArray(xy)||xy.length<2||
     !Number.isFinite(Number(xy[0]))||!Number.isFinite(Number(xy[1])))return null;
  const text=cellNumberText(p);
  if(!text)return null;
  const content='<div style="background:rgba(255,255,255,.88);border:1px solid #b91c1c;border-radius:3px;padding:2px 6px;font:700 22px Malgun Gothic;color:#d00000;white-space:nowrap;pointer-events:none">'+esc(text)+'</div>';
  const o=new kakao.maps.CustomOverlay({{
    position:new kakao.maps.LatLng(Number(xy[1]),Number(xy[0])),
    content:content,
    xAnchor:.5,yAnchor:.5,zIndex:24
  }});
  o.setMap(map);
  registerOverlay(o,'COAX','cell_number');
  return o;
}}

function renderFiberPointFallback(features){{
  if(!map||map.getLevel()>3||!groupEnabled.FIBER)return 0;
  let count=0;
  const seen=new Set();
  (features||[]).forEach(f=>{{
    if((f.geometry||{{}}).type!=='Point')return;
    const p=f.properties||{{}};
    if(String(p.group_id||'').toUpperCase()!=='FIBER')return;
    if(isInfoPointFeature(f)||isConnectorFeature(f))return;

    const a=p.attributes||{{}},fields=a.fields||a;
    if(fields._cmb_is_device===false)return;

    const kind=symbolKind(p);
    const entityType=String(p.entity_type||'').toUpperCase();
    const explicitDevice=(fields._cmb_is_device===true);
    if(kind==='generic' && entityType!=='INSERT' && !explicitDevice)return;
    const xy=storedPolePosition(f);
    if(!xy)return;
    const key=kind+'|'+Number(xy[0]).toFixed(6)+'|'+Number(xy[1]).toFixed(6);
    if(seen.has(key))return;
    seen.add(key);
    try{{
      drawDevice(new kakao.maps.LatLng(Number(xy[1]),Number(xy[0])),p);
      count++;
    }}catch(e){{console.warn('Fiber fallback device render failed',e);}}
  }});
  return count;
}}

function drawFiberInputArrow(path,color,cableOverlay,props){{
  if(!map||typeof map.getProjection!=='function'||!Array.isArray(path)||path.length<2)return null;
  const tipLatLng=path[path.length-1];
  const prevLatLng=path[path.length-2];
  const tipPx=latLngToPx(tipLatLng);
  const prevPx=latLngToPx(prevLatLng);
  let vx=tipPx.x-prevPx.x,vy=tipPx.y-prevPx.y;
  const len=Math.hypot(vx,vy);
  if(!Number.isFinite(len)||len<2)return null;
  vx/=len;vy/=len;

  // 광케이블 입력방향은 채워진 삼각형 화살촉으로 표시한다.
  // 줌 변경 때 재생성하며 레벨별 크기를 적용한다.
  const arrowScale=fiberArrowScaleForLevel(map.getLevel());
  const tipOffset=4*arrowScale;
  const baseOffset=17*arrowScale;
  const wing=5.5*arrowScale;
  const tip=[tipPx.x-vx*tipOffset,tipPx.y-vy*tipOffset];
  const baseCenter=[tipPx.x-vx*baseOffset,tipPx.y-vy*baseOffset];
  const px=-vy,py=vx;
  const left=[baseCenter[0]+px*wing,baseCenter[1]+py*wing];
  const right=[baseCenter[0]-px*wing,baseCenter[1]-py*wing];

  const c=String(color||'#1e88e5');
  const arrow=new kakao.maps.Polygon({{
    path:[
      pxToLatLng(tip[0],tip[1]),
      pxToLatLng(left[0],left[1]),
      pxToLatLng(right[0],right[1])
    ],
    strokeWeight:1,
    strokeColor:c,
    strokeOpacity:1,
    fillColor:c,
    fillOpacity:1
  }});
  arrow.__cmbBaseStyle={{
    strokeWeight:1,strokeColor:c,strokeOpacity:1,
    fillColor:c,fillOpacity:1,zIndex:7
  }};
  arrow.setMap(map);
  if(typeof arrow.setZIndex==='function')arrow.setZIndex(7);
  registerOverlay(arrow,'FIBER','fiber_input_arrow');

  if(cableOverlay){{
    const items=cableArrows.get(cableOverlay)||[];
    items.push(arrow);
    cableArrows.set(cableOverlay,items);
    kakao.maps.event.addListener(arrow,'click',()=>{{
      selectCable(cableOverlay,props||{{}},c,4,5);
    }});
  }}
  return arrow;
}}

function redrawFiberArrowsForZoom(){{
  if(!map||!cableArrows.size)return;
  const records=[];
  for(const [cable,arrows] of cableArrows.entries()){{
    try{{
      const path=typeof cable.getPath==='function'?cable.getPath():null;
      if(path&&path.length>=2){{
        records.push({{
          cable,
          path,
          color:String(cable.__cmbBaseColor||'#1e88e5'),
          props:cable.__cmbFiberProps||{{}}
        }});
      }}
    }}catch(e){{}}
    (arrows||[]).forEach(arrow=>{{
      try{{arrow.setMap(null);}}catch(e){{}}
      const idx=overlays.indexOf(arrow);
      if(idx>=0)overlays.splice(idx,1);
      overlayGroups.delete(arrow);
      overlayKinds.delete(arrow);
    }});
  }}
  cableArrows.clear();
  records.forEach(r=>drawFiberInputArrow(r.path,r.color,r.cable,r.props));
}}

function renderFiberFeatures(features){{
  if(!map)return 0;
  clearGroupOverlays('FIBER');
  if(!groupEnabled.FIBER){{
    currentFiberPointFeatures=[];
    return 0;
  }}
  let rendered=0;
  let lineObjects=0;
  (features||[]).forEach(f=>{{
    const g=f.geometry||{{}};
    const p=f.properties||{{}};
    if(String(p.group_id||'').toUpperCase()!=='FIBER')return;
    if(isAnnoFeature(f))return;
    if(!['LineString','MultiLineString'].includes(g.type))return;
    lineObjects++;
    const c=originalCableColor(p,'FIBER');
    const parts=g.type==='MultiLineString' ? (g.coordinates||[]) : [g.coordinates||[]];
    parts.forEach(before=>{{
      if(!Array.isArray(before))return;
      const path=before.filter(a=>Array.isArray(a)&&a.length>=2&&
        a[0]!==null&&a[1]!==null&&a[0]!==''&&a[1]!==''&&
        Number.isFinite(Number(a[0]))&&Number.isFinite(Number(a[1]))&&
        Math.abs(Number(a[0]))<=180&&Math.abs(Number(a[1]))<=90)
        .map(a=>new kakao.maps.LatLng(Number(a[1]),Number(a[0])));
      if(path.length<2)return;
      const l=new kakao.maps.Polyline({{
        path:path,
        strokeWeight:4,
        strokeColor:c,
        strokeOpacity:.95,
        strokeStyle:'solid'
      }});
      l.setMap(map);
      if(typeof l.setZIndex==='function')l.setZIndex(5);
      registerOverlay(l,'FIBER');
      l.__cmbFiberProps=p;
      l.__cmbBaseColor=c;
      bindCableClick(l,p,c,4,5);
      drawFiberInputArrow(path,c,l,p);
      rendered++;
    }});
  }});

  // FIBER 캐시에는 광선로뿐 아니라 광함체/센터/터미널 등 Point 기기도 포함된다.
  // 이 Point들은 서버 재호출 없이 캐시에서 미리 생성하고 줌 레벨로 표시/숨김한다.
  let fiberDeviceObjects=0;
  const fiberDeviceMap=new Map();
  (features||[]).forEach(f=>{{
    if((f.geometry||{{}}).type!=='Point')return;
    const p=f.properties||{{}};
    if(String(p.group_id||'').toUpperCase()!=='FIBER')return;
    if(isInfoPointFeature(f))return;

    const a=p.attributes||{{}},fields=a.fields||a;
    if(fields._cmb_is_device===false)return;

    const kind=symbolKind(p);
    const entityType=String(p.entity_type||'').toUpperCase();
    const explicitDevice=(fields._cmb_is_device===true);
    if(kind==='generic' && entityType!=='INSERT' && !explicitDevice)return;

    const xy=storedPolePosition(f);
    if(!xy)return;

    const key=kind+'|'+Number(xy[0]).toFixed(5)+'|'+Number(xy[1]).toFixed(5);
    if(!fiberDeviceMap.has(key))fiberDeviceMap.set(key,f);
  }});

  currentFiberPointFeatures=[...fiberDeviceMap.values()];

  currentFiberPointFeatures.forEach(f=>{{
    const p=f.properties||{{}},xy=storedPolePosition(f);
    if(!xy)return;
    try{{
      drawDevice(new kakao.maps.LatLng(Number(xy[1]),Number(xy[0])),p);
      fiberDeviceObjects++;
    }}catch(e){{console.warn('Fiber device render failed',e);}}
  }});

  applyZoomVisibility(map.getLevel());
  fiberDiag.lineObjects=lineObjects;
  fiberDiag.renderParts=rendered;
  fiberDiag.deviceObjects=fiberDeviceObjects;
  return rendered;
}}

async function pollFiberProgress(region,token){{
  while(token.active && region===document.getElementById('region').value){{
    try{{
      const p=await apiCall('fiber_progress');
      if(!token.active||region!==document.getElementById('region').value)return;
      const pct=Math.max(30,Math.min(79,Number(p.percent||30)));
      const received=Number(p.received||0);
      const expected=Number(p.expected||0);
      const requests=Number(p.requests||0);
      const countText=expected>0
        ? ('수신 '+received.toLocaleString()+' / '+expected.toLocaleString()+'개')
        : ('수신 '+received.toLocaleString()+'개');
      setWorkStatus(
        'L'+map.getLevel()+' · REGION '+region+
        ' · STAGE 광 전체 동기화 · '+countText+
        ' · 서버요청 '+requests+'회',
        pct,
        true
      );
      if(p.active===false)return;
    }}catch(e){{}}
    await new Promise(resolve=>setTimeout(resolve,400));
  }}
}}

async function loadRegionFiber(syncForce=false){{
  const region=document.getElementById('region').value;
  if(!region||!groupEnabled.FIBER)return 0;

  // 자동 지역 진입은 기존 지역 광 캐시를 즉시 표시한다.
  // 수동 새로고침(syncForce=true)은 끊긴/불완전 캐시를 다시 그리지 않고
  // 서버의 지역 광 전체를 강제로 재수신한 뒤 정상 수신본으로 교체한다.
  if(!syncForce){{
    try{{
      setWorkStatus('L'+map.getLevel()+' · REGION '+region+' · STAGE 새 지역 광 캐시 확인',10,true);
      const cached=await apiCall('fiber_cached');
      if(region!==document.getElementById('region').value)return 0;
      const cachedFeatures=(cached&&cached.features)||[];
      if(cachedFeatures.length){{
        renderFiberFeatures(cachedFeatures);
        fiberDiag.cache=cachedFeatures.length;
        viewDiag.stage='광 지역 캐시 표시';
        viewDiag.progress=String(cachedFeatures.length)+'개';
        setWorkStatus('L'+map.getLevel()+' · '+viewDiagText()+fiberDiagText(),25,false);
      }}
    }}catch(e){{}}
  }}

  // 서버 revision과 동기화한다.
  // syncForce=true이면 revision 동일 여부와 관계없이 지역 광 전체를 다시 받는다.
  viewDiag.stage=syncForce?'광 전체 강제 재수신':'광 지역 동기화';
  viewDiag.progress=syncForce?'기존 캐시 무시 · 서버 전체 재조회':'서버 최신상태 확인';
  setWorkStatus('L'+map.getLevel()+' · '+viewDiagText()+fiberDiagText(),syncForce?35:40,true);

  const progressToken={{active:true}};
  const progressPromise=pollFiberProgress(region,progressToken);
  const fresh=await apiCall('fiber_all',{{force:!!syncForce}});
  progressToken.active=false;
  await progressPromise.catch(()=>{{}});
  if(region!==document.getElementById('region').value)return 0;
  if(!fresh||fresh.ok===false){{
    if(fresh&&fresh.cancelled)return 0;
    if(fresh&&fresh.error)setWorkStatus(fresh.error+' · 기존 광 캐시 유지',100,false);
    return 0;
  }}

  const features=(fresh.features||[]);
  if(features.length){{
    renderFiberFeatures(features);
    fiberDiag.cache=features.length;
  }}
  viewDiag.stage=syncForce?'광 전체 새로고침 완료':'광 지역 동기화 완료';
  viewDiag.progress=String(features.length)+'개 · '+String(fresh.cache||'network');
  setWorkStatus('L'+map.getLevel()+' · '+viewDiagText()+fiberDiagText(),75,false);
  return features.length;
}}

async function loadFiberViewport(force=false){{
  const region=document.getElementById('region').value;
  if(!region||!map||!groupEnabled.FIBER)return 0;

  const center=map.getCenter();
  const cLat=Number(center.getLat()),cLng=Number(center.getLng());

  if(!force && Number.isFinite(lastFiberQueryLat) && Number.isFinite(lastFiberQueryLng)){{
    const moved=distanceMeters(lastFiberQueryLat,lastFiberQueryLng,cLat,cLng);
    if(moved<QUERY_RECENTER_METERS)return 0;
  }}

  const generation=++fiberViewportGeneration;
  const bbox=queryBoundsFromCenter(cLat,cLng);
  const west=bbox.west,south=bbox.south,east=bbox.east,north=bbox.north;

  viewDiag.region=region;
  viewDiag.centerLat=cLat;
  viewDiag.centerLng=cLng;
  viewDiag.stage='광 좌표 조회';
  viewDiag.progress='조회 반경 '+String(QUERY_RADIUS_METERS)+'m';
  setStatus('L'+map.getLevel()+' · '+viewDiagText()+fiberDiagText());

  const r=await apiCall('fiber_bbox',{{west,south,east,north,force}});
  if(generation!==fiberViewportGeneration)return 0;
  if(region!==document.getElementById('region').value)return 0;

  if(!r||r.ok===false){{
    if(r&&r.error)setStatus(r.error+' · 기존 광 표시 유지');
    return 0;
  }}

  lastFiberQueryLat=cLat;
  lastFiberQueryLng=cLng;
  const features=(r.features||[]);
  let rendered=0;
  if(features.length){{
    rendered=renderFiberFeatures(features);
    fiberDiag.cache=features.length;
  }}

  viewDiag.stage=r.refresh_pending?'광 캐시 표시':'광 좌표 완료';
  viewDiag.progress=
    String(features.length)+'개 · '+(r.cache==='stale'?'서버 갱신중':String(r.cache||'network'));
  setStatus('L'+map.getLevel()+' · '+viewDiagText()+fiberDiagText());

  // 캐시가 있으면 즉시 표시하고 서버 갱신은 백그라운드 1회만 수행한다.
  // 동일 위치에서 강제 재조회하지 않아 이동 반응을 막지 않는다.
  return rendered;
}}

function queueNonFiberLoad(force=false,delay=120){{
  if(nonFiberLoadTimer){{
    clearTimeout(nonFiberLoadTimer);
    nonFiberLoadTimer=null;
  }}
  nonFiberLoadTimer=setTimeout(()=>{{
    nonFiberLoadTimer=null;
    loadObjects(force);
  }},Math.max(0,Number(delay)||0));
}}

async function loadObjects(force=false){{
  const region=document.getElementById('region').value;
  if(!region||!map)return;
  const center=map.getCenter();
  const queryLat=Number(center.getLat());
  const queryLng=Number(center.getLng());
  const mapLevelNow=map.getLevel();
  const detailMode=mapLevelNow<=3;
  const networkQueryMode=mapLevelNow<=5;
  // L6 이상은 광 캐시만 유지한다. L4~L5는 셀경계 조회를 위해 주변 객체를 계속 읽는다.
  if(!networkQueryMode){{
    applyZoomVisibility(mapLevelNow);
    lastQueryLat=queryLat;
    lastQueryLng=queryLng;
    lastDetailMode=false;
    setStatus('L'+mapLevelNow+' · 광 캐시 표시'+fiberDiagText());
    return;
  }}

  if(!force && Number.isFinite(lastQueryLat) && Number.isFinite(lastQueryLng)){{
    const moved=distanceMeters(lastQueryLat,lastQueryLng,queryLat,queryLng);
    if(moved<QUERY_RECENTER_METERS && lastDetailMode===detailMode){{
      setWorkStatus(
        'L'+mapLevelNow+' · REGION '+region+' · 이동 '+Math.round(moved)+'m / '+QUERY_RECENTER_METERS+'m · 기존 동축 캐시 유지',
        100,
        false
      );
      return;
    }}
  }}

  const myGeneration=++loadGeneration;
  const bbox=queryBoundsFromCenter(queryLat,queryLng);
  const west=bbox.west,south=bbox.south,east=bbox.east,north=bbox.north;

  viewDiag.region=region;
  viewDiag.centerLat=queryLat;
  viewDiag.centerLng=queryLng;
  viewDiag.stage='OBJECT 조회';
  viewDiag.progress='COAX/CONDUIT/POLE';
  setWorkStatus('L'+mapLevelNow+' · '+viewDiagText(),85,true);
  const r=await apiCall('objects',{{west:west,south:south,east:east,north:north}});
  if(myGeneration!==loadGeneration)return;
  if(region!==document.getElementById('region').value)return;
  if(r.error){{setStatus(r.error);return}}
  lastQueryLat=queryLat;
  lastQueryLng=queryLng;
  lastDetailMode=detailMode;
  const previousOverlays=overlays.filter(x=>overlayGroups.get(x)!=='FIBER');
  overlays=overlays.filter(x=>overlayGroups.get(x)==='FIBER');
  selectedOverlay=null;
  const allFeatures=r.features||[];
  const mapLevel=map.getLevel();
  const isMaxDetail=mapLevel<=3;
  const features=allFeatures.filter(f=>{{
    const p=f.properties||{{}};
    const layerName=String(p.layer||'').trim().toUpperCase();
    if(layerName.startsWith('TS_')||layerName==='TL_SCCO_SIG'||isAnnoFeature(f)||isConnectorFeature(f)) return false;

    const group=String(p.group_id||'').toUpperCase();
    if(group==='FIBER')return false;

    if(group==='COAX' && groupEnabled.COAX===true){{
      if(isCellBoundaryFeature(f))return mapLevel<=5;
      if(isCellNumberFeature(f))return mapLevel<=4;
    }}
    return isMaxDetail && groupEnabled[group]===true;
  }});
  function deviceFeatureKey(f){{
    const p=f.properties||{{}};
    const a=storedPolePosition(f);
    const kind=symbolKind(p);
    // 새 데이터는 저장된 한전주 좌표를 기기 위치 키로 사용한다.
    if(a){{
      return kind+'|'+Number(a[0]).toFixed(5)+'|'+Number(a[1]).toFixed(5);
    }}
    const direct=String(
      p.regional_object_id || p.entity_id || p.object_id || p.source_handle || ''
    ).trim();
    return kind+'|'+direct+'|'+String(p.layer||'')+'|'+String(p.block_name||'');
  }}

  const pointCandidates=features.filter(f=>{{
    if((f.geometry||{{}}).type!=='Point')return false;
    const p=f.properties||{{}},a=p.attributes||{{}},fields=a.fields||a;
    if(isCellNumberFeature(f))return false;
    if(isInfoPointFeature(f))return false;
    if(isConnectorFeature(f))return false;

    const kind=symbolKind(p);
    const entityType=String(p.entity_type||'').toUpperCase();

    // 명시적으로 기기가 아니라고 저장된 객체만 제외한다.
    if(fields._cmb_is_device===false)return false;

    // 구버전/기존 서버 데이터는 기기 POINT이면서 심벌 힌트가 attributes에만 있을 수 있다.
    // 명시적 _cmb_is_device=true이면 generic이라도 기기 후보를 유지한다.
    const explicitDevice=(fields._cmb_is_device===true);
    if(kind==='generic' && entityType!=='INSERT' && !explicitDevice)return false;

    return true;
  }});

  // 동일 기기는 지도에 반드시 1개만 존재한다.
  const deviceFeatureMap=new Map();
  pointCandidates.forEach(f=>{{
    const key=deviceFeatureKey(f);
    if(!deviceFeatureMap.has(key))deviceFeatureMap.set(key,f);
  }});
  const pointFeatures=[...deviceFeatureMap.values()];

  const lineFeatures=features.filter(f=>['LineString','MultiLineString'].includes((f.geometry||{{}}).type));
  currentPointFeatures=pointFeatures.slice();
  currentLineFeatures=lineFeatures.slice();
  const devices=[];

  pointFeatures.forEach(f=>{{
    const p=f.properties||{{}};
    const a=storedPolePosition(f);
    if(!a)return;
    try{{
      const inferred=inferDirectionalInputFromFeature(f,lineFeatures);
      if(inferred){{
        const attrs=p.attributes||{{}};
        const fields=attrs.fields||attrs;
        fields._cmb_rotation_deg=inferred.deg;
        p.attributes=attrs;
        p._cmb_directional_input=inferred;
      }}
      devices.push(drawDevice(new kakao.maps.LatLng(Number(a[1]),Number(a[0])),p));
    }}
    catch(e){{console.warn('Device render failed',e);}}
  }});

  currentDevices=devices.slice();

  // 모든 기기는 메모리에 만들어 두고 현재 줌 레벨 정책에 따라 즉시 표시/숨김한다.
  applyZoomVisibility(mapLevel);

  let renderedLines=0;
  const renderedByGroup={{FIBER:0,COAX:0,CONDUIT:0,POLE:0,USER:0}};

  lineFeatures.forEach(f=>{{
    const g=f.geometry||{{}};
    const p=f.properties||{{}};
    const group=String(p.group_id||'').toUpperCase();
    const c=originalCableColor(p,group);
    const parts=g.type==='MultiLineString' ? (g.coordinates||[]) : [g.coordinates||[]];

    parts.forEach(before=>{{
      if(!Array.isArray(before))return;

      // 원본 좌표를 먼저 정상화한다.
      const validCoords=before.filter(a=>Array.isArray(a)&&a.length>=2&&
        a[0]!==null&&a[1]!==null&&a[0]!==''&&a[1]!==''&&
        Number.isFinite(Number(a[0]))&&Number.isFinite(Number(a[1]))&&
        Math.abs(Number(a[0]))<=180&&Math.abs(Number(a[1]))<=90)
        .map(a=>[Number(a[0]),Number(a[1])]);
      const originalPath=validCoords.map(a=>new kakao.maps.LatLng(a[1],a[0]));

      if(originalPath.length<2)return;

      // 스냅은 보조 기능이다. 스냅 결과가 잘못되면 반드시 원본 선을 사용한다.
      let path=originalPath;
      try{{
        const snappedPath=snapCablePath(validCoords,devices);
        if(Array.isArray(snappedPath)&&snappedPath.length>=2&&snappedPath.every(a=>
          a&&typeof a.getLat==='function'&&typeof a.getLng==='function'&&
          Number.isFinite(a.getLat())&&Number.isFinite(a.getLng())&&
          Math.abs(a.getLat())<=90&&Math.abs(a.getLng())<=180))path=snappedPath;
      }}catch(e){{
        path=originalPath;
      }}

      let cableKind='';
      if(group==='COAX'){{
        cableKind=isCellBoundaryFeature(f)?'cell_boundary':coaxCableOverlayKind(f,devices);
      }}
      const isCellBoundary=(group==='COAX' && cableKind==='cell_boundary');
      const l=new kakao.maps.Polyline({{
        path:path,
        strokeWeight:isCellBoundary?3:4,
        strokeColor:isCellBoundary?'#f3a6bd':c,
        strokeOpacity:isCellBoundary?.90:.95,
        // Kakao dashed style uses visually longer segments than dotted patterns.
        strokeStyle:isCellBoundary?'dash':'solid'
      }});
      l.setMap(map);
      if(typeof l.setZIndex==='function')l.setZIndex(isCellBoundary?3:5);
      registerOverlay(l,group,cableKind);
      if(['FIBER','COAX','CONDUIT'].includes(group)){{
        bindCableClick(l,p,c,4,5);
      }}else{{
        bindClick(l,p);
      }}

      renderedLines++;
      if(renderedByGroup[group]===undefined)renderedByGroup[group]=0;
      renderedByGroup[group]++;
    }});
  }});

  let cellNumberCount=0;
  if(mapLevel<=4 && groupEnabled.COAX){{
    allFeatures.filter(isCellNumberFeature).forEach(f=>{{
      if(renderCellNumberFeature(f))cellNumberCount++;
    }});
  }}

  const fiberFallbackDevices=renderFiberPointFallback(allFeatures);
  const directionalInputArrows=applyDirectionalInputArrows(devices,lineFeatures);
  applyZoomVisibility(mapLevel);

  previousOverlays.forEach(x=>{{
    try{{x.setMap(null);}}catch(e){{}}
    overlayGroups.delete(x);
  }});
  const visibleGroups=Object.keys(groupEnabled).filter(k=>groupEnabled[k]&&k!=='USER').join('/');
  const rawGroups={{}};
  allFeatures.forEach(f=>{{
    const g=String(((f.properties||{{}}).group_id)||'NONE').toUpperCase();
    rawGroups[g]=(rawGroups[g]||0)+1;
  }});
  const rawText=Object.keys(rawGroups).sort().map(k=>k+':'+rawGroups[k]).join('/');

  const geomStats={{}};
  allFeatures.forEach(f=>{{
    const group=String(((f.properties||{{}}).group_id)||'NONE').toUpperCase();
    const type=String(((f.geometry||{{}}).type)||'');
    if(!geomStats[group])geomStats[group]={{line:0,point:0,other:0}};
    if(type==='LineString'||type==='MultiLineString')geomStats[group].line++;
    else if(type==='Point')geomStats[group].point++;
    else geomStats[group].other++;
  }});
  const cableDiag=['FIBER','COAX','CONDUIT'].map(g=>{{
    const s=geomStats[g]||{{line:0,point:0,other:0}};
    return g+' 선:'+s.line+'/점:'+s.point;
  }}).join(' · ');

  viewDiag.stage=r.refresh_pending?'OBJECT 캐시+갱신':'OBJECT 완료';
  viewDiag.progress='PENDING '+String(r.pending_cells||0);
  setStatus(
    'L'+map.getLevel()+
    ' · '+viewDiagText()+
    ' · '+(r.cache==='stale'?'기존 캐시 즉시 표시 · 서버 갱신중':'캐시/서버 반영')+
    ' · 서버 '+allFeatures.length+'개 ['+rawText+']'+
    ' · '+cableDiag+
    ' · 표시 '+features.length+
    ' · 심볼 '+devices.length+
    ' · 광기기보강 '+fiberFallbackDevices+
    ' · 광기기메모리 '+String((currentFiberPointFeatures||[]).length)+
    ' · 셀번호 '+cellNumberCount+
    ' · 입력화살표 '+directionalInputArrows+
    ' · 렌더선 '+renderedLines+
    ' [F:'+String(renderedByGroup.FIBER||0)+
    '/C:'+String(renderedByGroup.COAX||0)+
    '/D:'+String(renderedByGroup.CONDUIT||0)+']'
  );

  if(r.refresh_pending){{
    setTimeout(()=>loadObjects(true),900);
  }}
}}

async function loadRegions(){{
  const r=await apiCall('regions');
  if(!r.ok){{setStatus('지역 조회 실패 · '+(r.error||'서버 오류'));return}}
  const sel=document.getElementById('region');
  const items=(r.items||[]).filter(x=>x&&x.id);
  authorizedRegions=items.map(x=>({{
    id:String(x.id),
    name:String(x.name||x.id),
    bounds:x.bounds||null
  }}));
  sel.innerHTML='<option value="">지역 선택</option>';
  authorizedRegions.forEach(x=>{{
    const o=document.createElement('option');
    o.value=x.id;
    o.text=x.name!==x.id ? (x.name+' ('+x.id+')') : x.id;
    sel.appendChild(o);
  }});
  if(!authorizedRegions.length){{
    setStatus('권한 지역 0개 · 관리자 지역 권한 설정을 확인하세요 · 등급 '+String(r.level||'?'));
    return;
  }}
  setStatus('권한 지역 '+authorizedRegions.length+'개 · 지역을 선택하세요');
}}

async function activateRegion(region){{
  region=String(region||'');
  const sel=document.getElementById('region');
  if(!region)return false;

  const info=authorizedRegions.find(x=>x.id===region);
  if(!info){{
    sel.value=activeRegionId||'';
    setStatus('권한이 없는 지역입니다');
    return false;
  }}
  if(activeRegionId===region && !regionSwitching)return true;

  const mySwitch=++regionSwitchGeneration;
  regionSwitching=true;

  // 새 지역을 선택하는 순간 이전 지역 화면/재렌더 메모리를 즉시 제거한다.
  clearOverlays();
  activeRegionId='';
  document.getElementById('detail').style.display='none';
  sel.value=region;
  setWorkStatus('지역 전환 · 이전 지역 취소/숨김 · '+region,5,true);

  try{{
    const r=await apiCall('select',{{region:region}});
    if(mySwitch!==regionSwitchGeneration)return false;
    if(!r.ok){{
      sel.value='';
      setWorkStatus(r.error||'지역 연결 실패',100,false);
      return false;
    }}

    activeRegionId=region;
    viewDiag.region=region;
    viewDiag.stage='새 지역 캐시 준비';
    viewDiag.progress=(info?info.name:region);
    setWorkStatus('L'+map.getLevel()+' · '+viewDiagText(),10,true);

    lastQueryLat=null;
    lastQueryLng=null;
    lastDetailMode=null;

    // 새 지역 광 캐시를 먼저 표시하고, 이전 지역 전체수집은 backend generation으로 취소된다.
    await loadRegionFiber(false);
    if(mySwitch!==regionSwitchGeneration||activeRegionId!==region)return false;

    setWorkStatus('L'+map.getLevel()+' · REGION '+region+' · STAGE 동축/기기 조회 시작',80,true);
    await loadObjects(true);
    if(mySwitch!==regionSwitchGeneration||activeRegionId!==region)return false;

    setWorkStatus('L'+map.getLevel()+' · REGION '+region+' · STAGE 완료',100,false);
    return true;
  }} finally {{
    if(mySwitch===regionSwitchGeneration)regionSwitching=false;
  }}
}}

async function bootstrapAuth(){{
  try{{
    // 런처가 자식 실행 직전에 /me 검증을 완료한다.
    // pywebview 예약/미노출 함수명 문제를 피하기 위해 별도 bootstrap RPC를 사용하지 않는다.
    authenticated=true;
    setStatus('권한 지역 조회 중');
    await loadRegions();

    // 지역 조회 성공 여부와 무관하게 UI를 막지 않는 부가 기능만 뒤에서 실행한다.
    startIdleWatch();
    loadSessionPolicy().catch(()=>{{}});
    return true;
  }}catch(e){{
    authenticated=false;
    const msg=(e&&e.message)?e.message:'알 수 없는 오류';
    setStatus('지역 조회 오류 · '+msg);
    return false;
  }}
}}

function bindUi(){{
  document.getElementById('reload').onclick=async()=>{{
    if(!activeRegionId){{
      setStatus('먼저 지역을 선택하세요');
      return;
    }}
    lastQueryLat=null;
    lastQueryLng=null;
    lastDetailMode=null;
    setWorkStatus('L'+map.getLevel()+' · REGION '+activeRegionId+' · STAGE 광 전체 강제 새로고침 시작',5,true);
    await loadRegionFiber(true);
    setWorkStatus('L'+map.getLevel()+' · REGION '+activeRegionId+' · STAGE 동축/기기 새로고침',80,true);
    await loadObjects(true);
    setWorkStatus('L'+map.getLevel()+' · REGION '+activeRegionId+' · STAGE 새로고침 완료',100,false);
  }};
  document.getElementById('myLocation').onclick=()=>centerMyLocation(true);
  document.getElementById('mapHybrid').onclick=()=>{{
    if(!map||roadviewMode)return;
    hybridMode=!hybridMode;
    map.setMapTypeId(hybridMode?kakao.maps.MapTypeId.HYBRID:kakao.maps.MapTypeId.ROADMAP);
    const btn=document.getElementById('mapHybrid');
    btn.textContent=hybridMode?'일반지도':'위성지도';
    btn.title=hybridMode?'일반지도로 전환':'위성지도로 전환';
    setStatus(hybridMode?'위성지도':'일반지도');
  }};

  document.getElementById('roadviewBtn').onclick=()=>{{
    if(!map)return;
    const rvBtn=document.getElementById('roadviewBtn');
    const mapEl=document.getElementById('map');
    const rvEl=document.getElementById('roadview');
    const baseBtn=document.getElementById('mapHybrid');

    if(roadviewMode){{
      roadviewMode=false;
      rvEl.style.display='none';
      mapEl.style.display='block';
      rvBtn.textContent='로드뷰';
      rvBtn.title='현재 지도 중심의 로드뷰 열기';
      baseBtn.disabled=false;
      if(typeof map.relayout==='function')map.relayout();
      setStatus(hybridMode?'위성지도':'일반지도');
      return;
    }}

    const center=map.getCenter();
    if(!roadviewClient)roadviewClient=new kakao.maps.RoadviewClient();
    if(!roadview)roadview=new kakao.maps.Roadview(rvEl);

    setStatus('현재 위치 주변 로드뷰 찾는 중...');
    roadviewClient.getNearestPanoId(center,100,function(panoId){{
      if(panoId===null||panoId===undefined){{
        setStatus('현재 지도 중심 100m 이내에 로드뷰가 없습니다.');
        return;
      }}
      roadviewMode=true;
      mapEl.style.display='none';
      rvEl.style.display='block';
      rvBtn.textContent='지도보기';
      rvBtn.title='지도로 돌아가기';
      baseBtn.disabled=true;
      roadview.setPanoId(panoId,center);
      if(typeof roadview.relayout==='function')roadview.relayout();
      setStatus('로드뷰');
    }});
  }};
  document.getElementById('measureDistance').onclick=()=>setDistanceMode(!distanceMode);
  document.getElementById('clearDistance').onclick=()=>clearAllDistanceMeasurements();

  document.querySelectorAll('.layerBtn[data-group]').forEach(btn=>{{
    btn.onclick=()=>{{
      const g=String(btn.dataset.group||'').toUpperCase();
      groupEnabled[g]=!groupEnabled[g];
      btn.classList.toggle('on',groupEnabled[g]);

      if(groupEnabled[g]){{
        const restored=showGroupOverlays(g);
        if(restored>0){{
          setStatus('L'+map.getLevel()+' · '+g+' 캐시 즉시 표시 · '+restored+'개');
        }}else{{
          if(g==='FIBER'){{
            loadRegionFiber(false).catch(()=>{{}});
          }}else{{
            queueNonFiberLoad(true,0);
          }}
        }}
      }}else{{
        const hidden=hideGroupOverlays(g);
        const active=Object.keys(groupEnabled).filter(k=>groupEnabled[k]).join('/');
        setStatus(
          'L'+map.getLevel()+
          ' · '+g+' 즉시 숨김 '+hidden+'개'+
          (active ? ' · 활성 '+active : ' · 활성 그룹 없음')
        );
      }}
    }};
  }});

  document.getElementById('region').onchange=async e=>{{
    const region=String((e.target&&e.target.value)||'');
    if(!region){{
      e.target.value=activeRegionId||'';
      return;
    }}
    await activateRegion(region);
  }};

}}

function centerMyLocation(loadAfter){{
  if(!navigator.geolocation){{
    setStatus('현재 위치 기능을 사용할 수 없습니다');
    return;
  }}
  setStatus('현재 위치 확인 중');
  navigator.geolocation.getCurrentPosition(
    pos=>{{
      if(!map)return;
      const lat=Number(pos.coords.latitude);
      const lng=Number(pos.coords.longitude);
      myLat=lat;
      myLng=lng;
      map.setCenter(new kakao.maps.LatLng(lat,lng));
      map.setLevel(3);
      setStatus('현재 위치 · 반경 '+QUERY_RADIUS_METERS+'m');
      if(loadAfter)loadObjects(true);
    }},
    err=>{{
      setStatus('현재 위치 확인 실패');
    }},
    {{enableHighAccuracy:true,timeout:8000,maximumAge:30000}}
  );
}}

function initMap(){{
  try{{
    if(!(window.kakao&&kakao.maps)){{
      setStatus('카카오 JavaScript SDK 로드 실패');
      return;
    }}
    kakao.maps.load(()=>{{
      map=new kakao.maps.Map(document.getElementById('map'),{{
        center:new kakao.maps.LatLng(35.1595,126.8526),
        level:3
      }});
      kakao.maps.event.addListener(map,'idle',()=>{{
        // 지역은 사용자가 권한 목록에서 직접 선택한다.
        // 지도 이동 중에는 조회하지 않고 마지막 idle 후 선택 지역의 동축/기기만 갱신한다.
        const generation=++regionResolveGeneration;
        if(regionResolveTimer)clearTimeout(regionResolveTimer);
        regionResolveTimer=setTimeout(async()=>{{
          regionResolveTimer=null;
          if(generation!==regionResolveGeneration||!map||!activeRegionId)return;
          await loadObjects(false);
        }},REGION_SETTLE_DELAY_MS);
      }});
      kakao.maps.event.addListener(map,'click',e=>{{
        closeDistanceDeleteMenu();
        if(distanceMode)addDistancePoint(e.latLng);
      }});
      kakao.maps.event.addListener(map,'zoom_changed',()=>{{
        const level=map.getLevel();

        // 줌 변경은 서버/API와 완전히 분리한다.
        // 기기와 광 방향 화살표만 메모리/기존 오버레이에서 다시 계산하고 선로 데이터는 재조회하지 않는다.
        if(level<=3){{
          redrawDevicesFromMemory();
          redrawFiberArrowsForZoom();
        }}else{{
          applyZoomVisibility(level);
          redrawFiberArrowsForZoom();
        }}
        lastDetailMode=(level<=3);
        setStatus(
          'L'+level+
          (level<=3 ? ' · 캐시 레벨 즉시 적용' : ' · 광만 표시')+
          fiberDiagText()
        );
      }});
      centerMyLocation(false);
    }});
  }}catch(err){{
    setStatus('카카오맵 초기화 오류');
  }}
}}

['pointerdown','pointermove','keydown','wheel','touchstart'].forEach(
  eventName=>document.addEventListener(eventName,noteActivity,{{passive:true}})
);
document.addEventListener('visibilitychange',()=>{{
  if(document.visibilityState==='visible')noteActivity();
}});
document.addEventListener('keydown',e=>{{
  if(e.key==='Escape'&&distanceMode){{
    e.preventDefault();
    finishDistanceMeasurement();
  }}
}});
bindUi();

let authBootstrapped=false;
async function runBootstrapOnce(){{
  if(authBootstrapped)return;
  authBootstrapped=true;
  const ok=await bootstrapAuth();
  if(!ok)return;

  // 권한 지역 목록을 먼저 준비한 뒤 지도를 만든다.
  // 사용자는 이 목록에서 지역을 직접 선택한다.
  initMap();
}}
runBootstrapOnce();
</script>
</body>
</html>"""


def run_online_viewer():
    k = key()
    if not k:
        return 2

    import webview

    api = Api()

    # 런처가 자식 실행 직전에 검증한 세션이 없으면 Viewer를 열지 않는다.
    if not api.c.access_token:
        api.session_ended = True
        return SESSION_ENDED_EXIT_CODE

    local_token = secrets.token_urlsafe(32)
    page = html(k, local_token).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status, payload):
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            if not self.path.startswith("/api/"):
                self._json(404, {"ok": False, "error": "API 경로 없음"})
                return

            if self.headers.get("X-CMB-Local-Token", "") != local_token:
                self._json(403, {"ok": False, "error": "로컬 Viewer 인증 실패"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length) if length > 0 else b"{}"
                data = json.loads(body.decode("utf-8")) if body else {}
                name = self.path[len("/api/"):].split("?", 1)[0]

                if name == "regions":
                    result = api.regions()
                elif name == "select":
                    result = api.select(data.get("region"))
                elif name == "fiber_cached":
                    result = api.cached_fiber()
                elif name == "fiber_progress":
                    result = api.fiber_progress_status()
                elif name == "fiber_bbox":
                    result = api.fiber_bbox(
                        data.get("west"),
                        data.get("south"),
                        data.get("east"),
                        data.get("north"),
                        force=bool(data.get("force")),
                    )
                elif name == "fiber_all":
                    result = api.ensure_fiber_all(
                        force=bool(data.get("force", False)),
                    )
                elif name == "objects":
                    result = api.objects(
                        data.get("west"),
                        data.get("south"),
                        data.get("east"),
                        data.get("north"),
                    )
                elif name == "region_at_point":
                    result = api.region_at_point(
                        data.get("regions") or [],
                        data.get("lat"),
                        data.get("lng"),
                        data.get("radius_m", 1200),
                    )
                elif name == "map_display_settings":
                    result = api.map_display_settings()
                elif name == "session_policy":
                    result = api.session_policy()
                elif name == "touch_session":
                    result = api.touch_session()
                elif name == "end_session":
                    result = api.end_session()
                else:
                    self._json(404, {"ok": False, "error": "지원하지 않는 API"})
                    return

                if isinstance(result, dict) and result.get("error") and result.get("ok") is False:
                    self._json(400, result)
                else:
                    self._json(200, result if result is not None else {"ok": True})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        window = webview.create_window(
            "CMB 온라인 Viewer",
            url="http://127.0.0.1:8765/",
            width=1450,
            height=900,
            min_size=(900, 600),
        )
        api.window = window
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.shutdown()
        server.server_close()

    return SESSION_ENDED_EXIT_CODE if api.session_ended else 0

