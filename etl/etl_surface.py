import os
import time
import json
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import psycopg2
import yaml


# ----------------------------
# Config
# ----------------------------
def load_config():
    """
    Load configuration from YAML and override db_params with env vars.
    Expects config/00_proj.yml relative to current working directory.
    """
    with open("config/00_proj.yml", "r") as f:
        raw_cfg = yaml.safe_load(f)

    dbp = raw_cfg.get("db_params", {})
    raw_cfg["db_params"] = {
        "dbname": os.getenv("POSTGRES_DB", dbp.get("dbname")),
        "user": os.getenv("POSTGRES_USER", dbp.get("user")),
        "host": os.getenv("POSTGRES_HOST", dbp.get("host")),
        "port": os.getenv("POSTGRES_PORT", dbp.get("port")),
        "password": os.getenv("POSTGRES_PASSWORD", dbp.get("password")),
    }
    return raw_cfg


# ----------------------------
# DB helpers
# ----------------------------
def create_highway_surface_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS novaims.tb_highway_surface (
            id SERIAL PRIMARY KEY,
            osm_id BIGINT UNIQUE NOT NULL,
            fclass VARCHAR,
            surface VARCHAR
        );
        """
    )


def get_overall_bbox(cur, grid_table_name):
    """
    Returns south, west, north, east
    """
    cur.execute(
        f'''
        SELECT MIN("left"), MAX("right"), MAX(top), MIN(bottom)
        FROM {grid_table_name}
        '''
    )
    left, right, top, bottom = cur.fetchone()
    return bottom, left, top, right


# ----------------------------
# Overpass helpers
# ----------------------------
def overpass_session():
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({"User-Agent": "osm-surface-etl/1.0 (contact: you@example.com)"})
    return s


SESSION = overpass_session()


def call_overpass(overpass_url: str, query: str, timeout: int = 300) -> dict:
    resp = SESSION.post(overpass_url, data={"data": query}, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Overpass status {resp.status_code}. Body: {resp.text[:200]}"
        )
    ctype = resp.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        raise RuntimeError(
            f"Non JSON response. Content-Type={ctype}. Body: {resp.text[:200]}"
        )
    return resp.json()


# ----------------------------
# Stages
# ----------------------------
def stage_extract(cfg, raw_out_path="surface_raw.json"):
    """
    One Overpass query over the full bbox. Save raw JSON to file.
    """
    print("Stage extract started")
    dbp = cfg["db_params"]

    conn = psycopg2.connect(
        dbname=dbp["dbname"],
        user=dbp["user"],
        host=dbp["host"],
        password=dbp["password"],
        port=dbp["port"],
    )
    cur = conn.cursor()
    south, west, north, east = get_overall_bbox(cur, cfg["grid_table_name"])
    cur.close()
    conn.close()

    print(f"Using bbox south={south}, west={west}, north={north}, east={east}")

    query = f"""
[out:json][timeout:300];
(
  way["highway"]["surface"]({south},{west},{north},{east});
);
out tags;
"""

    try:
        data = call_overpass(cfg["overpass_api_url"], query, timeout=300)
    except Exception as e:
        print(f"Overpass error on full query: {e}. Retry soon")
        time.sleep(10)
        data = call_overpass(cfg["overpass_api_url"], query, timeout=320)

    with open(raw_out_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    print(f"Stage extract completed. Raw saved to {raw_out_path}")
    return raw_out_path


def stage_transform(cfg, raw_in_path="surface_raw.json", cleaned_out_path="surface_clean.json"):
    """
    Read raw JSON, keep only way elements with allowed highway classes.
    Save compact cleaned list for faster loading.
    """
    print("Stage transform started")

    desired_set = set(cfg.get("desired_categories") or [])

    with open(raw_in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {}) or {}
        fclass = tags.get("highway")
        surface = tags.get("surface")
        if desired_set and fclass not in desired_set:
            continue
        cleaned.append(
            {"osm_id": el.get("id"), "fclass": fclass, "surface": surface}
        )

    with open(cleaned_out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f)

    print(
        f"Stage transform completed. Kept {len(cleaned)} rows. Cleaned saved to {cleaned_out_path}"
    )
    return cleaned_out_path


def stage_load(cfg, cleaned_in_path="surface_clean.json"):
    """
    Upsert cleaned records into novaims.tb_highway_surface.
    """
    print("Stage load started")

    with open(cleaned_in_path, "r", encoding="utf-8") as f:
        rows = json.load(f)

    dbp = cfg["db_params"]
    conn = psycopg2.connect(
        dbname=dbp["dbname"],
        user=dbp["user"],
        host=dbp["host"],
        password=dbp["password"],
        port=dbp["port"],
    )
    cur = conn.cursor()
    create_highway_surface_table(cur)

    upserts = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO novaims.tb_highway_surface (osm_id, fclass, surface)
            VALUES (%s, %s, %s)
            ON CONFLICT (osm_id) DO UPDATE
            SET fclass = EXCLUDED.fclass,
                surface = EXCLUDED.surface;
            """,
            (r["osm_id"], r["fclass"], r["surface"]),
        )
        upserts += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"Stage load completed. Upserted {upserts} rows")


# ----------------------------
# Entrypoint
# ----------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["extract", "transform", "load", "all"],
        default="all",
        help="Which stage to run"
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep intermediate files instead of deleting them"
    )
    args = parser.parse_args()

    print("Starting surface ETL")
    cfg = load_config()

    raw_path = "surface_raw.json"
    clean_path = "surface_clean.json"

    try:
        if args.stage in ("extract", "all"):
            raw_path = stage_extract(cfg, raw_out_path=raw_path)

        if args.stage in ("transform", "all"):
            if not os.path.exists(raw_path):
                raw_path = stage_extract(cfg, raw_out_path=raw_path)
            clean_path = stage_transform(cfg, raw_in_path=raw_path, cleaned_out_path=clean_path)

        if args.stage in ("load", "all"):
            if not os.path.exists(clean_path):
                if not os.path.exists(raw_path):
                    raw_path = stage_extract(cfg, raw_out_path=raw_path)
                clean_path = stage_transform(cfg, raw_in_path=raw_path, cleaned_out_path=clean_path)
            stage_load(cfg, cleaned_in_path=clean_path)

        print("Surface ETL finished")

    except Exception as e:
        print(f"Surface ETL failed: {e}")
        raise
    finally:
        if not args.keep:
            if args.stage in ("all", "load"):
                for p in [raw_path, clean_path]:
                    if os.path.exists(p):
                        os.remove(p)
                        print(f"Removed {p}")
        print("ETL process complete")
