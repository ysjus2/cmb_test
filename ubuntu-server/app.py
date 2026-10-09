from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DB_PATH = Path(os.environ.get("CMB_DB_PATH", "/var/lib/cmb-server/cmb.sqlite3"))
DEV_BYPASS = os.environ.get("CMB_DEV_BYPASS_AUTH", "1") == "1"
DEV_TOKEN = os.environ.get("CMB_DEV_TOKEN", "cmb-local-test")
ALLOWED_GROUPS = {"FIBER", "COAX", "POLE", "CONDUIT", "USER"}

app = FastAPI(title="CMB Network Server", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if DEV_BYPASS else [],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS revisions(
              id TEXT PRIMARY KEY,
              region_code TEXT NOT NULL,
              group_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              dataset_id TEXT NOT NULL,
              source_file TEXT,
              source_sha256 TEXT,
              package_sha256 TEXT,
              object_count INTEGER NOT NULL DEFAULT 0,
              active INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              UNIQUE(region_code, group_id, revision)
            );
            CREATE INDEX IF NOT EXISTS idx_rev_active
              ON revisions(region_code, group_id, active);

            CREATE TABLE IF NOT EXISTS objects(
              revision_id TEXT NOT NULL REFERENCES revisions(id) ON DELETE CASCADE,
              entity_id TEXT NOT NULL,
              regional_object_id TEXT,
              layer TEXT NOT NULL,
              entity_type TEXT,
              block_name TEXT,
              geometry_json TEXT NOT NULL,
              attributes_json TEXT NOT NULL DEFAULT '{}',
              xdata_json TEXT NOT NULL DEFAULT '{}',
              min_lon REAL NOT NULL,
              min_lat REAL NOT NULL,
              max_lon REAL NOT NULL,
              max_lat REAL NOT NULL,
              PRIMARY KEY(revision_id, entity_id)
            );
            CREATE INDEX IF NOT EXISTS idx_objects_bbox
              ON objects(min_lon, min_lat, max_lon, max_lat);
            """
        )


@app.on_event("startup")
def _startup():
    init_db()


def require_test_admin(authorization: str | None):
    if DEV_BYPASS:
        expected = f"Bearer {DEV_TOKEN}"
        if authorization != expected:
            raise HTTPException(401, "테스트 관리자 토큰이 필요합니다.")
        return
    raise HTTPException(401, "운영 인증은 아직 연결되지 않았습니다.")


def dataset_id(region_code: str) -> str:
    return region_code


def geometry_bounds(geometry: dict[str, Any]):
    typ = geometry.get("type")
    coords = geometry.get("coordinates")
    points = [coords] if typ == "Point" else coords if typ == "LineString" else None
    if not points:
        raise ValueError("Point/LineString geometry만 지원합니다.")
    xs, ys = [], []
    for p in points:
        if not isinstance(p, list) or len(p) < 2:
            raise ValueError("잘못된 geometry 좌표입니다.")
        lon, lat = float(p[0]), float(p[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("경위도 범위를 벗어났습니다.")
        xs.append(lon); ys.append(lat)
    return min(xs), min(ys), max(xs), max(ys)


class UploadPackage(BaseModel):
    schema: str = "cmb-network-package-v1"
    region_code: str
    group: str
    source_epsg: int = 5174
    source_file: str = ""
    source_sha256: str = ""
    package_sha256: str = ""
    object_count: int = 0
    objects: list[dict[str, Any]] = Field(default_factory=list)


@app.get("/health")
def health():
    return {"ok": True, "service": "cmb-network", "dev_bypass": DEV_BYPASS}


@app.post("/dev/session")
def dev_session():
    if not DEV_BYPASS:
        raise HTTPException(404)
    return {"access_token": DEV_TOKEN, "role": 1, "mode": "dev-bypass"}


@app.get("/regions")
def regions(authorization: str | None = Header(default=None)):
    require_test_admin(authorization)
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT region_code FROM revisions WHERE active=1 ORDER BY region_code"
        ).fetchall()
    return [{"id": r["region_code"], "name": r["region_code"]} for r in rows]


@app.get("/regions/{region_id}/datasets")
def region_datasets(region_id: str, authorization: str | None = Header(default=None)):
    require_test_admin(authorization)
    with db() as conn:
        row = conn.execute(
            "SELECT 1 FROM revisions WHERE region_code=? AND active=1 LIMIT 1", (region_id,)
        ).fetchone()
    return [{"id": dataset_id(region_id), "region_id": region_id}] if row else []


@app.get("/datasets/{dataset}/layers")
def layers(dataset: str, authorization: str | None = Header(default=None)):
    require_test_admin(authorization)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.group_id, o.layer, COUNT(*) object_count,
                   MIN(o.min_lon) west, MIN(o.min_lat) south,
                   MAX(o.max_lon) east, MAX(o.max_lat) north
            FROM revisions r JOIN objects o ON o.revision_id=r.id
            WHERE r.region_code=? AND r.active=1
            GROUP BY r.group_id, o.layer ORDER BY r.group_id, o.layer
            """, (dataset,)
        ).fetchall()
    if not rows:
        return {"layers": [], "bounds": None}
    return {
        "layers": [{"group_id": r["group_id"], "layer": r["layer"], "object_count": r["object_count"]} for r in rows],
        "bounds": {
            "west": min(r["west"] for r in rows), "south": min(r["south"] for r in rows),
            "east": max(r["east"] for r in rows), "north": max(r["north"] for r in rows),
        },
    }


@app.get("/datasets/{dataset}/objects")
def objects(
    dataset: str,
    bbox: str = Query(...),
    limit: int = Query(500, ge=1, le=5000),
    authorization: str | None = Header(default=None),
):
    require_test_admin(authorization)
    try:
        west, south, east, north = [float(x) for x in bbox.split(",")]
    except Exception:
        raise HTTPException(400, "bbox=west,south,east,north 형식이 필요합니다.")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.group_id, r.revision, r.id revision_id,
                   o.entity_id, o.regional_object_id, o.layer, o.entity_type,
                   o.block_name, o.geometry_json, o.attributes_json
            FROM revisions r JOIN objects o ON o.revision_id=r.id
            WHERE r.region_code=? AND r.active=1
              AND o.max_lon>=? AND o.min_lon<=? AND o.max_lat>=? AND o.min_lat<=?
            LIMIT ?
            """, (dataset, west, east, south, north, limit)
        ).fetchall()
    features = []
    for r in rows:
        attrs = json.loads(r["attributes_json"] or "{}")
        features.append({
            "type": "Feature",
            "id": f'{r["revision_id"]}:{r["entity_id"]}',
            "geometry": json.loads(r["geometry_json"]),
            "properties": {
                "group_id": r["group_id"],
                "revision": r["revision"],
                "entity_id": r["entity_id"],
                "regional_object_id": r["regional_object_id"],
                "layer": r["layer"],
                "entity_type": r["entity_type"],
                "block_name": r["block_name"],
                "name": attrs.get("NAME") or attrs.get("ID") or r["layer"],
                "attributes": {"fields": attrs},
            },
        })
    return {"version": str(int(time.time())), "features": features, "next_cursor": None}


@app.post("/admin/drawings/upload")
def upload(package: UploadPackage, authorization: str | None = Header(default=None)):
    require_test_admin(authorization)
    group = package.group.upper().strip()
    region = package.region_code.upper().strip()
    if group not in ALLOWED_GROUPS:
        raise HTTPException(400, f"지원 그룹: {sorted(ALLOWED_GROUPS)}")
    if not region.startswith("CMB_GN_"):
        raise HTTPException(400, "region_code 형식이 잘못되었습니다.")
    if package.object_count and package.object_count != len(package.objects):
        raise HTTPException(400, "object_count와 objects 길이가 다릅니다.")

    prepared = []
    seen = set()
    for obj in package.objects:
        entity = str(obj.get("source_handle") or "").strip()
        if not entity:
            raise HTTPException(400, "source_handle이 없는 객체가 있습니다.")
        if entity in seen:
            raise HTTPException(400, f"중복 source_handle: {entity}")
        seen.add(entity)
        try:
            bounds = geometry_bounds(obj.get("geometry") or {})
        except ValueError as exc:
            raise HTTPException(400, f"{entity}: {exc}")
        prepared.append((obj, bounds))

    with db() as conn:
        last = conn.execute(
            "SELECT COALESCE(MAX(revision),0) rev FROM revisions WHERE region_code=? AND group_id=?",
            (region, group),
        ).fetchone()["rev"]
        rev = int(last) + 1
        rid = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO revisions(id,region_code,group_id,revision,dataset_id,source_file,
              source_sha256,package_sha256,object_count,active,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (rid, region, group, rev, dataset_id(region), package.source_file,
             package.source_sha256, package.package_sha256, len(prepared), 0, int(time.time())),
        )
        for obj, bounds in prepared:
            conn.execute(
                """
                INSERT INTO objects(revision_id,entity_id,regional_object_id,layer,entity_type,
                  block_name,geometry_json,attributes_json,xdata_json,
                  min_lon,min_lat,max_lon,max_lat)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (rid, str(obj.get("source_handle")), str(obj.get("regional_object_id") or ""),
                 str(obj.get("layer") or ""), str(obj.get("entity_type") or ""),
                 str(obj.get("block_name") or ""),
                 json.dumps(obj.get("geometry") or {}, ensure_ascii=False),
                 json.dumps(obj.get("attributes") or {}, ensure_ascii=False),
                 json.dumps(obj.get("xdata") or {}, ensure_ascii=False),
                 bounds[0], bounds[1], bounds[2], bounds[3]),
            )
        # 그룹 업로드는 검증이 완료된 패키지를 원자적으로 활성화한다.
        conn.execute(
            "UPDATE revisions SET active=0 WHERE region_code=? AND group_id=?",
            (region, group),
        )
        conn.execute("UPDATE revisions SET active=1 WHERE id=?", (rid,))
    return {"ok": True, "region_code": region, "group": group, "revision": rev,
            "revision_id": rid, "object_count": len(prepared), "active": True}


@app.get("/admin/drawings/{region}/revisions")
def revision_list(region: str, authorization: str | None = Header(default=None)):
    require_test_admin(authorization)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id,group_id,revision,source_file,source_sha256,package_sha256,
                   object_count,active,created_at
            FROM revisions WHERE region_code=? ORDER BY group_id,revision DESC
            """, (region.upper(),)
        ).fetchall()
    return [dict(r) for r in rows]
