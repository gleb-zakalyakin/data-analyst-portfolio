from datetime import datetime
from airflow import DAG
from airflow.sensors.s3_key_sensor import S3KeySensor
from airflow.providers.yandex.operators.dataproc import DataprocCreatePysparkJobOperator
from airflow.hooks.base import BaseHook

DAG_ID = "taxi_data_analysis"

# Берём username из Airflow Connection
conn = BaseHook.get_connection("clickhouse_default")
username = conn.login

with DAG(
    dag_id=DAG_ID,
    schedule_interval="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
) as dag:

    # 1) Ждём появления входного файла в S3
    wait_for_input = S3KeySensor(
        task_id="wait_for_input_file",
        bucket_name="da-plus-dags",
        bucket_key="project_04/taxi_data.parquet",
        aws_conn_id="s3",
        poke_interval=300,
        timeout=3600,
    )

    # 2) Запускаем PySpark-задание на кластере Dataproc
    run_pyspark = DataprocCreatePysparkJobOperator(
        task_id="run_pyspark_job",
        cluster_id="c9q4134h5vi546h1e148",
        main_python_file_uri=f"s3a://da-plus-dags/{username}/jobs/spark_job.py",
    )

    # 3) Зависимости
    wait_for_input >> run_pyspark
