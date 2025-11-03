from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "airflow",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
}


with DAG(
    dag_id="etl_surface_dag",
    default_args=default_args,
    start_date=datetime(2025, 11, 1),
    schedule=None,
    catchup=False,
    tags=["etl", "surface"],
) as dag:

    extract = BashOperator(
        task_id="extract_surface",
        bash_command="cd /app && python etl/etl_surface.py --stage extract",
    )

    transform = BashOperator(
        task_id="transform_surface",
        bash_command="cd /app && python etl/etl_surface.py --stage transform",
    )

    load = BashOperator(
        task_id="load_surface",
        bash_command="cd /app && python etl/etl_surface.py --stage load",
    )

    extract >> transform >> load
