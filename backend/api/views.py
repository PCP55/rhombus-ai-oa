import os

import polars as pl
from celery import current_app
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt

from .models import ProcessingJob
from .tasks import process_file_task


@csrf_exempt
def upload_file(request):
    if request.method == "POST":
        # 1. Grab the file and text data from the incoming request
        file = request.FILES.get("file")
        target_column = request.POST.get("target_column")
        prompt = request.POST.get("prompt")
        replacement_value = request.POST.get("replacement_value", "")

        if not all([file, target_column, prompt]):
            return JsonResponse({"error": "Missing required fields"}, status=400)

        # 2. Create the "receipt" in the database
        job = ProcessingJob.objects.create(
            file=file,
            target_column=target_column,
            prompt=prompt,
            replacement_value=replacement_value,
        )

        # 3. Hand the ticket to Celery using .delay()
        process_file_task.delay(job.id)

        # 4. Instantly return the Job ID to the user
        return JsonResponse({"job_id": job.id, "status": "QUEUED"}, status=201)

    return JsonResponse({"error": "Invalid request method"}, status=405)


def check_status(request, job_id):
    """Returns the current progress and data of a specific job."""
    try:
        job = ProcessingJob.objects.get(id=job_id)

        response_data = {
            "job_id": job.id,
            "status": job.status,
            "progress": job.progress,
        }

        # Only include the heavy dataset if the job is actually finished
        if job.status == "SUCCESS":
            response_data["result_data"] = job.result_data
        elif job.status == "FAILED":
            response_data["error_message"] = job.error_message

        return JsonResponse(response_data)

    except ProcessingJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)


@csrf_exempt
def cancel_job(request, job_id):
    if request.method == "POST":
        try:
            job = ProcessingJob.objects.get(id=job_id)

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

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
