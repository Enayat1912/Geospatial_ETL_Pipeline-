import os
import subprocess
import urllib.request
import argparse
import yaml


def load_config():
    """
    Load YAML configuration and resolve database details from environment variables.
    """
    with open("config/00_proj.yml", "r") as config_file:
        raw_cfg = yaml.safe_load(config_file)

    dbp = raw_cfg.get("db_params", {})
    resolved_dbp = {
        "dbname": os.getenv("POSTGRES_DB", dbp.get("dbname")),
        "user": os.getenv("POSTGRES_USER", dbp.get("user")),
        "host": os.getenv("POSTGRES_HOST", dbp.get("host")),
        "port": os.getenv("POSTGRES_PORT", dbp.get("port")),
        "password": os.getenv("POSTGRES_PASSWORD", dbp.get("password")),
    }

    raw_cfg["db_params"] = resolved_dbp
    return raw_cfg


def download_osm_pbf(url, out_path="temporary_data.osm.pbf"):
    """
    Extract step: download the OSM pbf file for the region of interest.
    """
    print(f"Downloading OSM PBF file from: {url}")
    urllib.request.urlretrieve(url, out_path)
    print(f"Download complete: {out_path}")
    return out_path


def run_osmconvert(bounding_box, osmconvert_output, in_path="temporary_data.osm.pbf"):
    """
    Transform step: clip and simplify the OSM extract within the bounding box.
    """
    print("Running osmconvert command")
    cmd = (
        f"osmconvert {in_path} "
        f"-b={bounding_box} "
        f"--complete-ways "
        f"--drop-author --drop-version "
        f"-o={osmconvert_output}"
    )
    subprocess.run(cmd, shell=True, check=True)
    print(f"osmconvert finished. Output: {osmconvert_output}")
    return osmconvert_output


def run_osm2pgrouting(osmconvert_output, osm2pgrouting_config, db_params):
    """
    Load step: import clipped OSM data into PostGIS with osm2pgrouting.
    """
    print("Running osm2pgrouting command")
    cmd = (
        f"osm2pgrouting --chunk 100000 -f {osmconvert_output} "
        f"--dbname {db_params['dbname']} "
        f"--username {db_params['user']} "
        f"--host {db_params['host']} "
        f"--port {db_params['port']} "
        f"-W {db_params['password']} "
        f"-c {osm2pgrouting_config} "
        f"--schema novaims"
    )
    subprocess.run(cmd, shell=True, check=True)
    print("osm2pgrouting import completed")


def clean_up(paths):
    """
    Remove temporary files if they exist.
    """
    print("Cleaning up temporary files")
    for p in paths:
        if p and os.path.exists(p):
            os.remove(p)
            print(f"Removed {p}")
    print("Cleanup complete")


def step_extract(cfg):
    return download_osm_pbf(cfg["osm_pbf_url"], "temporary_data.osm.pbf")


def step_transform(cfg, in_path="temporary_data.osm.pbf"):
    return run_osmconvert(cfg["bounding_box"], cfg["osmconvert_output"], in_path)


def step_load(cfg, osm_path):
    run_osm2pgrouting(osm_path, cfg["osm2pgrouting_config"], cfg["db_params"])


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

    print("Starting geometry ETL")
    cfg = load_config()

    tmp_pbf = "temporary_data.osm.pbf"
    clipped = cfg["osmconvert_output"]

    try:
        if args.stage in ("extract", "all"):
            tmp_pbf = step_extract(cfg)

        if args.stage in ("transform", "all"):
            # ensure the extract exists if someone runs transform alone
            if not os.path.exists(tmp_pbf):
                tmp_pbf = step_extract(cfg)
            clipped = step_transform(cfg, tmp_pbf)

        if args.stage in ("load", "all"):
            # ensure we have a clipped file if someone runs load alone
            if not os.path.exists(clipped):
                if not os.path.exists(tmp_pbf):
                    tmp_pbf = step_extract(cfg)
                clipped = step_transform(cfg, tmp_pbf)
            step_load(cfg, clipped)

        print("OSM geometry ETL finished")

    except subprocess.CalledProcessError as e:
        print(f"Error during ETL subprocess execution: {e}")
        raise
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise
    finally:
        if not args.keep:
            # If you just ran load or all, it is safe to clean up
            if args.stage in ("load", "all"):
                clean_up([tmp_pbf, clipped])
        print("ETL process complete")
