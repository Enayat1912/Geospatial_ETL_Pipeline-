# OSM_ETL: Automated Geospatial ETL Pipeline with Airflow and PostGIS

 ## Introduction

OSM_ETL is a fully containerized geospatial data pipeline designed to automate the extraction, transformation, and loading (ETL) of OpenStreetMap (OSM) road network data into a PostGIS database, orchestrated by Apache Airflow. The system integrates open-source geospatial tools such as osmconvert, osm2pgrouting, and the Overpass API to efficiently process and structure spatial datasets for routing analysis, surface classification, and infrastructure mapping. By encapsulating all components, Airflow, PostGIS, and ETL scripts , in Docker containers, the project ensures portability, reproducibility, and ease of deployment across different environments. This approach simplifies complex geospatial workflows and supports scalable, automated data management for research and urban analytics.

## Data Methodology 
The project uses two main data sources: OSM geometry and OSM attributes.The OSM geometry data, available from [GeoFabrik](https://www.geofabrik.de/), provides detailed information about road networks, including road segments, intersections, and coordinates.The OSM attributes, retrieved through the [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API), add extra details such as road types, surface materials, and other related features. All extracted data is stored and managed in a PostgreSQL/PostGIS database. The data follows an ETL (Extract, Transform, Load) process: it is first downloaded in PBF format, then filtered using osmconvert, and finally imported into the database using osm2pgrouting.

## Project Structure 
```bash
OSM_ETL/
├── airflow/                        # Airflow configuration and DAG definitions
│   ├── dags/                       # Workflow scripts controlling ETL execution
│   │   ├── etl_geom_dag.py         # DAG for geometry extraction and import
│   │   └── etl_surface_dag.py      # DAG for surface attribute extraction
│   └── entrypoint.sh               # Airflow startup and initialization script
│
├── config/                         # Configuration files for ETL parameters
│   ├── 00_proj.yml                 # YAML file defining project and database settings
│   └── mapconfig_for_cars.xml      # Configuration for osm2pgrouting import rules
│
├── db/                             # Database initialization resources
│   └── create_tables.sql           # SQL script creating PostGIS schemas and tables
│
├── etl/                            # Core Python ETL scripts
│   ├── etl_geom.py                 # Handles geometry extraction, conversion, and loading
│   └── etl_surface.py              # Fetches and loads surface attributes via Overpass API
│
├── figures/                        # Folder for images, diagrams, and visual assets
│
├── .env.example                    # Example environment file (copy and rename to .env)
├── docker-compose.yml              # Defines and orchestrates Docker containers
├── Dockerfile.airflow              # Dockerfile for building the Airflow service
├── Dockerfile                      # Base Docker image configuration
├── requirements.txt                # Python dependencies list
└── README.md                       # Documentation and usage instructions
```
## Setup and Installation

1. Make sure the following are installed on your system:

[Docker Desktop](https://www.docker.com/products/docker-desktop/)

Check installation:
```bash
docker --version
```

2. Configure Environment Variables

Create .env and fill in your credentials such as database and airflow UI connections 

3. Build and Start Containers

Run the entire system with:
```bash
docker compose up --build
```

This will:

Initialize the PostGIS database and create tables from /db/create_tables.sql

Build and start the Airflow web server and scheduler

Automatically create the admin Airflow user defined in .env

![Project Architecture](figures/pic4.png)

5️. Access the Airflow Web Interface

Once containers are running, open:
👉 http://localhost:8080

Login using:

Username: your user name   
Password: your password

🧪 Checking if Everything Works Properly

Once Airflow is running:

In the Airflow UI, go to the DAGs tab.

You should see:

## etl_geom_dag

## etl_surface_dag

Trigger each DAG manually (click the ► toggle).

Watch the tasks (extract, transform, load) run under Graph View.

If successful, you’ll see green boxes (success) and logs under Task Instance Logs.
![Project Architecture](figures/pic5.png)
![Project Architecture](figures/pic6.png)

 After Inspdags completed successfullyi , inspect the Database

Open the PostGIS shell:
```bash
docker exec -it etl_postgis psql -U postgres -d gisdb
```

Check the list of tables created in this schema:
```bash
\dt novaims.*;
```
![Project Architecture](figures/pic3.png)


And inspect data:

1. count number of rows in the table
```bash
SELECT COUNT(*) FROM novaims.tb_highway_surface;
```
2. Display 10 rows of the table
```bash
SELECT * FROM novaims.tb_highway_surface LIMIT 10;
```
![Project Architecture](figures/pic2.png)

3. Run aggregation 
```bash
 SELECT surface, COUNT(*) AS total
FROM novaims.tb_highway_surface
GROUP BY surface
ORDER BY total DESC
LIMIT 10;
```
![Project Architecture](figures/pic1.png)

📚 Credits

Developed by Enayat Meskinyaar
Master’s in Geospatial Technologies, Nova University of Lisbon & University of Münster
Supervising the integration of AI-ready ETL pipelines for spatial data automation.
