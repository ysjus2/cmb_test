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
  exit 2
fi

while IFS= read -r -d '' item; do
  case "${item}" in
    DATABASE_URL=*|CMB_DATABASE_URL=*|DB_URL=*|POSTGRES_DSN=*|PG_DSN=*|PGHOST=*|PGPORT=*|PGDATABASE=*|PGUSER=*|PGPASSWORD=*|PGSSLMODE=*)
      export "${item}"
      ;;
  esac
done < "/proc/${MAIN_PID}/environ"

echo "======================================================================"
echo " CMB COORDINATE / BBOX PIPELINE CHECK V1"
echo " - GRID -> LAT/LON 전환 후 FIBER 좌표 조회 경로 점검"
echo " - DB geometry/SRID/bounds와 Viewer bbox 요청 구조 비교"
echo "======================================================================"

cd "${APP_DIR}"

"${PYTHON_BIN}" - <<'PY'
from __future__ import annotations
import os, inspect, json, math, re

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
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=%s
        ORDER BY ordinal_position
    """,(table,))
    return {r[0]:(r[1],r[2]) for r in cur.fetchall()}

def exists(cur, table):
    cur.execute("""
        SELECT EXISTS(
          SELECT 1 FROM information_schema.tables
          WHERE table_schema='public' AND table_name=%s
        )
    """,(table,))
    return bool(cur.fetchone()[0])

def fetchone(cur, sql, args=()):
    cur.execute(sql,args)
    return cur.fetchone()

def safe_num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None

print()
print("[1/5] TABLE / COLUMN")
with connect() as conn:
    cur=conn.cursor()
    for table in ("drawing_group_revisions","drawing_group_objects"):
        if not exists(cur,table):
            print("ERROR TABLE_MISSING",table)
            raise SystemExit(3)
        print(table)
        for name,(dtype,udt) in cols(cur,table).items():
            if name in {
                "id","region_code","group_id","active","revision_id","geometry","geom",
                "min_lat","max_lat","min_lon","max_lon","grid_id","grid_ids",
                "pole_lat","pole_lon","layer","regional_object_id"
            }:
                print(f"  {name:20} type={dtype} udt={udt}")

    rcols=cols(cur,"drawing_group_revisions")
    ocols=cols(cur,"drawing_group_objects")
    geom_col="geometry" if "geometry" in ocols else ("geom" if "geom" in ocols else None)
    if not geom_col:
        print("ERROR: geometry/geom 컬럼 없음")
        raise SystemExit(4)

    print()
    print("[2/5] ACTIVE FIBER REVISION / RAW COORDINATE")
    cur.execute("""
      SELECT id,region_code,revision,object_count,created_at
      FROM drawing_group_revisions
      WHERE UPPER(group_id)='FIBER'
        AND (active IS NULL OR active=TRUE)
      ORDER BY region_code,created_at DESC
    """)
    revs=cur.fetchall()
    if not revs:
        print("NO_ACTIVE_FIBER")
        raise SystemExit(5)

    for rid,region,revision,meta_count,created_at in revs:
        print()
        print(f"REGION={region} REV={revision} META={meta_count} RID={rid} CREATED={created_at}")
        cur.execute(f"""
          SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE {geom_col} IS NULL) AS null_geom,
            COUNT(*) FILTER (WHERE {geom_col} IS NOT NULL AND ST_IsEmpty({geom_col})) AS empty_geom
          FROM drawing_group_objects
          WHERE revision_id=%s
        """,(rid,))
        total,null_geom,empty_geom=cur.fetchone()
        print(f"  TOTAL={total} NULL_GEOM={null_geom} EMPTY_GEOM={empty_geom}")

        cur.execute(f"""
          SELECT ST_SRID({geom_col}),COUNT(*)
          FROM drawing_group_objects
          WHERE revision_id=%s AND {geom_col} IS NOT NULL
          GROUP BY ST_SRID({geom_col})
          ORDER BY 1
        """,(rid,))
        srids=cur.fetchall()
        print("  SRID_COUNTS=",srids)

        cur.execute(f"""
          SELECT
            ST_XMin(ST_Extent({geom_col})),
            ST_YMin(ST_Extent({geom_col})),
            ST_XMax(ST_Extent({geom_col})),
            ST_YMax(ST_Extent({geom_col}))
          FROM drawing_group_objects
          WHERE revision_id=%s AND {geom_col} IS NOT NULL
        """,(rid,))
        raw_extent=cur.fetchone()
        print("  RAW_EXTENT=",raw_extent)

        # 각 SRID별 WGS84 변환 가능 여부와 범위
        for srid,cnt in srids:
            try:
                srid=int(srid or 0)
            except Exception:
                srid=0
            if srid <= 0:
                print(f"  WARN SRID_INVALID srid={srid} count={cnt}")
                continue
            try:
                cur.execute(f"""
                  SELECT
                    ST_XMin(ST_Extent(ST_Transform({geom_col},4326))),
                    ST_YMin(ST_Extent(ST_Transform({geom_col},4326))),
                    ST_XMax(ST_Extent(ST_Transform({geom_col},4326))),
                    ST_YMax(ST_Extent(ST_Transform({geom_col},4326)))
                  FROM drawing_group_objects
                  WHERE revision_id=%s
                    AND {geom_col} IS NOT NULL
                    AND ST_SRID({geom_col})=%s
                """,(rid,srid))
                e=cur.fetchone()
                print(f"  WGS84_EXTENT_FROM_{srid}={e}")
                vals=[safe_num(x) for x in e]
                plausible=all(x is not None for x in vals) and (
                    -180 <= vals[0] <= 180 and -90 <= vals[1] <= 90 and
                    -180 <= vals[2] <= 180 and -90 <= vals[3] <= 90
                )
                print(f"  WGS84_PLAUSIBLE={plausible}")
            except Exception as exc:
                conn.rollback()
                print(f"  TRANSFORM_ERROR srid={srid}: {exc}")

        bbox_cols={"min_lat","max_lat","min_lon","max_lon"}.issubset(ocols)
        if bbox_cols:
            cur.execute("""
              SELECT
                COUNT(*) FILTER (
                  WHERE min_lat IS NULL OR max_lat IS NULL OR min_lon IS NULL OR max_lon IS NULL
                ),
                MIN(min_lon),MIN(min_lat),MAX(max_lon),MAX(max_lat)
              FROM drawing_group_objects
              WHERE revision_id=%s
            """,(rid,))
            null_bbox,minlon,minlat,maxlon,maxlat=cur.fetchone()
            print(f"  BBOX_COL_NULL={null_bbox}")
            print(f"  BBOX_COL_EXTENT=({minlon},{minlat},{maxlon},{maxlat})")
        else:
            print("  BBOX_COLUMNS_NOT_COMPLETE")

        # 첫 geometry의 4326 중심 주변 500m bbox를 만들어 실제 PostGIS 교차 건수 확인
        try:
            cur.execute(f"""
              SELECT
                ST_X(ST_Centroid(ST_Transform({geom_col},4326))),
                ST_Y(ST_Centroid(ST_Transform({geom_col},4326)))
              FROM drawing_group_objects
              WHERE revision_id=%s
                AND {geom_col} IS NOT NULL
                AND NOT ST_IsEmpty({geom_col})
                AND ST_SRID({geom_col})>0
              LIMIT 1
            """,(rid,))
            sample=cur.fetchone()
        except Exception as exc:
            conn.rollback()
            sample=None
            print("  SAMPLE_CENTER_ERROR=",exc)

        if sample and sample[0] is not None and sample[1] is not None:
            lon=float(sample[0]); lat=float(sample[1])
            latd=500.0/111320.0
            lngd=500.0/(111320.0*max(0.2,math.cos(math.radians(lat))))
            w,s,e,n=lon-lngd,lat-latd,lon+lngd,lat+latd
            print(f"  TEST_BBOX_500M={w:.7f},{s:.7f},{e:.7f},{n:.7f}")
            try:
                cur.execute(f"""
                  SELECT COUNT(*)
                  FROM drawing_group_objects
                  WHERE revision_id=%s
                    AND {geom_col} IS NOT NULL
                    AND ST_SRID({geom_col})>0
                    AND ST_Intersects(
                      ST_Transform({geom_col},4326),
                      ST_MakeEnvelope(%s,%s,%s,%s,4326)
                    )
                """,(rid,w,s,e,n))
                geom_hit=int(cur.fetchone()[0])
                print(f"  GEOMETRY_BBOX_HIT={geom_hit}")
            except Exception as exc:
                conn.rollback()
                print("  GEOMETRY_BBOX_ERROR=",exc)

            if bbox_cols:
                try:
                    cur.execute("""
                      SELECT COUNT(*)
                      FROM drawing_group_objects
                      WHERE revision_id=%s
                        AND max_lon >= %s AND min_lon <= %s
                        AND max_lat >= %s AND min_lat <= %s
                    """,(rid,w,e,s,n))
                    bbox_hit=int(cur.fetchone()[0])
                    print(f"  STORED_BBOX_HIT={bbox_hit}")
                    if 'geom_hit' in locals() and geom_hit>0 and bbox_hit==0:
                        print("  RESULT=BBOX_COLUMNS_NOT_MATCHING_GEOMETRY")
                except Exception as exc:
                    conn.rollback()
                    print("  STORED_BBOX_ERROR=",exc)

        if meta_count and int(meta_count)!=int(total):
            print(f"  RESULT=REVISION_COUNT_MISMATCH meta={meta_count} db={total}")

print()
print("[3/5] ASGI ONLINE OBJECT ROUTE")
try:
    import cmb_asgi
    found=[]
    for route in getattr(cmb_asgi.app,"routes",[]):
        path=str(getattr(route,"path",""))
        if "/online/" in path and path.endswith("/objects"):
            endpoint=getattr(route,"endpoint",None)
            methods=sorted(getattr(route,"methods",None) or [])
            found.append((path,methods,endpoint))
    if not found:
        print("ERROR ONLINE_OBJECT_ROUTE_NOT_FOUND")
    for path,methods,endpoint in found:
        print("ROUTE",path,methods,getattr(endpoint,"__name__",""))
        try:
            src=inspect.getsource(endpoint)
        except Exception as exc:
            print("  SOURCE_UNAVAILABLE",exc)
            continue
        flags={
          "USES_GRID_ID": "grid_id" in src or "grid_ids" in src,
          "USES_MINMAX_BBOX": all(x in src for x in ("min_lat","max_lat","min_lon","max_lon")),
          "USES_ST_INTERSECTS": "ST_Intersects" in src or "ST_MakeEnvelope" in src,
          "USES_GEOMETRY": "geometry" in src or "geom" in src,
          "USES_LAYERS_FILTER": "layers" in src,
        }
        print("  ROUTE_FLAGS=",flags)
        for i,line in enumerate(src.splitlines(),1):
            if any(k.lower() in line.lower() for k in (
                "bbox","grid","min_lat","max_lat","min_lon","max_lon",
                "intersect","envelope","geometry","layers","revision"
            )):
                print(f"  SRC {i:03}: {line[:220]}")
except Exception as exc:
    print("ASGI_INSPECTION_ERROR=",repr(exc))

print()
print("[4/5] CONCLUSION GUIDE")
print("A. RAW_EXTENT가 한국 위경도(대략 lon 124~132 / lat 33~39)가 아니고 SRID=4326이면 SRID 지정 오류 가능성")
print("B. WGS84_EXTENT는 정상인데 BBOX_COL_EXTENT가 비정상이면 min/max 좌표 backfill 오류")
print("C. GEOMETRY_BBOX_HIT>0, STORED_BBOX_HIT=0이면 서버가 min/max 컬럼 필터를 쓰는 경우 조회 누락 가능")
print("D. ROUTE_FLAGS.USES_GRID_ID=True이면 /objects 일반 bbox 경로에 GRID 의존 로직이 남아있는지 점검 필요")
print("E. DB geometry/bbox 모두 정상인데 Viewer가 0건이면 /layers bounds 또는 layers 필터 값을 점검해야 함")
print()
print("[5/5] DONE")
print("RESULT=CMB_COORDINATE_BBOX_PIPELINE_CHECK_DONE")
PY
