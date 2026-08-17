import logging
import os

import polars as pl
from celery import current_app
from celery.result import AsyncResult
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .models import ProcessingJob
from .tasks import process_file_task, read_columns_task

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_EXTENSIONS = (".csv", ".xls", ".xlsx")


@csrf_exempt
def upload_file(request):
    """
    Step 1 of 2 (The "Thin" API Gateway):
    Stores the uploaded file in Django but immediately delegates the heavy
    lifting (reading the file) to Celery.
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
        # STATE MANAGEMENT: This creates the permanent record in SQLite.
        # The default status in the model is "DRAFT".
        job = ProcessingJob.objects.create(file=file)

        # MESSAGE BROKER: Django drops a message into Redis (db 0) for Celery.
        # apply_async is non-blocking, so this returns instantly to the frontend.
        read_columns_task.apply_async(args=[job.id], task_id=f"{job.id}-columns")

        return JsonResponse({"job_id": str(job.id), "status": job.status})

    except OSError:
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


@csrf_exempt  # No session cookie used, so CSRF token does not apply for this API
def submit_job(request, job_id):
    """
    Step 2 of 2:
    Validates the user's inputs against the columns Celery discovered,
    then queues the main PySpark processing task.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method"}, status=405)

    job = get_object_or_404(ProcessingJob, id=job_id)

    # State Machine Check: Ensure the user doesn't double-submit
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

    # Server-Side Allowlist Validation: Prevents users from injecting bad column names
    if not job.columns:
        return JsonResponse(
            {"error": "Column discovery is still in progress. Please wait."},
            status=400,
        )

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

    # Update SQLite with the final execution parameters
    job.target_column = target_column
    job.prompt = prompt
    job.replacement_value = replacement_value
    job.status = "QUEUED"
    job.save()

    # CORE ARCHITECTURE DECISION: We force the Celery task ID to exactly match
    # the SQLite job ID. This allows us to query Redis for live worker status later.
    process_file_task.apply_async(args=[job.id], task_id=str(job.id))

    return JsonResponse({"job_id": job.id, "status": "QUEUED"}, status=202)


def check_status(request, job_id):
    """
    The Polling Endpoint.
    This view reads from BOTH SQLite (for business status) and Redis (for live worker progress).
    """
    try:
        # 1. Read the permanent business state from SQLite
        job = ProcessingJob.objects.get(id=job_id)

        response_data = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
        }

        # 2. Read the ephemeral worker state from Redis
        # If running, interrogates Celery's Result Backend for real-time Spark updates
        if job.status == "RUNNING":
            task_result = AsyncResult(str(job.id))
            if isinstance(task_result.info, dict):
                response_data["progress_detail"] = task_result.info

        if job.status == "SUCCESS":
            response_data["result_data"] = job.result_data
        elif job.status == "FAILED":
            response_data["error_message"] = job.error_message

        # Returns the columns to the frontend so the dropdown can populate
        if job.status == "DRAFT":
            response_data["columns"] = job.columns

        return JsonResponse(response_data)

    except ProcessingJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)


@csrf_exempt
def cancel_job(request, job_id):
    """
    Hard-kills a running Celery/Spark process to free up server memory.
    """
    if request.method == "POST":
        try:
            job = ProcessingJob.objects.get(id=job_id)

            if job.status == "DRAFT":
                # Discard draft and stop any in-flight column discovery task.
                current_app.control.revoke(
                    f"{job.id}-columns", terminate=True, signal="SIGKILL"
                )
                job.delete()
                return JsonResponse({"message": "Draft job discarded."})

            # Only cancel if it's currently active in the background
            if job.status in ["QUEUED", "RUNNING"]:
                # terminate=True and SIGKILL operate at the OS level to forcibly
                # destroy the JVM/Spark worker process immediately.
                current_app.control.revoke(
                    str(job.id), terminate=True, signal="SIGKILL"
                )

                # Update SQLite so the frontend stops polling
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
    Reads the chunked Parquet output from PySpark and returns a specific page.
    Uses Polars LazyFrames to avoid loading millions of rows into Django's RAM.
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    job = get_object_or_404(ProcessingJob, id=job_id)

    if job.status != "SUCCESS":
        return JsonResponse(
            {"error": "Data processing is not complete yet."}, status=400
        )

    # 1. Parse Pagination Parameters (Default to page 1, 25 rows per page)
    try:
        page = int(request.GET.get("page", 1))
        limit = int(request.GET.get("limit", 25))
    except ValueError:
        return JsonResponse({"error": "Invalid page or limit parameters."}, status=400)

    # 2. Locate the Spark output directory
    processed_dir = os.path.join(os.path.dirname(job.file.path), "processed_data")

    if not os.path.exists(processed_dir):
        return JsonResponse(
            {"error": "Processed data directory not found on server."}, status=404
        )

    try:
        # 3. MEMORY OPTIMIZATION: Lazy scan the Parquet files.
        # This builds a query plan but does NOT load the files into RAM yet.
        lazy_df = pl.scan_parquet(f"{processed_dir}/part-*")

        # 4. Count total rows for the frontend UI pagination math
        total_rows = lazy_df.select(pl.len()).collect().item()
        total_pages = (total_rows + limit - 1) // limit

        # 5. Extract just the 25 rows we need.
        # `.collect()` is called ONLY on the sliced subset, keeping memory usage tiny.
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
