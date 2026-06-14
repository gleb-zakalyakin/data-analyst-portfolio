import os
from pyspark.sql import SparkSession
import pyspark.sql.functions as F

# Создаём Spark-сессию
spark = (
    SparkSession.builder.appName("TaxiPaymentSummaryJob")
    .config("fs.s3a.endpoint", "storage.yandexcloud.net")
    .config("spark.dynamicAllocation.enabled", "false")
    .config("spark.executor.instances", "1")
    .config("spark.executor.cores", "1")
    .config("spark.executor.memory", "1g")
    .config("spark.driver.memory", "1g")
    .getOrCreate()
)

# Параметры подключения из переменных окружения
jdbcPort = 8443
jdbcHostname = os.environ.get("CH_HOST")
username = os.environ.get("CH_USERNAME")
password = os.environ.get("CH_PASSWORD")
jdbcDatabase = f"playground_{username}"
jdbcUrl = f"jdbc:clickhouse://{jdbcHostname}:{jdbcPort}/{jdbcDatabase}?ssl=true"

# Читаем данные из S3
df = spark.read.parquet("s3a://da-plus-dags/project_04/taxi_data.parquet")

# Агрегация по способу оплаты
result_df = df.groupBy("payment_type").agg(
    F.count("*").alias("trip_count"),
    F.avg("fare").alias("avg_fare"),
    F.avg("tips").alias("avg_tips"),
    F.sum("trip_total").alias("sum_trip_total")
)

# Записываем результат в ClickHouse
result_df.write.format("jdbc") \
    .option("url", jdbcUrl) \
    .option("user", username) \
    .option("password", password) \
    .option("dbtable", "taxi_payment_summary") \
    .mode("overwrite") \
    .save()
