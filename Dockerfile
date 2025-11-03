FROM python:3.10-slim

# install system dependencies
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    gcc \
    g++ \
    curl \
    osm2pgrouting \
    osmctools \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# set workdir
WORKDIR /app

# copy Python deps first to leverage Docker layer cache
COPY requirements.txt /app/requirements.txt

# GDAL build env hints (needed for some wheels)
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal
ENV GDAL_CONFIG=/usr/bin/gdal-config

# install Python deps
RUN pip install --no-cache-dir -r requirements.txt

# copy project code into the image
# we'll copy config and etl code, plus anything else that's needed at runtime
COPY etl /app/etl
COPY config /app/config
COPY db /app/db

# by default, the container won't auto-run anything
# docker-compose overrides this with its own command
CMD ["python", "etl/etl_geom.py"]
