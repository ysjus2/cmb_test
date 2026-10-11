#!/usr/bin/env bash
set -euo pipefail

# CMB FINAL SERVER PATCH V3
# Canonical rule:
#   - one running FastAPI server
#   - one existing PostgreSQL/PostGIS database
#   - no SQLite sidecar database
#   - FIBER/COAX/POLE/CONDUIT/USER/SYMBOL revisions
#   - lightweight online version checks for Windows/Android caches

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"
BACKUP_DIR="${CMB_BACKUP_DIR:-/opt/cmb-backups}"
PATCH_MODULE="cmb_final_runtime_patch.py"
MARK_BEGIN="# === CMB_FINAL_RUNTIME_PATCH_V3_BEGIN ==="
MARK_END="# === CMB_FINAL_RUNTIME_PATCH_V3_END ==="

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash $0 로 실행해주세요."
  exit 1
fi

echo "[1/9] 현재 운영 서비스 확인"
if ! systemctl cat "${SERVICE_NAME}" >/dev/null 2>&1; then
  if systemctl cat cmb-server >/dev/null 2>&1; then
    SERVICE_NAME="cmb-server"
  else
    echo "ERROR: cmb-cad-api/cmb-server 서비스를 찾지 못했습니다."
    exit 1
  fi
fi

EXEC_START="$(systemctl show -p ExecStart --value "${SERVICE_NAME}")"
WORK_DIR="$(systemctl show -p WorkingDirectory --value "${SERVICE_NAME}")"
[[ -n "${WORK_DIR}" && "${WORK_DIR}" != "[not set]" ]] || WORK_DIR="/opt/cmb-server"
APP_DIR="${CMB_APP_DIR:-${WORK_DIR}}"

ENTRY_MODULE=""
if [[ "${EXEC_START}" =~ ([A-Za-z_][A-Za-z0-9_]*):app ]]; then
  ENTRY_MODULE="${BASH_REMATCH[1]}"
fi
if [[ -z "${ENTRY_MODULE}" ]]; then
  for candidate in cmb_asgi main app; do
    [[ -f "${APP_DIR}/${candidate}.py" ]] && ENTRY_MODULE="${candidate}" && break
  done
fi
if [[ -z "${ENTRY_MODULE}" || ! -f "${APP_DIR}/${ENTRY_MODULE}.py" ]]; then
  echo "ERROR: 현재 FastAPI 진입 파일을 찾지 못했습니다."
  echo "ExecStart=${EXEC_START}"
  echo "WorkingDirectory=${APP_DIR}"
  exit 1
fi
ENTRY_FILE="${APP_DIR}/${ENTRY_MODULE}.py"
echo "SERVICE=${SERVICE_NAME}"
echo "ENTRY=${ENTRY_FILE}"

echo "[2/9] 현재 실행 프로세스 환경값 사용"
MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE_NAME}")"
if [[ -z "${MAIN_PID}" || "${MAIN_PID}" == "0" || ! -r "/proc/${MAIN_PID}/environ" ]]; then
  echo "ERROR: 실행 중인 ${SERVICE_NAME} 프로세스 환경을 읽을 수 없습니다."
  exit 1
fi

# 현재 서버 프로세스가 실제 사용하는 DB/서비스 환경만 가져온다.
# env 파일을 shell source하지 않아 따옴표/공백/특수문자 문제를 피한다.
while IFS= read -r -d '' item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

echo "[3/9] 현재 PostgreSQL/PostGIS 연결 검증"
"${PYTHON_BIN}" - <<'PY'
import os, sys

def connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    errors=[]
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception as e:
        errors.append("psycopg: "+str(e))
    try:
        import psycopg2
        return psycopg2.connect(dsn or "")
    except Exception as e:
        errors.append("psycopg2: "+str(e))
    raise RuntimeError("PostgreSQL 연결 실패: "+" | ".join(errors))

with connect() as conn:
    cur=conn.cursor()
    cur.execute("SELECT current_database(), current_user")
    print("POSTGRES_OK", cur.fetchone())
    cur.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='postgis')")
    postgis=bool(cur.fetchone()[0])
    print("POSTGIS", postgis)
    if not postgis:
        raise RuntimeError("현재 운영 DB에 PostGIS가 활성화되어 있지 않습니다.")

    cur.execute("""
        SELECT table_name,column_name
        FROM information_schema.columns
        WHERE table_schema='public'
    """)
    tables={}
    for table,col in cur.fetchall():
        tables.setdefault(str(table),set()).add(str(col))

    candidates=[]
    for table,cols in tables.items():
        if (
            "region_code" in cols
            and ("group_id" in cols or "group" in cols)
            and "revision" in cols
            and ("active" in cols or "is_active" in cols)
        ):
            candidates.append(table)
    if not candidates:
        raise RuntimeError(
            "현재 운영 DB에서 지역/그룹 Revision 테이블을 찾지 못했습니다. "
            "DB를 변경하지 않고 중단합니다."
        )
    print("REVISION_TABLE_CANDIDATES", sorted(candidates))
PY

echo "[4/9] 기존 서버 파일 백업"
mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${BACKUP_DIR}/cmb-final-runtime-${STAMP}.tgz"
FILES=("$(basename "${ENTRY_FILE}")")
for extra in cmb_final_runtime_patch.py cmb_final_settings.py cmb_map_display_patch.py; do
  [[ -f "${APP_DIR}/${extra}" ]] && FILES+=("${extra}")
done
tar -C "${APP_DIR}" -czf "${BACKUP}" "${FILES[@]}"
echo "BACKUP=${BACKUP}"

restore_files() {
  echo "ROLLBACK: 서버 소스 복구"
  tar -C "${APP_DIR}" -xzf "${BACKUP}" || true
  systemctl restart "${SERVICE_NAME}" || true
}
trap 'echo "ERROR: 패치 실패"; restore_files' ERR

echo "[5/9] 기존 이중 패치 코드 제거 + 단일 런타임 패치 설치"
ENTRY_FILE="${ENTRY_FILE}" "${PYTHON_BIN}" - <<'PY'
import os, re
from pathlib import Path
p=Path(os.environ["ENTRY_FILE"])
text=p.read_text(encoding="utf-8")
patterns=[
    r"\n?# === CMB_MAP_DISPLAY_PATCH_V1_BEGIN ===.*?# === CMB_MAP_DISPLAY_PATCH_V1_END ===\n?",
    r"\n?# === CMB_FINAL_SETTINGS_V1_BEGIN ===.*?# === CMB_FINAL_SETTINGS_V1_END ===\n?",
    r"\n?# === CMB_FINAL_RUNTIME_PATCH_V2_BEGIN ===.*?# === CMB_FINAL_RUNTIME_PATCH_V2_END ===\n?",
    r"\n?# === CMB_FINAL_RUNTIME_PATCH_V3_BEGIN ===.*?# === CMB_FINAL_RUNTIME_PATCH_V3_END ===\n?",
]
for pattern in patterns:
    text=re.sub(pattern,"\n",text,flags=re.S)
p.write_text(text.rstrip()+"\n",encoding="utf-8")
print("OLD_PATCH_BLOCKS_REMOVED")
PY

rm -f "${APP_DIR}/cmb_final_settings.py" "${APP_DIR}/cmb_map_display_patch.py"

cat > "${APP_DIR}/${PATCH_MODULE}" <<'PY'
from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
import uuid

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

DEFAULT_RADIUS_M = 500
DEFAULT_REFRESH_M = 200
GROUPS = ("FIBER","COAX","POLE","CONDUIT","USER")


def _connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    errors=[]
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception as exc:
        errors.append("psycopg: "+str(exc))
    try:
        import psycopg2
        return psycopg2.connect(dsn or "")
    except Exception as exc:
        errors.append("psycopg2: "+str(exc))
    raise RuntimeError("현재 PostgreSQL 연결 실패: "+" | ".join(errors))


def _qident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""):
        raise RuntimeError("잘못된 DB 식별자")
    return '"' + name + '"'


def _tables():
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("""
            SELECT table_name,column_name,data_type
            FROM information_schema.columns
            WHERE table_schema='public'
        """)
        out={}
        for table,col,typ in cur.fetchall():
            out.setdefault(str(table),{})[str(col)]=str(typ)
        return out


def _settings_table():
    tables=_tables()
    for name in ("settings","server_settings","app_settings","cmb_settings"):
        cols=tables.get(name,{})
        if "key" in cols and "value" in cols:
            return name
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cmb_settings(
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()
    return "cmb_settings"


def _revision_spec():
    tables=_tables()
    ranked=[]
    for table,cols in tables.items():
        region = "region_code" if "region_code" in cols else None
        group = "group_id" if "group_id" in cols else ("group" if "group" in cols else None)
        rev = "revision" if "revision" in cols else None
        active = "active" if "active" in cols else ("is_active" if "is_active" in cols else None)
        if region and group and rev and active:
            score=0 if table=="revisions" else 1 if "revision" in table else 2
            ranked.append((score,table,region,group,rev,active,cols))
    if not ranked:
        raise RuntimeError("현재 운영 DB에서 revision 테이블을 찾지 못했습니다.")
    _,table,region,group,rev,active,cols=sorted(ranked)[0]
    return table,region,group,rev,active,cols


def _active_clause(active_col, cols):
    typ=cols.get(active_col,"").lower()
    return f"{_qident(active_col)}=TRUE" if "bool" in typ else f"{_qident(active_col)}=1"


def _read_settings():
    table=_settings_table()
    values={"radius_m":DEFAULT_RADIUS_M,"refresh_distance_m":DEFAULT_REFRESH_M}
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute(
            f"SELECT key,value FROM {_qident(table)} "
            "WHERE key IN (%s,%s)",
            ("map_radius_m","map_refresh_distance_m"),
        )
        for key,value in cur.fetchall():
            try:
                if key=="map_radius_m": values["radius_m"]=int(value)
                if key=="map_refresh_distance_m": values["refresh_distance_m"]=int(value)
            except Exception:
                pass
    radius=max(100,min(3000,values["radius_m"]))
    refresh=max(25,min(radius,1500,values["refresh_distance_m"]))
    return {"radius_m":radius,"refresh_distance_m":refresh}


def _write_setting(key,value):
    table=_settings_table()
    with _connect() as conn:
        cur=conn.cursor()
        cols=_tables().get(table,{})
        if "updated_at" in cols:
            cur.execute(
                f"INSERT INTO {_qident(table)}(key,value,updated_at) VALUES(%s,%s,NOW()) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=NOW()",
                (key,str(value)),
            )
        else:
            cur.execute(
                f"INSERT INTO {_qident(table)}(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (key,str(value)),
            )
        conn.commit()


def _write_settings(radius,refresh):
    radius=max(100,min(3000,int(radius)))
    refresh=max(25,min(radius,1500,int(refresh)))
    _write_setting("map_radius_m",radius)
    _write_setting("map_refresh_distance_m",refresh)
    return {"radius_m":radius,"refresh_distance_m":refresh}


def _ensure_symbol_tables():
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS symbol_revisions(
              id TEXT PRIMARY KEY,
              region_code TEXT NOT NULL,
              revision INTEGER NOT NULL,
              source_file TEXT,
              source_sha256 TEXT,
              package_sha256 TEXT,
              symbol_count INTEGER NOT NULL DEFAULT 0,
              memo TEXT NOT NULL DEFAULT '',
              active BOOLEAN NOT NULL DEFAULT FALSE,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              UNIQUE(region_code,revision)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_revisions_active
            ON symbol_revisions(region_code,active)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS symbol_defs(
              revision_id TEXT NOT NULL REFERENCES symbol_revisions(id) ON DELETE CASCADE,
              symbol_key TEXT NOT NULL,
              payload_json JSONB NOT NULL,
              PRIMARY KEY(revision_id,symbol_key)
            )
        """)
        conn.commit()


def _versions(region):
    table,region_col,group_col,rev_col,active_col,cols=_revision_spec()
    signature_col=next((c for c in ("package_sha256","source_sha256","revision_id","id") if c in cols),None)
    count_col=next((c for c in ("object_count","count") if c in cols),None)
    select=[
        _qident(group_col),
        _qident(rev_col),
    ]
    select.append(_qident(signature_col) if signature_col else "NULL")
    select.append(_qident(count_col) if count_col else "NULL")
    sql=(
        "SELECT "+",".join(select)+
        f" FROM {_qident(table)} WHERE {_qident(region_col)}=%s AND "+
        _active_clause(active_col,cols)
    )
    out={}
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute(sql,(region,))
        for group,revision,signature,count in cur.fetchall():
            g=str(group or "").upper()
            if g in GROUPS:
                out[g]=f"{revision}:{signature or ''}:{count if count is not None else ''}"
        _ensure_symbol_tables()
        cur=conn.cursor()
        cur.execute(
            "SELECT revision,COALESCE(package_sha256,''),symbol_count "
            "FROM symbol_revisions WHERE region_code=%s AND active=TRUE "
            "ORDER BY revision DESC LIMIT 1",
            (region,),
        )
        row=cur.fetchone()
        if row:
            out["SYMBOL"]=f"{row[0]}:{row[1]}:{row[2]}"
    return out


class MapDisplaySettings(BaseModel):
    radius_m:int=Field(DEFAULT_RADIUS_M,ge=100,le=3000)
    refresh_distance_m:int=Field(DEFAULT_REFRESH_M,ge=25,le=1500)


class SymbolPackage(BaseModel):
    region_code:str
    source_file:str=""
    source_sha256:str=""
    package_sha256:str=""
    memo:str=""
    symbol_count:int=0
    symbols:list[dict]=Field(default_factory=list)


def _has_route(app,path,method):
    method=method.upper()
    for route in getattr(app,"routes",[]):
        if getattr(route,"path",None)==path and method in set(getattr(route,"methods",set()) or set()):
            return True
    return False


def _probe_sync(url,headers):
    ctx=ssl._create_unverified_context()
    req=urllib.request.Request(url,headers=headers,method="GET")
    try:
        with urllib.request.urlopen(req,context=ctx,timeout=8) as resp:
            return int(resp.status),resp.read(4096)
    except urllib.error.HTTPError as exc:
        return int(exc.code),exc.read(4096)


async def _require_probe(request,path):
    headers={"Accept":"application/json"}
    if request.headers.get("authorization"):
        headers["Authorization"]=request.headers["authorization"]
    if request.headers.get("cookie"):
        headers["Cookie"]=request.headers["cookie"]
    base=str(request.base_url).rstrip("/")
    status,body=await asyncio.to_thread(_probe_sync,base+path,headers)
    if status==401: raise HTTPException(401,"로그인이 만료됐습니다.")
    if status==403: raise HTTPException(403,"권한이 없습니다.")
    if not 200<=status<300:
        raise HTTPException(status,"기존 서버 권한 확인 실패")


def install(app):
    _read_settings()
    _ensure_symbol_tables()

    if not _has_route(app,"/settings/map-display","GET"):
        @app.get("/settings/map-display")
        async def map_settings(request:Request):
            await _require_probe(request,"/regions")
            return _read_settings()

    if not _has_route(app,"/admin/settings/map-display","GET"):
        @app.get("/admin/settings/map-display")
        async def admin_map_settings(request:Request):
            await _require_probe(request,"/admin/settings/session-timeout")
            return _read_settings()

    if not _has_route(app,"/admin/settings/map-display","POST"):
        @app.post("/admin/settings/map-display")
        async def set_map_settings(settings:MapDisplaySettings,request:Request):
            await _require_probe(request,"/admin/settings/session-timeout")
            return _write_settings(settings.radius_m,settings.refresh_distance_m)

    if not _has_route(app,"/online/{region}/versions","GET"):
        @app.get("/online/{region}/versions")
        async def online_versions(region:str,request:Request):
            region=str(region or "").strip().upper()
            await _require_probe(request,f"/online/{region}/layers")
            return _versions(region)

    if not _has_route(app,"/online/{region}/symbols","GET"):
        @app.get("/online/{region}/symbols")
        async def online_symbols(region:str,request:Request):
            region=str(region or "").strip().upper()
            await _require_probe(request,f"/online/{region}/layers")
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute(
                    "SELECT id,revision,COALESCE(package_sha256,''),symbol_count "
                    "FROM symbol_revisions WHERE region_code=%s AND active=TRUE "
                    "ORDER BY revision DESC LIMIT 1",(region,)
                )
                rev=cur.fetchone()
                if not rev:
                    return {"region_code":region,"revision":None,"symbols":[]}
                cur.execute(
                    "SELECT payload_json FROM symbol_defs WHERE revision_id=%s ORDER BY symbol_key",
                    (rev[0],),
                )
                symbols=[]
                for (payload,) in cur.fetchall():
                    if isinstance(payload,str): payload=json.loads(payload)
                    symbols.append(payload)
            return {
                "region_code":region,
                "revision":int(rev[1]),
                "version":f"{rev[1]}:{rev[2]}:{rev[3]}",
                "symbols":symbols,
            }

    if not _has_route(app,"/admin/drawings/{region}/symbols","POST"):
        @app.post("/admin/drawings/{region}/symbols")
        async def upload_symbols(region:str,package:SymbolPackage,request:Request):
            region=str(region or "").strip().upper()
            await _require_probe(request,"/admin/settings/session-timeout")
            if region!=str(package.region_code or "").strip().upper():
                raise HTTPException(400,"지역코드가 일치하지 않습니다.")
            if package.symbol_count!=len(package.symbols):
                raise HTTPException(400,"symbol_count와 symbols 길이가 다릅니다.")
            prepared={}
            for item in package.symbols:
                key=str(item.get("key") or "").strip()
                if not key: raise HTTPException(400,"key가 없는 심볼 정의가 있습니다.")
                prepared[key]=item
            _ensure_symbol_tables()
            rid=str(uuid.uuid4())
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute(
                    "SELECT COALESCE(MAX(revision),0)+1 FROM symbol_revisions WHERE region_code=%s",
                    (region,),
                )
                revision=int(cur.fetchone()[0])
                cur.execute(
                    "INSERT INTO symbol_revisions("
                    "id,region_code,revision,source_file,source_sha256,package_sha256,"
                    "symbol_count,memo,active) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,FALSE)",
                    (rid,region,revision,package.source_file,package.source_sha256,
                     package.package_sha256,len(prepared),package.memo),
                )
                for key,item in prepared.items():
                    cur.execute(
                        "INSERT INTO symbol_defs(revision_id,symbol_key,payload_json) "
                        "VALUES(%s,%s,%s::jsonb)",
                        (rid,key,json.dumps(item,ensure_ascii=False)),
                    )
                cur.execute("UPDATE symbol_revisions SET active=FALSE WHERE region_code=%s",(region,))
                cur.execute("UPDATE symbol_revisions SET active=TRUE WHERE id=%s",(rid,))
                conn.commit()
            return {"ok":True,"group_id":"SYMBOL","region_code":region,
                    "revision":revision,"revision_id":rid,"symbol_count":len(prepared),"active":True}

    if not _has_route(app,"/admin/drawings/{region}/symbol-revisions","GET"):
        @app.get("/admin/drawings/{region}/symbol-revisions")
        async def symbol_revisions(region:str,request:Request):
            region=str(region or "").strip().upper()
            await _require_probe(request,"/admin/settings/session-timeout")
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute(
                    "SELECT id,revision,source_file,source_sha256,package_sha256,"
                    "symbol_count,memo,active,created_at FROM symbol_revisions "
                    "WHERE region_code=%s ORDER BY revision DESC",(region,)
                )
                rows=cur.fetchall()
            return [
                {"id":r[0],"group_id":"SYMBOL","revision":int(r[1]),"source_file":r[2],
                 "source_sha256":r[3],"package_sha256":r[4],"object_count":int(r[5]),
                 "symbol_count":int(r[5]),"memo":r[6],"active":bool(r[7]),
                 "created_at":r[8].isoformat() if hasattr(r[8],"isoformat") else str(r[8])}
                for r in rows
            ]

    if not _has_route(app,"/admin/drawings/{region}/symbol-revisions/{revision_id}/restore","POST"):
        @app.post("/admin/drawings/{region}/symbol-revisions/{revision_id}/restore")
        async def restore_symbol(region:str,revision_id:str,request:Request):
            region=str(region or "").strip().upper()
            await _require_probe(request,"/admin/settings/session-timeout")
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute(
                    "SELECT revision FROM symbol_revisions WHERE id=%s AND region_code=%s",
                    (revision_id,region),
                )
                row=cur.fetchone()
                if not row: raise HTTPException(404,"심볼 백업을 찾을 수 없습니다.")
                cur.execute("UPDATE symbol_revisions SET active=FALSE WHERE region_code=%s",(region,))
                cur.execute("UPDATE symbol_revisions SET active=TRUE WHERE id=%s",(revision_id,))
                conn.commit()
            return {"ok":True,"group_id":"SYMBOL","region_code":region,
                    "revision":int(row[0]),"revision_id":revision_id,"active":True}

    return {
        "database":"PostgreSQL/PostGIS",
        "settings_table":_settings_table(),
        "revision_table":_revision_spec()[0],
        "map_settings":_read_settings(),
    }
PY

cat >> "${ENTRY_FILE}" <<'PY'

# === CMB_FINAL_RUNTIME_PATCH_V3_BEGIN ===
from cmb_final_runtime_patch import install as _cmb_install_final_runtime_patch
_CMB_FINAL_RUNTIME_INFO = _cmb_install_final_runtime_patch(app)
# === CMB_FINAL_RUNTIME_PATCH_V3_END ===
PY

echo "[6/9] 오래된 SQLite 보조 DB 제거 준비"
for old in   /var/lib/cmb-server/map_display.sqlite3   /var/lib/cmb-server/cmb.sqlite3
do
  if [[ -f "${old}" ]]; then
    mv "${old}" "${BACKUP_DIR}/obsolete-$(basename "${old}")-${STAMP}"
    echo "REMOVED_OBSOLETE_DB=${old}"
  fi
done

echo "[7/9] 문법 + 실제 ASGI + PostgreSQL 라우트 검사"
"${PYTHON_BIN}" -m py_compile "${ENTRY_FILE}" "${APP_DIR}/${PATCH_MODULE}"
(
  cd "${APP_DIR}"
  PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" - <<PY
import importlib
m=importlib.import_module("${ENTRY_MODULE}")
app=m.app
required={
 ("/settings/map-display","GET"),
 ("/admin/settings/map-display","GET"),
 ("/admin/settings/map-display","POST"),
 ("/online/{region}/versions","GET"),
 ("/online/{region}/symbols","GET"),
 ("/admin/drawings/{region}/symbols","POST"),
 ("/admin/drawings/{region}/symbol-revisions","GET"),
 ("/admin/drawings/{region}/symbol-revisions/{revision_id}/restore","POST"),
}
actual=set()
for route in app.routes:
    for method in (getattr(route,"methods",None) or []):
        actual.add((getattr(route,"path",""),method))
missing=sorted(required-actual)
print("FINAL_RUNTIME_INFO",getattr(m,"_CMB_FINAL_RUNTIME_INFO",{}))
print("CACHE_ROUTES",sorted(x for x in actual if "/versions" in x[0] or "/symbols" in x[0]))
if missing: raise SystemExit("MISSING_ROUTES="+repr(missing))
print("ASGI_POSTGRES_FINAL_OK")
PY
)

echo "[8/9] 서비스 재시작"
systemctl restart "${SERVICE_NAME}"
for i in {1..15}; do
  if systemctl is-active --quiet "${SERVICE_NAME}"; then
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done
if ! systemctl is-active --quiet "${SERVICE_NAME}"; then
  journalctl -u "${SERVICE_NAME}" -n 120 --no-pager || true
  false
fi

echo "[9/9] 최종 서버 구성 확인"
(
  cd "${APP_DIR}"
  PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" - <<PY
import importlib
m=importlib.import_module("${ENTRY_MODULE}")
print(getattr(m,"_CMB_FINAL_RUNTIME_INFO",{}))
PY
)

trap - ERR

echo
echo "============================================================"
echo "CMB FINAL SERVER V3 적용 완료"
echo "- 현재 실행 서버 1개 유지"
echo "- PostgreSQL/PostGIS 운영 DB 1개 사용"
echo "- SQLite 보조/중복 DB 제거"
echo "- FIBER/COAX/POLE/CONDUIT/USER Revision 기존 DB 사용"
echo "- SYMBOL Revision 동일 PostgreSQL DB 사용"
echo "- /online/{region}/versions 추가"
echo "- /online/{region}/symbols 추가"
echo "- Windows/Android Revision 캐시 지원"
echo "- 지도 반경/재조회 거리 운영 DB 저장"
echo "- 백업: ${BACKUP}"
echo "============================================================"
echo "CMB_FINAL_SERVER_V3"
