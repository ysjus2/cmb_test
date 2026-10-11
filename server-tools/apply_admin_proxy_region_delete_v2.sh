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

echo "============================================================"
echo " CMB 관리자 API 404 + 지역 강제삭제 V2"
echo " - 신규 /admin/* 경로 nginx 프록시"
echo " - 지역 삭제 시 도면/심볼/권한 연쇄 정리"
echo " - PostgreSQL/PostGIS 유지, SQLite 사용 안함"
echo "============================================================"

echo "[1/8] 서버/DB 사전 점검"
"${PYTHON_BIN}" <<'PY'
import os

def connect():
    dsn = next((os.getenv(k) for k in (
        "DATABASE_URL","CMB_DATABASE_URL","DB_URL","POSTGRES_DSN","PG_DSN"
    ) if os.getenv(k)), None)
    try:
        import psycopg
        return psycopg.connect(dsn or "")
    except Exception:
        import psycopg2
        return psycopg2.connect(dsn or "")

with connect() as conn:
    cur = conn.cursor()
    cur.execute("SELECT current_database(), current_user")
    print("DB =", cur.fetchone())
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
        ORDER BY table_name
    """)
    tables = [r[0] for r in cur.fetchall()]
    print("TABLES =", tables)
    for required in ("regions","user_regions","drawing_group_revisions","drawing_group_objects"):
        if required not in tables:
            raise SystemExit("ERROR: 필수 테이블 없음: " + required)
print("DB_PREFLIGHT_OK")
PY

echo "[2/8] 백업"
tar -C "${APP_DIR}" -czf "${BACKUP_DIR}/cmb-before-region-delete-v2-${STAMP}.tgz"   "$(basename "${ENTRY_FILE}")" cmb_region_admin_patch.py 2>/dev/null || true

NGINX_CONF="$("${PYTHON_BIN}" <<'PY'
from pathlib import Path
roots=[Path("/etc/nginx/sites-enabled"),Path("/etc/nginx/conf.d"),Path("/etc/nginx/sites-available")]
seen=[]
for root in roots:
    if not root.exists():
        continue
    for p in root.iterdir():
        try:
            rp=p.resolve()
            if not rp.is_file() or rp in seen:
                continue
            text=rp.read_text(encoding="utf-8",errors="ignore")
            if "8443" in text and "proxy_pass" in text:
                seen.append(rp)
        except Exception:
            pass
print(str(seen[0]) if len(seen)==1 else "")
if len(seen)>1:
    print("MULTIPLE:"+"|".join(map(str,seen)), file=__import__("sys").stderr)
PY
)"

if [[ -z "${NGINX_CONF}" ]]; then
  echo "ERROR: 8443 프록시 nginx 설정 파일을 하나로 특정하지 못했습니다."
  nginx -T 2>&1 | grep -nE 'configuration file|8443|proxy_pass' | tail -120
  exit 1
fi

echo "NGINX_CONF=${NGINX_CONF}"
cp -a "${NGINX_CONF}" "${BACKUP_DIR}/$(basename "${NGINX_CONF}").before-admin-proxy-${STAMP}"

echo "[3/8] nginx /admin/* 프록시 보강"
NGINX_CONF="${NGINX_CONF}" "${PYTHON_BIN}" <<'PY'
import os,re
from pathlib import Path
p=Path(os.environ["NGINX_CONF"])
text=p.read_text(encoding="utf-8")
marker="# CMB_ADMIN_API_PROXY_V2"
if marker in text:
    print("NGINX_ADMIN_PROXY_ALREADY_PRESENT")
    raise SystemExit(0)

# listen 8443이 들어있는 server 블록을 brace matching으로 찾는다.
m=re.search(r"\bserver\s*\{", text)
blocks=[]
while m:
    start=m.start()
    brace=text.find("{",m.start())
    depth=0
    end=None
    for i in range(brace,len(text)):
        if text[i]=="{": depth+=1
        elif text[i]=="}":
            depth-=1
            if depth==0:
                end=i
                break
    if end is None: break
    block=text[start:end+1]
    if re.search(r"listen\s+[^;]*8443", block):
        blocks.append((start,end,block))
    m=re.search(r"\bserver\s*\{", text[end+1:] if end else "")
    if m and end:
        m=re.Match if False else None
        # manual next search
        nm=re.search(r"\bserver\s*\{", text[end+1:])
        if nm:
            class X:
                def start(self): return end+1+nm.start()
            m=X()
        else:
            m=None

if len(blocks)!=1:
    raise SystemExit(f"ERROR: listen 8443 server block count={len(blocks)}")

start,end,block=blocks[0]
insert=r'''
    # CMB_ADMIN_API_PROXY_V2
    location ^~ /admin/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

'''
new=text[:end]+insert+text[end:]
p.write_text(new,encoding="utf-8")
print("NGINX_ADMIN_PROXY_V2_ADDED")
PY

echo "[4/8] 지역 삭제 API를 연쇄 삭제 방식으로 교체"
cat > "${APP_DIR}/cmb_region_admin_patch.py" <<'PY'
from __future__ import annotations
import hashlib, os, re
from fastapi import HTTPException, Request
from pydantic import BaseModel

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

class RegionUpdateBody(BaseModel):
    name: str

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

def install(app):
    if not _route_exists(app,"/admin/regions/{region_id}","PUT"):
        @app.put("/admin/regions/{region_id}")
        async def update_region(region_id:str, body:RegionUpdateBody, request:Request):
            _admin_user(request)
            rid=_safe_region_id(region_id)
            name=str(body.name or "").strip()
            if not name:
                raise HTTPException(400,"지역명을 입력해주세요.")
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute("UPDATE regions SET name=%s WHERE id=%s",(name,rid))
                if cur.rowcount!=1:
                    raise HTTPException(404,"지역을 찾을 수 없습니다.")
                conn.commit()
            return {"ok":True,"id":rid,"name":name}

    if not _route_exists(app,"/admin/regions/{region_id}","DELETE"):
        @app.delete("/admin/regions/{region_id}")
        async def delete_region(region_id:str, request:Request):
            _admin_user(request)
            rid=_safe_region_id(region_id)
            deleted={}
            with _connect() as conn:
                cur=conn.cursor()
                cur.execute("SELECT name FROM regions WHERE id=%s",(rid,))
                row=cur.fetchone()
                if not row:
                    raise HTTPException(404,"지역을 찾을 수 없습니다.")
                region_name=row[0]

                # drawing_group_objects -> drawing_group_revisions
                cur.execute("SELECT id FROM drawing_group_revisions WHERE region_code=%s",(rid,))
                revision_ids=[r[0] for r in cur.fetchall()]
                if revision_ids:
                    cur.execute(
                        "DELETE FROM drawing_group_objects WHERE revision_id = ANY(%s)",
                        (revision_ids,)
                    )
                    deleted["drawing_group_objects"]=cur.rowcount
                else:
                    deleted["drawing_group_objects"]=0

                cur.execute("DELETE FROM drawing_group_revisions WHERE region_code=%s",(rid,))
                deleted["drawing_group_revisions"]=cur.rowcount

                # SYMBOL defs -> revisions
                if _table_exists(cur,"symbol_revisions"):
                    cur.execute("SELECT id FROM symbol_revisions WHERE region_code=%s",(rid,))
                    symbol_rev_ids=[r[0] for r in cur.fetchall()]
                    if _table_exists(cur,"symbol_defs") and symbol_rev_ids:
                        cols=_columns(cur,"symbol_defs")
                        if "revision_id" in cols:
                            cur.execute(
                                "DELETE FROM symbol_defs WHERE revision_id = ANY(%s)",
                                (symbol_rev_ids,)
                            )
                            deleted["symbol_defs"]=cur.rowcount
                        elif "region_code" in cols:
                            cur.execute("DELETE FROM symbol_defs WHERE region_code=%s",(rid,))
                            deleted["symbol_defs"]=cur.rowcount
                    cur.execute("DELETE FROM symbol_revisions WHERE region_code=%s",(rid,))
                    deleted["symbol_revisions"]=cur.rowcount

                # legacy cad_objects가 지역 컬럼을 갖는 경우 같이 정리
                if _table_exists(cur,"cad_objects"):
                    cols=_columns(cur,"cad_objects")
                    if "region_code" in cols:
                        cur.execute("DELETE FROM cad_objects WHERE region_code=%s",(rid,))
                        deleted["cad_objects"]=cur.rowcount
                    elif "region_id" in cols:
                        cur.execute("DELETE FROM cad_objects WHERE region_id=%s",(rid,))
                        deleted["cad_objects"]=cur.rowcount

                cur.execute("DELETE FROM user_regions WHERE region_id=%s",(rid,))
                deleted["user_regions"]=cur.rowcount

                cur.execute("DELETE FROM regions WHERE id=%s",(rid,))
                if cur.rowcount!=1:
                    raise HTTPException(404,"지역을 찾을 수 없습니다.")
                deleted["regions"]=cur.rowcount
                conn.commit()

            return {
                "ok":True,
                "id":rid,
                "name":region_name,
                "deleted":deleted,
            }
PY

echo "[5/8] Python 문법 검사"
"${PYTHON_BIN}" -m py_compile "${APP_DIR}/cmb_region_admin_patch.py" "${ENTRY_FILE}"
echo "PY_COMPILE_OK"

echo "[6/8] nginx 검사/적용"
nginx -t
systemctl reload nginx
systemctl restart "${SERVICE_NAME}"

echo "[7/8] health/라우트 확인"
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "SERVER_READY ${i}s"
    break
  fi
  sleep 1
done

cd "${APP_DIR}"
PYTHONPATH="${APP_DIR}" "${PYTHON_BIN}" <<'PY'
import cmb_asgi
wanted={
 ("PUT","/admin/regions/{region_id}"),
 ("DELETE","/admin/regions/{region_id}"),
 ("POST","/admin/drawings/{region}/symbols"),
}
found=set()
for r in cmb_asgi.app.routes:
    path=getattr(r,"path","")
    for m in (getattr(r,"methods",None) or []):
        if (m,path) in wanted:
            found.add((m,path))
print("ROUTES_FOUND =",sorted(found))
if ("PUT","/admin/regions/{region_id}") not in found or ("DELETE","/admin/regions/{region_id}") not in found:
    raise SystemExit("REGION_ADMIN_ROUTE_CHECK_FAILED")
PY

echo "[8/8] nginx 경유 확인"
TMP1="$(mktemp)"
CODE1="$(curl -k -sS -o "${TMP1}" -w '%{http_code}' -X DELETE https://127.0.0.1:8443/admin/regions/__cmb_probe__ || true)"
echo "DELETE_PROXY_HTTP=${CODE1}"
head -c 300 "${TMP1}" || true
echo
rm -f "${TMP1}"

if [[ "${CODE1}" == "404" ]]; then
  echo "ERROR: nginx가 여전히 신규 /admin/* 경로를 FastAPI로 전달하지 않습니다."
  exit 1
fi

echo "============================================================"
echo "CMB_ADMIN_PROXY_REGION_DELETE_V2_OK"
echo "- SYMBOL 신규 경로 nginx 전달"
echo "- 지역 PUT/DELETE 신규 경로 nginx 전달"
echo "- 지역 삭제 시 도면/심볼/권한 연결 연쇄 삭제"
echo "============================================================"
