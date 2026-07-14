import os

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_replace


def process_data_with_spark(
    file: str, target_column: str, regex_pattern: str, replacement_value: str
):
    """
    Reads a CSV, applies a regex replacement, and saves the distributed partitions.
    """
    # 1. Initialize Spark Session
    spark = (
        SparkSession.builder.appName("RegexProcessor")
        .master("spark://spark:7077")
        .config("spark.executor.memory", "512m")
        .config("spark.cores.max", "1")
        .getOrCreate()
    )

    print(f"--- Loading Data from {file} ---")
    df = spark.read.csv(
        file, header=True, inferSchema=True, multiLine=True, escape='"', quote='"'
    )

    # 2. Apply the Regex Transformation
    print(f"--- Applying Regex to column: {target_column} ---")
    df_transformed = df.withColumn(
        target_column,
        regexp_replace(col(target_column), regex_pattern, replacement_value),
    )

    # 3. Write the distributed partitions safely to disk
    job_directory = os.path.dirname(file)
    output_path = os.path.join(job_directory, "processed_data")

    print(f"--- Saving distributed partitions to {output_path} ---")
    df_transformed.write.parquet(output_path, mode="overwrite")

    # 4. Grab a small preview for the frontend
    print("--- Generating 50-row preview for the UI ---")
    preview_df = df_transformed.limit(50)
    preview_results = [row.asDict() for row in preview_df.collect()]


    spark.stop()

    return preview_results
