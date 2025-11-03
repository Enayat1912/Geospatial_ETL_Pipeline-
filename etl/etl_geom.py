#!/usr/bin/env python3
"""
Geometry ETL

Stages
  1) extract   -> download OSM PBF for the region
  2) transform -> clip with osmconvert using a bounding box
  3) load      -> import into PostGIS with osm2pgrouting

Examples
  python etl/etl_geom.py --stage all
  python etl/etl_geom.py --stage extract --pbf temporary_data.osm.pbf
  python etl/etl_geom.py --stage load --clipped region_clip.osm.pbf
  python etl/etl_geom.py --stage all --keep
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import urllib.request
from typing import Dict

import yaml


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("geom_etl")


# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
def load_config() -> Dict:
    """
    Load YAML config and resolve database details from environment variables.
    Expects config/00_proj.yml in the project.
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
# Steps
# ---------------------------------------------------------------------
def download_osm_pbf(url: str, out_path: str) -> str:
    """
    Extract step. Download the PBF extract for the region of interest.
    """
    log.info("Downloading OSM PBF from %s", url)
    urllib.request.urlretrieve(url, out_path)
    log.info("Download complete: %s", out_path)
    return out_path


def run_osmconvert(bounding_box: str, out_path: str, in_path: str) -> str:
    """
    Transform step. Clip PBF to a bounding box and keep complete ways.
    """
    log.info("Running osmconvert to clip %s -> %s", in_path, out_path)
    # Use exec form for safety and clearer errors
    cmd = [
        "osmconvert",
        in_path,
        f"-b={bounding_box}",
        "--complete-ways",
        "--drop-author",
        "--drop-version",
        f"-o={out_path}",
    ]
    subprocess.run(cmd, check=True)
    log.info("osmconvert finished: %s", out_path)
    return out_path


def run_osm2pgrouting(clipped_path: str, osm2pg_cfg: str, db: Dict) -> None:
    """
    Load step. Import the clipped network into PostGIS using osm2pgrouting.
    """
    log.info("Running osm2pgrouting to load %s", clipped_path)
    cmd = [
        "osm2pgrouting",
        "--chunk", "100000",
        "-f", clipped_path,
        "--dbname", db["dbname"],
        "--username", db["user"],
        "--host", db["host"],
        "--port", str(db["port"]),
        "-W", db["password"],
        "-c", osm2pg_cfg,
        "--schema", "novaims",
    ]
    subprocess.run(cmd, check=True)
    log.info("osm2pgrouting import completed")


def clean_up(paths: list[str]) -> None:
    """
    Remove temporary files if they exist.
    """
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
                log.info("Removed %s", p)
        except Exception as e:
            log.warning("Could not remove %s: %s", p, e)


# Convenience wrappers used by CLI
def step_extract(cfg: Dict, out_path: str) -> str:
    return download_osm_pbf(cfg["osm_pbf_url"], out_path)


def step_transform(cfg: Dict, in_path: str, out_path: str) -> str:
    return run_osmconvert(cfg["bounding_box"], out_path, in_path)


def step_load(cfg: Dict, clipped_path: str) -> None:
    run_osm2pgrouting(clipped_path, cfg["osm2pgrouting_config"], cfg["db_params"])


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Geometry ETL pipeline")
    p.add_argument(
        "--stage",
        choices=["extract", "transform", "load", "all"],
        default="all",
        help="Which stage to run",
    )
    p.add_argument(
        "--pbf",
        default="temporary_data.osm.pbf",
        help="Path to the raw downloaded PBF",
    )
    p.add_argument(
        "--clipped",
        default=None,
        help="Path for the clipped PBF output. Defaults to config.osmconvert_output",
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

    raw_pbf = args.pbf
    clipped_pbf = args.clipped or cfg["osmconvert_output"]

    log.info("Starting geometry ETL")

    try:
        if args.stage in ("extract", "all"):
            raw_pbf = step_extract(cfg, out_path=raw_pbf)

        if args.stage in ("transform", "all"):
            if not os.path.exists(raw_pbf):
                raw_pbf = step_extract(cfg, out_path=raw_pbf)
            clipped_pbf = step_transform(cfg, in_path=raw_pbf, out_path=clipped_pbf)

        if args.stage in ("load", "all"):
            if not os.path.exists(clipped_pbf):
                if not os.path.exists(raw_pbf):
                    raw_pbf = step_extract(cfg, out_path=raw_pbf)
                clipped_pbf = step_transform(cfg, in_path=raw_pbf, out_path=clipped_pbf)
            step_load(cfg, clipped_path=clipped_pbf)

        log.info("OSM geometry ETL finished successfully")

    except subprocess.CalledProcessError as e:
        log.exception("Subprocess failed: %s", e)
        raise
    except Exception as e:
        log.exception("Unexpected error: %s", e)
        raise
    finally:
        if not args.keep and args.stage in ("load", "all"):
            clean_up([raw_pbf, clipped_pbf])
        log.info("ETL process complete")


if __name__ == "__main__":
    main()
