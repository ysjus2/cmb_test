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

    def _fetch_all_region_features(self):
        # FIBER 전체 캐시는 해당 지역의 실제 bounds + FIBER 레이어만 수집한다.
        # 과거처럼 전체 그룹을 전국 bbox에서 받은 뒤 FIBER만 거르면
        # COAX/시설 밀도가 높은 지역에서 5,000개 제한을 불필요하게 소진한다.
        limit = 5000
        max_depth = 14

        meta = self.c.online_layers(self.region) or {}
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

        def fetch_cell(w, s, e, n, depth=0):
            raw = self.c.online_objects(
                self.region,
                f"{w},{s},{e},{n}",
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

        # 이 지역의 서버 revision은 앱 실행 후 최초 진입 시 한 번만 확인한다.
        self._refresh_versions_if_due(force=force)
        fiber_version = str((self.cache_state.get("versions") or {}).get("FIBER") or "")
        self._load_fiber_cache()

        # 과거 버전에서 일부만 저장된 캐시가 동일 revision으로 남아 있을 수 있다.
        # revision 일치만으로 hit 처리하지 않고 서버 object_count와 개수까지 일치해야 한다.
        expected_count = self._expected_group_count("FIBER")
        cached_features = self._fiber_features()
        cached_count = len(cached_features)
        cache_complete = (
            expected_count is None
            or expected_count <= 0
            or cached_count == expected_count
        )
        if (
            not force
            and fiber_version
            and self.fiber_cache.get("version") == fiber_version
            and cache_complete
        ):
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
            return {"ok": True, "features": [], "cache": "empty", "version": ""}
        all_features = self._fetch_all_region_features()
        fiber_features = [
            feature for feature in all_features
            if str(((feature.get("properties") or {}).get("group_id") or "")).upper() == "FIBER"
        ]

        received_count = len(fiber_features)
        unique_key_count = len({self._feature_key(f) for f in fiber_features})
        if expected_count is not None and expected_count > 0 and received_count != expected_count:
            # 일부 광만 받은 상태를 정상 캐시로 덮어쓰지 않는다.
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

        self.fiber_cache = {"version": fiber_version, "features": fiber_features}
        self._save_fiber_cache()
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

    def region_at_point(self, regions, lat, lng, radius_m=1200):
        """Resolve the map center by actual lon/lat object presence, without 그리드."""
        lat = float(lat); lng = float(lng)
        radius_m = max(200.0, min(3000.0, float(radius_m or 1200)))
        lat_delta = radius_m / 111320.0
        lng_scale = max(0.2, __import__("math").cos(lat * __import__("math").pi / 180.0))
        lng_delta = radius_m / (111320.0 * lng_scale)
        bbox = f"{lng-lng_delta},{lat-lat_delta},{lng+lng_delta},{lat+lat_delta}"

        ranked = []
        for region in [str(x or "").strip() for x in (regions or []) if str(x or "").strip()]:
            try:
                raw = self.c.online_objects(region, bbox, limit=500) or {}
                features = [x for x in (raw.get("features") or []) if isinstance(x, dict)]
                if not features:
                    continue

                # 현재 중심에 가까운 실제 geometry가 있는 지역을 우선한다.
                nearest = float("inf")
                for feature in features:
                    bounds = self._geometry_bounds((feature or {}).get("geometry") or {})
                    if not bounds:
                        continue
                    west, south, east, north = bounds
                    cx = min(max(lng, west), east)
                    cy = min(max(lat, south), north)
                    dist = (cx-lng) ** 2 + (cy-lat) ** 2
                    if dist < nearest:
                        nearest = dist
                ranked.append((nearest, -len(features), region, len(features)))
            except Exception:
                continue

        if not ranked:
            return {"ok": True, "region": "", "count": 0, "source": "bbox_objects"}

        ranked.sort(key=lambda row: (row[0], row[1], row[2]))
        nearest, _neg_count, region, count = ranked[0]
        return {
            "ok": True,
            "region": region,
            "count": count,
            "source": "bbox_objects",
            "distance_score": nearest,
        }

    def map_display_settings(self):
        try:
            settings = self.c.map_display_settings() or {}
            radius = int(settings.get("radius_m", 500))
            refresh = int(settings.get("refresh_distance_m", 200))
            return {
                "ok": True,
                "radius_m": max(100, min(3000, radius)),
                "refresh_distance_m": max(25, min(radius, refresh)),
            }
        except Exception as exc:
            return self._handle_error(
                exc,
                {"radius_m": 500, "refresh_distance_m": 200},
            )

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
        self.region = str(region or "")
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

        merged = {}
        mx = (west + east) / 2.0
        my = (south + north) / 2.0
        for cell in (
            (west, south, mx, my),
            (mx, south, east, my),
            (west, my, mx, north),
            (mx, my, east, north),
        ):
            for feature in fetch_cell(*cell):
                merged[self._feature_key(feature)] = feature
        return list(merged.values())

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
#statusWrap{{flex:1 1 auto;min-width:0;overflow:hidden;padding-left:4px}}
#status{{display:block;font-size:12px;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}}
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
      <select id='region' style='display:none' aria-hidden='true'><option value=''></option></select>
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
    <div id='statusWrap'><span id='status' title='현재 상태'>세션 확인 중</span></div>
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
let QUERY_RADIUS_METERS=500;
const FIBER_QUERY_RADIUS_METERS=10000;
let QUERY_RECENTER_METERS=200;
let lastActivity=Date.now();
let idleTimer=null;
let nonFiberLoadTimer=null;
let authorizedRegions=[];
let regionSwitching=false;
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

function regionBoundsArea(bounds){{
  if(!bounds)return Number.POSITIVE_INFINITY;
  const west=Number(bounds.west),south=Number(bounds.south);
  const east=Number(bounds.east),north=Number(bounds.north);
  if(![west,south,east,north].every(Number.isFinite))return Number.POSITIVE_INFINITY;
  return Math.abs((east-west)*(north-south));
}}

async function activateRegion(region){{
  region=String(region||'');
  const sel=document.getElementById('region');
  if(!region||regionSwitching)return false;
  if(sel.value===region)return true;

  regionSwitching=true;
  try{{
    clearOverlays();
    document.getElementById('detail').style.display='none';
    sel.value=region;
    const info=authorizedRegions.find(x=>x.id===region);
    const r=await apiCall('select',{{region:region}});
    if(!r.ok){{
      sel.value='';
      setStatus(r.error||'지역 자동 연결 실패');
      return false;
    }}

    let cached={{features:[],cache:'empty'}};
    try{{cached=await apiCall('fiber_cached');}}catch(err){{}}
    if(region!==sel.value)return false;
    const cachedFeatures=cached.features||[];
    const cachedCount=renderFiberFeatures(cachedFeatures);
    fiberDiag.cache=cachedFeatures.length;
    fiberDiag.received=0;
    fiberDiag.unique=0;
    fiberDiag.server=0;
    setStatus((info?info.name:region)+' · '+(cachedCount>0
      ? '광 캐시 즉시 표시'+fiberDiagText()
      : '광 캐시 없음 · 최초 다운로드 시작'));

    apiCall('fiber_all',{{force:false}}).then(fiber=>{{
      if(region!==sel.value)return;
      if(fiber.error){{
        setStatus(fiber.error+' · 기존 광 캐시 유지');
        return;
      }}
      const fiberFeatures=fiber.features||[];
      const fiberCount=fiberFeatures.length;
      const expected=Number(fiber.expected_count||0);
      fiberDiag.server=expected;
      fiberDiag.received=Number(fiber.received_count||fiberCount);
      fiberDiag.unique=Number(fiber.unique_key_count||fiber.received_count||fiberCount);
      if(fiber.cache!=='hit' || cachedCount===0)renderFiberFeatures(fiberFeatures);
      const source=(fiber.cache==='hit'?'광 캐시':'광 서버')+' '+fiberCount+'개';
      setStatus((info?info.name:region)+' · '+source+fiberDiagText());
    }}).catch(err=>setStatus('광 갱신 실패 · '+((err&&err.message)||err)));

    await loadObjects(true);
    return true;
  }} finally {{
    regionSwitching=false;
  }}
}}

async function autoRegionForMapCenter(){{
  if(!map||!authorizedRegions.length||regionSwitching)return false;
  const center=map.getCenter();
  const lat=Number(center.getLat()),lng=Number(center.getLng());
  const sel=document.getElementById('region');

  viewDiag.centerLat=lat;
  viewDiag.centerLng=lng;
  viewDiag.stage='좌표 지역 확인';
  viewDiag.progress='현재 위치 주변 도면 검색';
  setStatus('L'+map.getLevel()+' · '+viewDiagText());

  // 1순위: 현재 위·경도 주변에 실제 도면 객체가 존재하는 지역을 찾는다.
  // region bounds가 서로 겹쳐도 실제 geometry 좌표 기준으로 선택한다.
  let resolved=null;
  try{{
    resolved=await apiCall('region_at_point',{{
      regions:authorizedRegions.map(x=>x.id),
      lat:lat,
      lng:lng,
      radius_m:1200
    }});
  }}catch(e){{resolved=null;}}

  if(resolved&&resolved.region){{
    const matched=authorizedRegions.find(x=>x.id===String(resolved.region));
    if(matched){{
      viewDiag.region=matched.id;
      viewDiag.stage='좌표 지역 확정';
      viewDiag.progress=matched.id+' · 주변 객체 '+String(resolved.count||0);
      if(sel.value===matched.id){{
        setStatus('L'+map.getLevel()+' · '+viewDiagText());
        return true;
      }}
      return await activateRegion(matched.id);
    }}
  }}

  // 실제 객체가 전혀 없는 위치에서만 지역 bounds를 최후 폴백으로 사용한다.
  const candidates=authorizedRegions
    .filter(x=>boundsContainsLatLng(x.bounds,center))
    .sort((a,b)=>regionBoundsArea(a.bounds)-regionBoundsArea(b.bounds));
  const matched=candidates.length?candidates[0]:null;
  if(!matched){{
    if(sel.value){{
      clearOverlays();
      await apiCall('select',{{region:''}});
      sel.value='';
    }}
    viewDiag.region='';
    viewDiag.stage='좌표 지역 없음';
    viewDiag.progress='';
    setStatus('현재 지도 위치에 접근 가능한 지역 도면이 없습니다 · '+currentCenterText());
    return false;
  }}
  viewDiag.region=matched.id;
  viewDiag.stage='지역 bounds 폴백';
  viewDiag.progress=matched.id;
  if(sel.value===matched.id)return true;
  return await activateRegion(matched.id);
}}

async function loadMapDisplaySettings(){{
  try{{
    const r=await apiCall('map_display_settings');
    if(r&&r.ok!==false){{
      const radius=Number(r.radius_m||500);
      const refresh=Number(r.refresh_distance_m||200);
      QUERY_RADIUS_METERS=Math.max(100,Math.min(3000,radius));
      QUERY_RECENTER_METERS=Math.max(25,Math.min(QUERY_RADIUS_METERS,refresh));
    }}
  }}catch(e){{}}
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
    const ok=await autoRegionForMapCenter();
    if(!ok)return;
    const region=String(document.getElementById('region').value||'');
    try{{
      const fiber=await apiCall('fiber_all',{{force:true}});
      if(region===document.getElementById('region').value && fiber && !fiber.error){{
        const items=fiber.features||[];
        renderFiberFeatures(items);
        fiberDiag.cache=items.length;
      }}
    }}catch(e){{}}
    await loadObjects(true);
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
            apiCall('fiber_cached').then(cached=>{{
              const items=(cached&&cached.features)||[];
              if(items.length){{
                renderFiberFeatures(items);
                return null;
              }}
              return apiCall('fiber_all',{{force:false}}).then(f=>renderFiberFeatures((f&&f.features)||[]));
            }}).catch(()=>{{}});
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

  document.getElementById('region').onchange=()=>{{}};

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
      kakao.maps.event.addListener(map,'idle',async()=>{{
        const ok=await autoRegionForMapCenter();
        if(ok){{
          // 지도 이동이 멈출 때마다 광/동축/기기를 모두 현재 위·경도 bbox로 갱신한다.
          loadFiberViewport(false).catch(()=>{{}});
          loadObjects();
        }}
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
      setTimeout(async()=>{{
        const ok=await autoRegionForMapCenter();
        if(ok)loadObjects(true);
      }},250);
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
  await loadMapDisplaySettings();
  const ok=await bootstrapAuth();
  if(!ok)return;

  // 권한 지역 목록이 준비된 뒤 지도를 만든다.
  // 이전에는 initMap()이 먼저 실행되어 첫 idle 이벤트 때 authorizedRegions가 비어
  // 전주메타/grid 조회가 시작되지 않을 수 있었다.
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

