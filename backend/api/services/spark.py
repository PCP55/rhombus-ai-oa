import os
from typing import Callable, Optional

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, regexp_replace, spark_partition_id

# Number of row-chunks to split the write into so we can report incremental
# progress. Higher = more granular progress updates, but more Spark actions.
NUM_PROGRESS_CHUNKS = 10


def process_data_with_spark(
    file: str,
    target_column: str,
    regex_pattern: str,
    replacement_value: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    """
    Reads a CSV, applies a regex replacement, and saves the distributed partitions.

    If `progress_callback` is provided, it is called as `progress_callback(rows_processed, total_rows)`
    after each chunk of rows has been written, so callers (e.g. the Celery task) can
    surface real-time "percentage of rows processed" progress.
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

    # 2. Count total rows up-front so progress can be reported as a percentage
    total_rows = df.count()
    if progress_callback:
        progress_callback(0, total_rows)

    # 3. Apply the Regex Transformation
    print(f"--- Applying Regex to column: {target_column} ---")
    df_transformed = df.withColumn(
        target_column,
        regexp_replace(col(target_column), regex_pattern, replacement_value),
    )

    # 4. Write the distributed partitions safely to disk, one chunk at a time,
    #    reporting progress after each chunk so long-running jobs aren't a black box.
    job_directory = os.path.dirname(file)
    output_path = os.path.join(job_directory, "processed_data")

    num_chunks = min(NUM_PROGRESS_CHUNKS, max(1, total_rows)) if total_rows else 1
    df_transformed = df_transformed.repartition(num_chunks)

    print(f"--- Saving distributed partitions to {output_path} in {num_chunks} chunk(s) ---")
    rows_processed = 0
    for chunk_id in range(num_chunks):
        chunk_df = df_transformed.filter(spark_partition_id() == chunk_id)
        chunk_rows = chunk_df.count()

        chunk_df.write.parquet(
            output_path, mode="overwrite" if chunk_id == 0 else "append"
        )

        rows_processed += chunk_rows
        if progress_callback:
            progress_callback(rows_processed, total_rows)

    # 5. Grab a small preview for the frontend
    print("--- Generating 50-row preview for the UI ---")
    preview_df = df_transformed.limit(50)
    preview_results = [row.asDict() for row in preview_df.collect()]

    spark.stop()

    return preview_results
