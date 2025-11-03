
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}

with DAG(
    dag_id="etl_geom_dag",
    default_args=default_args,
    start_date=datetime(2025, 11, 1),
    schedule=None,
    catchup=False,
    tags=["etl", "geom"],
) as dag:

    extract = BashOperator(
        task_id="extract_geom",
        bash_command="cd /app && python etl/etl_geom.py --stage extract",
    )

    transform = BashOperator(
        task_id="transform_geom",
        bash_command="cd /app && python etl/etl_geom.py --stage transform",
    )

    load = BashOperator(
        task_id="load_geom",
        bash_command="cd /app && python etl/etl_geom.py --stage load",
    )

    extract >> transform >> load
