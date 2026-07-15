import logging

import polars as pl
from celery import shared_task
from django.core.cache import cache

from .models import ProcessingJob
from .services.llm import generate_regex
from .services.read_columns import read_columns
from .services.spark import process_data_with_spark

logger = logging.getLogger(__name__)

# Errors that will never succeed on retry — fail the job immediately.
PERMANENT_ERRORS = (ValueError, FileNotFoundError, ProcessingJob.DoesNotExist)

MAX_TASK_RETRIES = 3


def _fail_job(job_id, message: str) -> None:
    try:
        job = ProcessingJob.objects.get(id=job_id)
        job.status = "FAILED"
        job.error_message = message
        job.save(update_fields=["status", "error_message"])
    except ProcessingJob.DoesNotExist:
        logger.error("Cannot mark job %s as failed — job not found", job_id)


def _retry_or_fail(task, job_id, exc: Exception) -> None:
    """Retry transient failures with exponential backoff; fail permanently otherwise."""
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
        countdown = 30 * (2 ** task.request.retries)  # 30s, 60s, 120s
        raise task.retry(exc=exc, countdown=countdown, max_retries=MAX_TASK_RETRIES)
    except task.MaxRetriesExceededError:
        _fail_job(job_id, str(exc))


@shared_task(bind=True)
def read_columns_task(self, job_id):
    """
    Background column discovery after upload — keeps all file parsing off
    the Django web process, including full Excel loads.
    """
    try:
        job = ProcessingJob.objects.get(id=job_id)
        columns = read_columns(job.file.path)
        if not columns:
            _fail_job(job_id, "No columns were found in the uploaded file.")
            return

        job.columns = columns
        job.save(update_fields=["columns"])
        logger.info("Worker Job %s: discovered %d columns", job_id, len(columns))

    except Exception as exc:
        logger.exception("Worker Job %s: column discovery failed", job_id)
        _retry_or_fail(self, job_id, exc)


@shared_task(bind=True)
def process_file_task(self, job_id):
    """
    Runs LLM regex generation, Excel conversion, and Spark replacement in
    the background — the web process only enqueues this task.
    """
    try:
        job = ProcessingJob.objects.get(id=job_id)
        job.status = "RUNNING"
        job.progress = 10
        job.save()

        logger.info("Worker Job %s: Translating prompt to regex...", job_id)
        self.update_state(
            state="RUNNING",
            meta={"current": 10, "total": 50, "status": "Extract Regex"},
        )

        cache_key = f"regex_prompt_{job.prompt.strip().lower()}"
        regex_pattern = cache.get(cache_key)

        if not regex_pattern:
            logger.info("Cache miss: Calling LLM...")
            regex_pattern = generate_regex(prompt=job.prompt)
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

        SPARK_PROGRESS_START = 50
        SPARK_PROGRESS_END = 95

        def report_spark_progress(rows_processed, total_rows):
            percent = int((rows_processed / total_rows) * 100) if total_rows else 0
            overall_progress = SPARK_PROGRESS_START + int(
                percent * (SPARK_PROGRESS_END - SPARK_PROGRESS_START) / 100
            )

            job.progress = overall_progress
            job.save(update_fields=["progress"])

            self.update_state(
                state="RUNNING",
                meta={
                    "current": rows_processed,
                    "total": total_rows,
                    "percent": percent,
                    "status": f"Processed {rows_processed}/{total_rows} rows ({percent}%)",
                },
            )

        file_path = job.file.path

        if file_path.endswith(".xlsx") or file_path.endswith(".xls"):
            logger.info("Worker Job %s: Converting Excel to CSV via Polars...", job_id)
            csv_path = file_path.replace(".xlsx", ".csv").replace(".xls", ".csv")
            df = pl.read_excel(file_path)
            df.write_csv(csv_path)
            file_path = csv_path

        preview_data = process_data_with_spark(
            file=file_path,
            target_column=job.target_column,
            regex_pattern=regex_pattern,
            replacement_value=job.replacement_value,
            progress_callback=report_spark_progress,
        )

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
