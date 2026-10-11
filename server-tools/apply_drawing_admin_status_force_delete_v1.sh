#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"
APP_DIR="${CMB_APP_DIR:-/home/ysjus/cmb-server}"
ENTRY_FILE="${APP_DIR}/cmb_asgi.py"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"
BACKUP_DIR="/home/ysjus/cmb-server-backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "${BACKUP_DIR}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: sudo bash 로 실행해주세요."
  exit 1
fi

MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE_NAME}")"
if [[ -z "${MAIN_PID}" || "${MAIN_PID}" == "0" || ! -r "/proc/${MAIN_PID}/environ" ]]; then
  echo "ERROR: 실행 중인 ${SERVICE_NAME} 환경을 읽을 수 없습니다."
  exit 1
fi

while IFS= read -r -d '' item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

echo "[1/7] 백업"
tar -C "${APP_DIR}" -czf "${BACKUP_DIR}/cmb-before-drawing-admin-v1-${STAMP}.tgz"   "$(basename "${ENTRY_FILE}")" 2>/dev/null || true

echo "[2/7] 도면 현황/강제삭제 API 설치"
cat > "${APP_DIR}/cmb_drawing_admin_patch.py" <<'PY'
from __future__ import annotations
import hashlib, os, re
from fastapi import HTTPException, Request

def _connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception:
        import psycopg2
        return psycopg2.connect(dsn or "")

def _admin_user(request: Request):
    auth=str(request.headers.get("authorization") or "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401,"로그인이 필요합니다.")
    token=auth.split(" ",1)[1].strip()
    token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connect() as conn:
        cur=conn.cursor()
        cur.execute("""
            SELECT u.id,u.username,u.level,u.active
            FROM auth_sessions s
            JOIN app_users u ON u.id=s.user_id
            WHERE s.access_hash=%s
              AND s.revoked=FALSE
              AND s.access_expires>NOW()
              AND u.active=TRUE
            ORDER BY s.id DESC LIMIT 1
        """,(token_hash,))
        row=cur.fetchone()
    if not row:
        raise HTTPException(401,"세션이 만료되었습니다.")
    if int(row[2])!=1:
        raise HTTPException(403,"1등급 관리자만 사용할 수 있습니다.")
    return {"id":row[0],"username":row[1],"level":row[2]}

def _safe_region_id(region_id):
    rid=str(region_id or "").strip()
    if not rid or len(rid)>200 or not re.fullmatch(r"[A-Za-z0-9_.-]+",rid):
        raise HTTPException(400,"잘못된 지역코드입니다.")
    return rid

def _table_exists(cur, table):
    cur.execute("""
        SELECT EXISTS(
          SELECT 1 FROM information_schema.tables
          WHERE table_schema='public' AND table_name=%s
        )
    """,(table,))
    return bool(cur.fetchone()[0])

def _columns(cur, table):
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
    """,(table,))
    return {r[0] for r in cur.fetchall()}

def _route_exists(app,path,method):
    method=method.upper()
    return any(
        getattr(r,"path",None)==path
        and method in (getattr(r,"methods",None) or set())
        for r in getattr(app,"routes",[])
    )

def _ensure_region(cur,rid):
    cur.execute("SELECT name FROM regions WHERE id=%s",(rid,))
    row=cur.fetchone()
    if not row:
        raise HTTPException(404,"지역을 찾을 수 없습니다.")
    return row[0]

def install(app):
    if not _route_exists(app,"/admin/drawings/{region_id}/status","GET"):
        @app.get("/admin/drawings/{region_id}/status")
        async def drawing_status(region_id:str, request:Request):
            _admin_user(request)
            rid=_safe_region_id(region_id)
            groups=[]
            with _connect() as conn:
                cur=conn.cursor()
                name=_ensure_region(cur,rid)

                if _table_exists(cur,"drawing_group_revisions"):
                    cols=_columns(cur,"drawing_group_revisions")
                    fields=["id","region_code"]
                    for f in ("group_id","revision","active","object_count","created_at","memo"):
                        if f in cols: fields.append(f)
                    cur.execute(
                        "SELECT "+",".join(fields)+" FROM drawing_group_revisions WHERE region_code=%s ORDER BY "+
                        ("group_id," if "group_id" in cols else "")+
                        ("active DESC," if "active" in cols else "")+
                        ("revision DESC" if "revision" in cols else "id DESC"),
                        (rid,),
                    )
                    for row in cur.fetchall():
                        d=dict(zip(fields,row))
                        groups.append({
                            "group_id":d.get("group_id") or "DRAWING",
                            "revision":d.get("revision"),
                            "active":bool(d.get("active",True)),
                            "object_count":int(d.get("object_count") or 0),
                            "created_at":d.get("created_at").isoformat() if d.get("created_at") else None,
                            "memo":d.get("memo"),
                            "source":"drawing_group_revisions",
                        })

                if _table_exists(cur,"symbol_revisions"):
                    cols=_columns(cur,"symbol_revisions")
                    fields=["id","region_code"]
                    for f in ("revision","active","symbol_count","object_count","created_at","memo"):
                        if f in cols: fields.append(f)
                    cur.execute(
                        "SELECT "+",".join(fields)+" FROM symbol_revisions WHERE region_code=%s ORDER BY "+
                        ("active DESC," if "active" in cols else "")+
                        ("revision DESC" if "revision" in cols else "id DESC"),
                        (rid,),
                    )
                    for row in cur.fetchall():
                        d=dict(zip(fields,row))
                        groups.append({
                            "group_id":"SYMBOL",
                            "revision":d.get("revision"),
                            "active":bool(d.get("active",True)),
                            "object_count":int(d.get("symbol_count") or d.get("object_count") or 0),
                            "created_at":d.get("created_at").isoformat() if d.get("created_at") else None,
                            "memo":d.get("memo"),
                            "source":"symbol_revisions",
                        })

                # legacy/current dataset storage fallback summary
                if _table_exists(cur,"datasets"):
                    cur.execute("SELECT id,active_version FROM datasets WHERE region_id=%s ORDER BY id",(rid,))
                    ds=cur.fetchall()
                    if ds and not groups:
                        object_total=0
                        if _table_exists(cur,"cad_objects"):
                            ids=[r[0] for r in ds]
                            placeholders=",".join(["%s"]*len(ids))
                            cur.execute(f"SELECT COUNT(*) FROM cad_objects WHERE dataset_id IN ({placeholders})",tuple(ids))
                            object_total=int(cur.fetchone()[0])
                        groups.append({
                            "group_id":"DATASET",
                            "revision":None,
                            "active":True,
                            "object_count":object_total,
                            "created_at":None,
                            "memo":"legacy dataset storage",
                            "source":"datasets",
                        })
            return {"ok":True,"region_id":rid,"region_name":name,"groups":groups}

    if not _route_exists(app,"/admin/drawings/{region_id}/force","DELETE"):
        @app.delete("/admin/drawings/{region_id}/force")
        async def force_delete_drawing(region_id:str, request:Request):
            _admin_user(request)
            rid=_safe_region_id(region_id)
            deleted={}
            with _connect() as conn:
                cur=conn.cursor()
                name=_ensure_region(cur,rid)

                # 1) dataset/cad_objects path
                if _table_exists(cur,"datasets"):
                    cur.execute("SELECT id FROM datasets WHERE region_id=%s",(rid,))
                    dataset_ids=[r[0] for r in cur.fetchall()]
                    if dataset_ids:
                        ph=",".join(["%s"]*len(dataset_ids))
                        if _table_exists(cur,"cad_objects"):
                            cur.execute(f"DELETE FROM cad_objects WHERE dataset_id IN ({ph})",tuple(dataset_ids))
                            deleted["cad_objects"]=cur.rowcount
                        cols=_columns(cur,"datasets")
                        if "active_version" in cols:
                            cur.execute(f"UPDATE datasets SET active_version=NULL WHERE id IN ({ph})",tuple(dataset_ids))
                        if _table_exists(cur,"dataset_versions"):
                            cur.execute(f"DELETE FROM dataset_versions WHERE dataset_id IN ({ph})",tuple(dataset_ids))
                            deleted["dataset_versions"]=cur.rowcount
                        cur.execute("DELETE FROM datasets WHERE region_id=%s",(rid,))
                        deleted["datasets"]=cur.rowcount

                # 2) drawing-group path
                if _table_exists(cur,"drawing_group_revisions"):
                    if _table_exists(cur,"drawing_group_objects"):
                        cur.execute("""
                            DELETE FROM drawing_group_objects
                            WHERE revision_id IN (
                                SELECT id FROM drawing_group_revisions WHERE region_code=%s
                            )
                        """,(rid,))
                        deleted["drawing_group_objects"]=cur.rowcount
                    cur.execute("DELETE FROM drawing_group_revisions WHERE region_code=%s",(rid,))
                    deleted["drawing_group_revisions"]=cur.rowcount

                # 3) symbol path
                if _table_exists(cur,"symbol_revisions"):
                    if _table_exists(cur,"symbol_defs"):
                        cols=_columns(cur,"symbol_defs")
                        if "revision_id" in cols:
                            cur.execute("""
                                DELETE FROM symbol_defs
                                WHERE revision_id IN (
                                    SELECT id FROM symbol_revisions WHERE region_code=%s
                                )
                            """,(rid,))
                            deleted["symbol_defs"]=cur.rowcount
                        elif "region_code" in cols:
                            cur.execute("DELETE FROM symbol_defs WHERE region_code=%s",(rid,))
                            deleted["symbol_defs"]=cur.rowcount
                    cur.execute("DELETE FROM symbol_revisions WHERE region_code=%s",(rid,))
                    deleted["symbol_revisions"]=cur.rowcount

                # IMPORTANT: regions/user_regions are intentionally preserved.
                conn.commit()

            return {
                "ok":True,
                "region_id":rid,
                "region_name":name,
                "deleted":deleted,
                "region_preserved":True,
                "user_region_permissions_preserved":True,
            }
PY

echo "[3/7] cmb_asgi.py 연결"
"${PYTHON_BIN}" - <<PY
from pathlib import Path
import re
p=Path(r"${ENTRY_FILE}")
text=p.read_text(encoding="utf-8")
begin="# === CMB_DRAWING_ADMIN_PATCH_V1_BEGIN ==="
end="# === CMB_DRAWING_ADMIN_PATCH_V1_END ==="
block='''# === CMB_DRAWING_ADMIN_PATCH_V1_BEGIN ===
try:
    import cmb_drawing_admin_patch
    cmb_drawing_admin_patch.install(app)
except Exception as exc:
    print("CMB_DRAWING_ADMIN_PATCH_ERROR", repr(exc))
# === CMB_DRAWING_ADMIN_PATCH_V1_END ===
'''
text=re.sub(r"\n?# === CMB_DRAWING_ADMIN_PATCH_V1_BEGIN ===.*?# === CMB_DRAWING_ADMIN_PATCH_V1_END ===\n?", "\n", text, flags=re.S)
p.write_text(text.rstrip()+"\n\n"+block, encoding="utf-8")
PY

echo "[4/7] 문법 검사"
"${PYTHON_BIN}" -m py_compile "${APP_DIR}/cmb_drawing_admin_patch.py" "${ENTRY_FILE}"
echo "PY_COMPILE_OK"

echo "[5/7] 서비스 재시작"
systemctl restart "${SERVICE_NAME}"
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8000/health >/dev/null

echo "[6/7] 라우트 확인"
cd "${APP_DIR}"
PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" <<'PY'
import cmb_asgi
wanted={
 ("GET","/admin/drawings/{region_id}/status"),
 ("DELETE","/admin/drawings/{region_id}/force"),
}
found=set()
for r in cmb_asgi.app.routes:
    path=getattr(r,"path","")
    for m in (getattr(r,"methods",None) or []):
        if (m,path) in wanted:
            found.add((m,path))
print("DRAWING_ADMIN_ROUTES",sorted(found))
if found != wanted:
    raise SystemExit("DRAWING_ADMIN_ROUTE_CHECK_FAILED")
PY

echo "[7/7] 완료"
echo "============================================================"
echo "CMB_DRAWING_ADMIN_PATCH_V1_OK"
echo "GET    /admin/drawings/{region_id}/status"
echo "DELETE /admin/drawings/{region_id}/force"
echo "- regions 유지"
echo "- user_regions 유지"
echo "- 도면/버전/심볼 데이터만 삭제"
echo "BACKUP=${BACKUP_DIR}/cmb-before-drawing-admin-v1-${STAMP}.tgz"
echo "============================================================"
