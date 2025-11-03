#!/usr/bin/env bash
set -e

echo "Initializing Airflow metadata DB..."
airflow db init

echo "Creating admin user if not exists..."
airflow users create \
  --username "${USERNAME}" \
  --firstname "${FIRSTNAME}" \
  --lastname "${LASTNAME}" \
  --role Admin \
  --email "${EMAIL}" \
  --password "${PASSWORD}" || true

echo "Starting webserver on 0.0.0.0:8080..."
airflow webserver --port 8080 &

echo "Starting scheduler in foreground..."
exec airflow scheduler
