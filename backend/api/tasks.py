import logging

import polars as pl
from celery import shared_task
from django.core.cache import cache

from .models import ProcessingJob
from .services.llm import generate_regex
from .services.read_columns import read_columns
from .services.spark import process_data_with_spark

logger = logging.getLogger(__name__)

# SYSTEM RESILIENCE: We distinguish between "transient" errors (like a network blip)
# and "permanent" errors (like a missing file). We don't want Celery to waste CPU
# retrying a job that will definitively fail every time.
PERMANENT_ERRORS = (ValueError, FileNotFoundError, ProcessingJob.DoesNotExist)

MAX_TASK_RETRIES = 3


def _fail_job(job_id, message: str) -> None:
    """Helper function to cleanly mark a job as failed in the SQLite database."""
    try:
        job = ProcessingJob.objects.get(id=job_id)
        job.status = "FAILED"
        job.error_message = message
        job.save(update_fields=["status", "error_message"])
    except ProcessingJob.DoesNotExist:
        logger.error("Cannot mark job %s as failed — job not found", job_id)


def _retry_or_fail(task, job_id, exc: Exception) -> None:
    """
    FAULT TOLERANCE: Implements Exponential Backoff.
    If the worker hits a random error (like Redis temporarily dropping), it will
    wait 30s, then 60s, then 120s before giving up.
    """
    if isinstance(exc, PERMANENT_ERRORS):
        _fail_job(job_id, str(exc))
        return

    logger.warning(
        "Worker Job %s transient error (attempt %s/%s): %s",
        job_id,
        task.request.retries + 1,
        MAX_TASK_RETRIES,
        exc,
    )
    try:
        # Exponential backoff formula: 30 * (2 ^ retry_count)
        countdown = 30 * (2 ** task.request.retries)
        raise task.retry(exc=exc, countdown=countdown, max_retries=MAX_TASK_RETRIES)
    except task.MaxRetriesExceededError:
        _fail_job(job_id, str(exc))


@shared_task(bind=True)
def read_columns_task(self, job_id):
    """
    Step 1 Background Task:
    By pushing this to Celery, we ensure that if a user uploads a massive Excel file,
    the Django web server doesn't freeze while trying to read the headers.
    """
    try:
        job = ProcessingJob.objects.get(id=job_id)
        columns = read_columns(job.file.path)
        if not columns:
            _fail_job(job_id, "No columns were found in the uploaded file.")
            return

        job.columns = columns
        # update_fields is a Django optimization: it only writes the 'columns'
        # field to SQLite instead of rewriting the entire row.
        job.save(update_fields=["columns"])
        logger.info("Worker Job %s: discovered %d columns", job_id, len(columns))

    except Exception as exc:
        logger.exception("Worker Job %s: column discovery failed", job_id)
        _retry_or_fail(self, job_id, exc)


@shared_task(bind=True)
def process_file_task(self, job_id):
    """
    Step 2 Background Task (The Main Engine):
    Orchestrates the LLM, the file format conversion, and the PySpark job.
    """
    try:
        job = ProcessingJob.objects.get(id=job_id)
        job.status = "RUNNING"
        job.progress = 10
        job.save() # Updates SQLite (Business State)

        logger.info("Worker Job %s: Translating prompt to regex...", job_id)

        # Updates Redis (Worker State) so the frontend gets detailed text updates
        self.update_state(
            state="RUNNING",
            meta={"current": 10, "total": 50, "status": "Extract Regex"},
        )

        # REDIS CACHING (Logical DB 1):
        # We normalize the prompt (strip/lower) to maximize cache hits.
        cache_key = f"regex_prompt_{job.prompt.strip().lower()}"
        regex_pattern = cache.get(cache_key)

        if not regex_pattern:
            logger.info("Cache miss: Calling LLM...")
            regex_pattern = generate_regex(prompt=job.prompt)
            # Save to Redis for 24 hours (86400 seconds)
            cache.set(cache_key, regex_pattern, timeout=86400)
        else:
            logger.info("Cache hit: Pulled regex from Redis!")

        job.progress = 30
        job.save()

        logger.info(
            "Worker Job %s: Running Spark with pattern '%s'", job_id, regex_pattern
        )
        self.update_state(
            state="RUNNING",
            meta={"current": 50, "total": 100, "status": "Running Spark"},
        )

        # We map Spark's internal progress (0-100%) to our overall job progress (50-95%)
        SPARK_PROGRESS_START = 50
        SPARK_PROGRESS_END = 95

        def report_spark_progress(rows_processed, total_rows):
            """
            CALLBACK FUNCTION: Spark calls this function after every chunk it processes.
            This allows us to push live progress to the UI without waiting for
            the entire million-row file to finish.
            """
            percent = int((rows_processed / total_rows) * 100) if total_rows else 0
            overall_progress = SPARK_PROGRESS_START + int(
                percent * (SPARK_PROGRESS_END - SPARK_PROGRESS_START) / 100
            )

            job.progress = overall_progress
            job.save(update_fields=["progress"]) # SQLite

            self.update_state(                    # Redis
                state="RUNNING",
                meta={
                    "current": rows_processed,
                    "total": total_rows,
                    "percent": percent,
                    "status": f"Processed {rows_processed}/{total_rows} rows ({percent}%)",
                },
            )

        file_path = job.file.path

        # DATA ENGINEERING BRIDGE: PySpark is built for Big Data formats (CSV, Parquet).
        # It does not support proprietary Excel formats natively. We use Polars here
        # to rapidly convert the file so Spark can read it.
        if file_path.endswith(".xlsx") or file_path.endswith(".xls"):
            logger.info("Worker Job %s: Converting Excel to CSV via Polars...", job_id)
            csv_path = file_path.replace(".xlsx", ".csv").replace(".xls", ".csv")
            df = pl.read_excel(file_path)
            df.write_csv(csv_path)
            file_path = csv_path

        # Actually trigger the PySpark transformation
        preview_data = process_data_with_spark(
            file=file_path,
            target_column=job.target_column,
            regex_pattern=regex_pattern,
            replacement_value=job.replacement_value,
            progress_callback=report_spark_progress,
        )

        # Job complete. Save the preview data and mark 100%.
        job.status = "SUCCESS"
        job.progress = 100
        job.result_data = {
            "message": f"Target column: {job.target_column}",
            "regex_used": regex_pattern,
            "preview": preview_data,
        }
        job.save()

    except Exception as exc:
        logger.exception("Worker Job %s failed", job_id)
        _retry_or_fail(self, job_id, exc)
