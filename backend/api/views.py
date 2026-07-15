import logging
import os

import polars as pl
from celery import current_app
from celery.result import AsyncResult
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .models import ProcessingJob
from .services.read_columns import read_columns
from .tasks import process_file_task

logger = logging.getLogger(__name__)

# Only these are ever handed to the Excel->CSV converter or read directly by
# Spark (see tasks.py / services/spark.py) — reject anything else up front
# instead of letting it fail deep inside a background worker.
ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".xls", ".xlsx")


# @csrf_exempt is correct here, not just a shortcut: Django's CSRF protection
# defends session-cookie-authenticated requests from being forged by another
# site. This API is stateless (no login session/cookie), called cross-origin
# by the Next.js frontend via fetch(), so there's no CSRF token to check in
# the first place. Real authorization is handled instead by
# RequireAccessKeyMiddleware (APP_ACCESS_KEY) + CORS_ALLOWED_ORIGINS.
@csrf_exempt
def upload_file(request):
    """
    Step 1 of 2: stores the uploaded file and hands back its column names so
    the frontend can offer a dropdown instead of a free-text field. Nothing
    is queued for Celery yet -- the job is created in DRAFT status and only
    becomes real work once submit_job() below fills in the target column
    and prompt. Splitting it this way means the (possibly large) file is
    only ever uploaded once, not once to "preview" it and again to process it.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"error": "Missing required field: file"}, status=400)

    if not file.name.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        return JsonResponse(
            {
                "error": (
                    f"Unsupported file type '{file.name}'. Only "
                    f"{', '.join(ALLOWED_UPLOAD_EXTENSIONS)} files are accepted."
                )
            },
            status=400,
        )

    job = None
    try:
        job = ProcessingJob.objects.create(file=file)  # status defaults to DRAFT

        columns = read_columns(job.file.path)
        if not columns:
            job.delete()
            return JsonResponse(
                {"error": "No columns were found in the uploaded file."}, status=400
            )

        # Persist the columns we actually found so submit_job() can validate
        # against them below, instead of trusting whatever target_column the
        # client sends back.
        job.columns = columns
        job.save(update_fields=["columns"])

        return JsonResponse(
            {"job_id": str(job.id), "status": job.status, "columns": columns}
        )

    except OSError:
        # Disk full, permission denied, temp-dir too small, etc. -- common when
        # a multi-GB upload lands on a small droplet.
        logger.exception("Failed to store uploaded file for upload request")
        if job:
            job.delete()
        return JsonResponse(
            {
                "error": (
                    "The server could not store this file. It may be out of disk "
                    "space, or the upload may exceed the configured size limit."
                )
            },
            status=507,
        )
    except Exception:
        # Covers read_columns failures, a missing DB migration (saving the new
        # `columns` field), and anything else that would otherwise bubble up
        # as a bare HTML 500 page the frontend can't parse.
        logger.exception("Upload failed while staging file and reading columns")
        if job:
            job.delete()
        return JsonResponse(
            {
                "error": (
                    "Could not read columns from this file. Make sure it's a "
                    "well-formed CSV or Excel file."
                )
            },
            status=400,
        )


@csrf_exempt  # see note on upload_file above — no session cookie, so no CSRF token applies
def submit_job(request, job_id):
    """
    Step 2 of 2: attaches the target column / NL prompt / replacement value
    the user picked (after seeing the column dropdown from upload_file) to
    an existing DRAFT job, then actually queues it for Celery.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    job = get_object_or_404(ProcessingJob, id=job_id)

    if job.status != "DRAFT":
        return JsonResponse(
            {"error": f"Job has already been submitted (status: {job.status})."},
            status=400,
        )

    target_column = request.POST.get("target_column")
    prompt = request.POST.get("prompt")
    replacement_value = request.POST.get("replacement_value", "")

    if not all([target_column, prompt]):
        return JsonResponse({"error": "Missing required fields"}, status=400)

    # The frontend only ever offers columns from job.columns (populated by
    # upload_file), but the API itself must not trust that -- validate
    # server-side against what was actually read from the file, rather than
    # letting a client-supplied column name reach Spark unchecked.
    if target_column not in job.columns:
        return JsonResponse(
            {
                "error": (
                    f"'{target_column}' is not a column in the uploaded file. "
                    f"Available columns: {', '.join(job.columns)}"
                )
            },
            status=400,
        )

    job.target_column = target_column
    job.prompt = prompt
    job.replacement_value = replacement_value
    job.status = "QUEUED"
    job.save()

    # Pin the Celery task_id to the job_id so the polling API can look up
    # this task's live state later.
    process_file_task.apply_async(args=[job.id], task_id=str(job.id))

    return JsonResponse({"job_id": job.id, "status": "QUEUED"}, status=202)


def check_status(request, job_id):
    """Returns the current progress and data of a specific job."""
    try:
        job = ProcessingJob.objects.get(id=job_id)

        response_data = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
        }

        # While the job is running, pull the live Celery task state (populated via
        # self.update_state in process_file_task) to surface fine-grained progress
        # detail, e.g. percentage of rows processed, alongside the overall progress.
        if job.status == "RUNNING":
            task_result = AsyncResult(str(job.id))
            if isinstance(task_result.info, dict):
                response_data["progress_detail"] = task_result.info

        # Only include the heavy dataset if the job is actually finished
        if job.status == "SUCCESS":
            response_data["result_data"] = job.result_data
        elif job.status == "FAILED":
            response_data["error_message"] = job.error_message

        return JsonResponse(response_data)

    except ProcessingJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)


@csrf_exempt  # see note on upload_file — no session cookie, so no CSRF token applies
def cancel_job(request, job_id):
    if request.method == "POST":
        try:
            job = ProcessingJob.objects.get(id=job_id)

            if job.status == "DRAFT":
                # Never queued for Celery -- nothing to revoke, just discard
                # the uploaded file/row (e.g. the user picked a different
                # file after seeing the column dropdown).
                job.delete()
                return JsonResponse({"message": "Draft job discarded."})

            # Only cancel if it's currently active
            if job.status in ["QUEUED", "RUNNING"]:
                # terminate=True forcefully kills the Spark/LLM process mid-execution
                current_app.control.revoke(
                    str(job.id), terminate=True, signal="SIGKILL"
                )

                job.status = "FAILED"
                job.error_message = "Job was cancelled by the user."
                job.save()

                return JsonResponse({"message": "Job cancelled successfully."})
            else:
                return JsonResponse(
                    {"error": "Job is already finished or failed."}, status=400
                )

        except ProcessingJob.DoesNotExist:
            return JsonResponse({"error": "Job not found"}, status=404)

    return JsonResponse({"error": "Method not allowed"}, status=405)


def get_paginated_results(request, job_id):
    """
    Reads the chunked CSV output from PySpark and returns a specific page.
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    job = get_object_or_404(ProcessingJob, id=job_id)

    if job.status != "SUCCESS":
        return JsonResponse(
            {"error": "Data processing is not complete yet."}, status=400
        )

    # 1. Parse Pagination Parameters (Default to page 1, 50 rows per page)
    try:
        page = int(request.GET.get("page", 1))
        limit = int(request.GET.get("limit", 50))
    except ValueError:
        return JsonResponse({"error": "Invalid page or limit parameters."}, status=400)

    # 2. Locate the Spark output directory
    processed_dir = os.path.join(os.path.dirname(job.file.path), "processed_data")

    if not os.path.exists(processed_dir):
        return JsonResponse(
            {"error": "Processed data directory not found on server."}, status=404
        )

    try:
        # 3. Lazy scan the entire folder of chunked CSVs
        lazy_df = pl.scan_parquet(f"{processed_dir}/part-*")

        # 4. Count total rows for the frontend UI (Polars does this almost instantly)
        total_rows = lazy_df.select(pl.len()).collect().item()
        total_pages = (total_rows + limit - 1) // limit

        # 5. Extract just the 50 rows we need
        offset = (page - 1) * limit
        chunk_df = lazy_df.slice(offset, limit).collect()

        # 6. Convert to a list of dictionaries for JSON serialization
        results = chunk_df.to_dicts()

        return JsonResponse(
            {
                "data": results,
                "pagination": {
                    "current_page": page,
                    "total_pages": total_pages,
                    "total_rows": total_rows,
                    "has_next": page < total_pages,
                    "has_prev": page > 1,
                },
            }
        )

    except Exception:
        logger.exception("Failed to read paginated results for job %s", job.id)
        return JsonResponse(
            {"error": "Could not read the processed results for this job."},
            status=500,
        )
