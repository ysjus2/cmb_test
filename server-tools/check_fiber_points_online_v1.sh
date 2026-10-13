#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cmb-server}"
SERVICE_NAME="${SERVICE_NAME:-cmb-cad-api}"
PYTHON_BIN="${PYTHON_BIN:-${APP_DIR}/.venv/bin/python}"

MAIN_PID="$(systemctl show -p MainPID --value "${SERVICE_NAME}" 2>/dev/null || true)"
if [[ -z "${MAIN_PID}" || "${MAIN_PID}" == "0" ]]; then
  echo "ERROR: ${SERVICE_NAME} MainPID를 찾지 못했습니다."
  exit 1
fi

while IFS= read -r item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

"${PYTHON_BIN}" <<'PY'
import os, json

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

def cols(cur, table):
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
    """,(table,))
    return {r[0] for r in cur.fetchall()}

with connect() as conn:
    cur=conn.cursor()
    rcols=cols(cur,"drawing_group_revisions")
    ocols=cols(cur,"drawing_group_objects")

    cur.execute("""
        SELECT id,region_code,revision,object_count,created_at
        FROM drawing_group_revisions
        WHERE UPPER(group_id)='FIBER' AND active=TRUE
        ORDER BY created_at DESC
    """)
    revs=cur.fetchall()
    if not revs:
        raise SystemExit("NO_ACTIVE_FIBER_REVISION")

    print("="*90)
    print("CMB FIBER ACTIVE REVISION / GEOMETRY CHECK")
    print("="*90)

    geom_col = "geometry" if "geometry" in ocols else ("geom" if "geom" in ocols else None)
    attrs_col = "attributes" if "attributes" in ocols else None
    layer_col = "layer" if "layer" in ocols else None
    block_col = "block_name" if "block_name" in ocols else None
    entity_col = "entity_type" if "entity_type" in ocols else None

    if not geom_col:
        print("ERROR: geometry/geom 컬럼을 찾지 못했습니다.")
        print("object columns =", sorted(ocols))
        raise SystemExit(2)

    for rid, region, revision, meta_count, created_at in revs:
        print()
        print(f"REGION={region} REVISION={revision} META={meta_count} ID={rid} CREATED={created_at}")

        cur.execute(
            f"""
            SELECT ST_GeometryType({geom_col}), COUNT(*)
            FROM drawing_group_objects
            WHERE revision_id=%s
            GROUP BY ST_GeometryType({geom_col})
            ORDER BY 1
            """,
            (rid,),
        )
        geo_rows=cur.fetchall()
        print("GEOMETRY_COUNTS:")
        for typ,cnt in geo_rows:
            print(f"  {typ}: {cnt}")

        point_count=sum(int(cnt) for typ,cnt in geo_rows if str(typ).upper().endswith("POINT"))
        line_count=sum(int(cnt) for typ,cnt in geo_rows if "LINESTRING" in str(typ).upper())
        print(f"POINT_TOTAL={point_count}")
        print(f"LINE_TOTAL={line_count}")

        select_cols=[]
        if layer_col: select_cols.append(layer_col)
        if block_col: select_cols.append(block_col)
        if entity_col: select_cols.append(entity_col)
        if attrs_col: select_cols.append(attrs_col)

        if point_count and select_cols:
            cur.execute(
                f"""
                SELECT {",".join(select_cols)}
                FROM drawing_group_objects
                WHERE revision_id=%s
                  AND ST_GeometryType({geom_col})='ST_Point'
                LIMIT 200
                """,
                (rid,),
            )
            print("POINT_SAMPLES:")
            for row in cur.fetchall():
                data=dict(zip(select_cols,row))
                attrs=data.get(attrs_col) if attrs_col else None
                if isinstance(attrs,str):
                    try: attrs=json.loads(attrs)
                    except Exception: pass
                symbol=""
                is_device=""
                if isinstance(attrs,dict):
                    symbol=attrs.get("_cmb_symbol_kind","")
                    is_device=attrs.get("_cmb_is_device","")
                print(
                    "  layer=",data.get(layer_col,"") if layer_col else "",
                    " block=",data.get(block_col,"") if block_col else "",
                    " entity=",data.get(entity_col,"") if entity_col else "",
                    " symbol=",symbol,
                    " is_device=",is_device,
                )

        if point_count==0:
            print("RESULT=FIBER_POINT_MISSING_IN_DB")
        else:
            print("RESULT=FIBER_POINT_PRESENT_IN_DB")

    print("="*90)
PY
