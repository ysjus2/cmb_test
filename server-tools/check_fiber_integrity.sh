#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${CMB_SERVICE_NAME:-cmb-cad-api}"
APP_DIR="${CMB_APP_DIR:-/home/ysjus/cmb-server}"
PYTHON_BIN="${APP_DIR}/.venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="${APP_DIR}/venv/bin/python"
[[ -x "${PYTHON_BIN}" ]] || PYTHON_BIN="$(command -v python3)"

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

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations
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

def table_exists(cur, table):
    cur.execute("""
        SELECT EXISTS(
          SELECT 1 FROM information_schema.tables
          WHERE table_schema='public' AND table_name=%s
        )
    """,(table,))
    return bool(cur.fetchone()[0])

def columns(cur, table):
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
    """,(table,))
    return {r[0] for r in cur.fetchall()}

print("="*72)
print("CMB FIBER INTEGRITY CHECK")
print("="*72)

with connect() as conn:
    cur=conn.cursor()

    if not table_exists(cur,"drawing_group_revisions"):
        print("ERROR: drawing_group_revisions 테이블 없음")
        raise SystemExit(2)
    if not table_exists(cur,"drawing_group_objects"):
        print("ERROR: drawing_group_objects 테이블 없음")
        raise SystemExit(2)

    rcols=columns(cur,"drawing_group_revisions")
    ocols=columns(cur,"drawing_group_objects")
    print("revision columns:", sorted(rcols))
    print("object columns:", sorted(ocols))
    print()

    required={"id","region_code","group_id"}
    if not required.issubset(rcols):
        print("ERROR: revision 필수 컬럼 부족:", sorted(required-rcols))
        raise SystemExit(2)
    if "revision_id" not in ocols:
        print("ERROR: drawing_group_objects.revision_id 없음")
        raise SystemExit(2)

    fields=["id","region_code","group_id"]
    for f in ("revision","active","object_count","created_at","source_file","package_sha256"):
        if f in rcols:
            fields.append(f)

    where="UPPER(group_id)='FIBER'"
    if "active" in rcols:
        where += " AND active=TRUE"

    cur.execute(
        "SELECT "+",".join(fields)+
        " FROM drawing_group_revisions WHERE "+where+
        " ORDER BY region_code"
    )
    rows=cur.fetchall()

    if not rows:
        print("FIBER active revision 없음")
        raise SystemExit(1)

    bad=0
    total_meta=0
    total_db=0

    for row in rows:
        d=dict(zip(fields,row))
        rid=d["id"]
        region=d["region_code"]
        cur.execute("SELECT COUNT(*) FROM drawing_group_objects WHERE revision_id=%s",(rid,))
        actual=int(cur.fetchone()[0])
        meta=int(d.get("object_count") or 0)
        total_meta += meta
        total_db += actual
        ok=(meta==actual) if meta else True
        if not ok:
            bad += 1
        status="OK" if ok else "MISMATCH"
        print(
            f"{status:8} region={region} revision={d.get('revision')} "
            f"meta={meta} db={actual} id={rid}"
        )

        # 가능한 경우 객체 ID 중복도 검사
        ident_col=None
        for candidate in ("regional_object_id","object_id","source_handle"):
            if candidate in ocols:
                ident_col=candidate
                break
        if ident_col:
            cur.execute(
                f"""SELECT COUNT(*) FROM (
                    SELECT {ident_col}
                    FROM drawing_group_objects
                    WHERE revision_id=%s
                      AND {ident_col} IS NOT NULL
                      AND CAST({ident_col} AS text)<>''
                    GROUP BY {ident_col}
                    HAVING COUNT(*)>1
                ) q""",
                (rid,),
            )
            dup=int(cur.fetchone()[0])
            if dup:
                print(f"         duplicate_{ident_col}={dup}")

    print("-"*72)
    print(f"TOTAL meta={total_meta} db={total_db} mismatch_regions={bad}")
    if bad:
        print("RESULT=FIBER_DB_MISMATCH")
        raise SystemExit(3)
    print("RESULT=FIBER_DB_OK")
PY
