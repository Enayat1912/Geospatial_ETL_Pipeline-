#!/usr/bin/env python3
"""
Surface ETL

One-shot or staged ETL that:
1) Extracts highway features with a 'surface' tag from Overpass for a region
2) Transforms to a compact JSON list
3) Loads into PostGIS table novaims.tb_highway_surface with upserts

Usage examples
  python etl/etl_surface.py --stage all
  python etl/etl_surface.py --stage extract --raw surface_raw.json
  python etl/etl_surface.py --stage load --clean surface_clean.json
  python etl/etl_surface.py --stage all --keep
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Dict, List

import psycopg2
import requests
import yaml
from psycopg2.extensions import connection as PGConnection
from psycopg2.extensions import cursor as PGCursor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("surface_etl")


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------
def load_config() -> Dict:
    """
    Load configuration from YAML and override db_params with environment variables.
    Expects config/00_proj.yml relative to the working directory.
    """
    with open("config/00_proj.yml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    dbp = cfg.get("db_params", {})
    cfg["db_params"] = {
        "dbname": os.getenv("POSTGRES_DB", dbp.get("dbname")),
        "user": os.getenv("POSTGRES_USER", dbp.get("user")),
        "host": os.getenv("POSTGRES_HOST", dbp.get("host")),
        "port": os.getenv("POSTGRES_PORT", dbp.get("port")),
        "password": os.getenv("POSTGRES_PASSWORD", dbp.get("password")),
    }
    return cfg


# ---------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------
def pg_connect(dbp: Dict) -> PGConnection:
    return psycopg2.connect(
        dbname=dbp["dbname"],
        user=dbp["user"],
        host=dbp["host"],
        password=dbp["password"],
        port=dbp["port"],
    )


def create_highway_surface_table(cur: PGCursor) -> None:
    """
    Create the destination table if it does not already exist.
    Safe to call repeatedly.
    """
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS novaims.tb_highway_surface (
            id      SERIAL PRIMARY KEY,
            osm_id  BIGINT UNIQUE NOT NULL,
            fclass  VARCHAR,
            surface VARCHAR
        );
        """
    )


def get_overall_bbox(cur: PGCursor, grid_table_name: str) -> tuple[float, float, float, float]:
    """
    Compute one bounding box that covers all grid cells.
    Returns south, west, north, east which Overpass expects.
    """
    cur.execute(
        f"""
        SELECT MIN("left"), MAX("right"), MAX(top), MIN(bottom)
        FROM {grid_table_name}
        """
    )
    left, right, top, bottom = cur.fetchone()
    return bottom, left, top, right


# ---------------------------------------------------------------------
# Overpass helpers
# ---------------------------------------------------------------------
def overpass_session() -> requests.Session:
    """
    Build a requests session with retries and a friendly User Agent.
    """
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


def call_overpass(overpass_url: str, query: str, timeout: int = 300) -> Dict:
    """
    Call Overpass with POST and return JSON or raise a clear error.
    """
    resp = SESSION.post(overpass_url, data={"data": query}, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Overpass status {resp.status_code}. Body: {resp.text[:200]}")
    ctype = resp.headers.get("Content-Type", "")
    if "json" not in ctype.lower():
        raise RuntimeError(f"Non JSON response. Content-Type={ctype}. Body: {resp.text[:200]}")
    return resp.json()


# ---------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------
def stage_extract(cfg: Dict, raw_out_path: str) -> str:
    """
    One Overpass query over the full bbox. Save raw JSON to file.
    """
    log.info("Stage extract started")
    dbp = cfg["db_params"]

    with pg_connect(dbp) as conn:
        with conn.cursor() as cur:
            south, west, north, east = get_overall_bbox(cur, cfg["grid_table_name"])

    log.info("Using bbox south=%s, west=%s, north=%s, east=%s", south, west, north, east)

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
        log.warning("Overpass error on full query: %s. Retrying shortly", e)
        time.sleep(10)
        data = call_overpass(cfg["overpass_api_url"], query, timeout=320)

    with open(raw_out_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    log.info("Stage extract completed. Raw saved to %s", raw_out_path)
    return raw_out_path


def stage_transform(cfg: Dict, raw_in_path: str, cleaned_out_path: str) -> str:
    """
    Read raw JSON, keep only way elements with allowed highway classes.
    Save compact cleaned list for faster loading.
    """
    log.info("Stage transform started")
    desired_set = set(cfg.get("desired_categories") or [])

    with open(raw_in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cleaned: List[Dict] = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {}) or {}
        fclass = tags.get("highway")
        surface = tags.get("surface")
        if desired_set and fclass not in desired_set:
            continue
        cleaned.append({"osm_id": el.get("id"), "fclass": fclass, "surface": surface})

    with open(cleaned_out_path, "w", encoding="utf-8") as f:
        json.dump(cleaned, f)

    log.info("Stage transform completed. Kept %d rows. Saved to %s", len(cleaned), cleaned_out_path)
    return cleaned_out_path


def stage_load(cfg: Dict, cleaned_in_path: str) -> None:
    """
    Upsert cleaned records into novaims.tb_highway_surface.
    """
    log.info("Stage load started")

    with open(cleaned_in_path, "r", encoding="utf-8") as f:
        rows: List[Dict] = json.load(f)

    dbp = cfg["db_params"]
    with pg_connect(dbp) as conn:
        with conn.cursor() as cur:
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

    log.info("Stage load completed. Upserted %d rows", upserts)


# ---------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Surface ETL pipeline")
    p.add_argument(
        "--stage",
        choices=["extract", "transform", "load", "all"],
        default="all",
        help="Which stage to run",
    )
    p.add_argument(
        "--raw",
        default="surface_raw.json",
        help="Path for raw Overpass JSON file",
    )
    p.add_argument(
        "--clean",
        default="surface_clean.json",
        help="Path for cleaned JSON file",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Keep intermediate files instead of deleting them",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config()

    log.info("Starting surface ETL")

    raw_path = args.raw
    clean_path = args.clean

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

        log.info("Surface ETL finished successfully")

    except Exception as e:
        log.exception("Surface ETL failed: %s", e)
        raise
    finally:
        if not args.keep and args.stage in ("all", "load"):
            for p in [raw_path, clean_path]:
                try:
                    if os.path.exists(p):
                        os.remove(p)
                        log.info("Removed %s", p)
                except Exception as rm_err:
                    log.warning("Could not remove %s: %s", p, rm_err)
        log.info("ETL process complete")


if __name__ == "__main__":
    main()

