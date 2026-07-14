import polars as pl
from celery import shared_task
from django.core.cache import cache

from .models import ProcessingJob
from .services.llm import generate_regex
from .services.spark import process_data_with_spark


@shared_task(
    bind=True,
    autoretry_for=(Exception,),  # Retry if ANY exception occurs
    retry_backoff=True,
    max_retries=3,
)
def process_file_task(self, job_id):
    """
    This runs completely in the background via Celery and Redis.
    It does not block your main Django web server.
    """
    try:
        # 1. Fetch the ticket from the database
        job = ProcessingJob.objects.get(id=job_id)

        job.status = "RUNNING"
        job.progress = 10
        job.save()

        # 2. Extract the Regex
        print(f"Worker Job {job_id}: Translating prompt to regex...")
        self.update_state(
            state="RUNNING",
            meta={
                "current": 10,
                "total": 50,
                "status": "Extract Regex",
            },
        )

        cache_key = f"regex_prompt_{job.prompt.strip().lower()}"
        regex_pattern = cache.get(cache_key)

        if not regex_pattern:
            print("Cache miss: Calling LLM...")
            regex_pattern = generate_regex(prompt=job.prompt)
            cache.set(cache_key, regex_pattern, timeout=86400)  # Cache for 24 hours
        else:
            print("Cache hit: Pulled regex from Redis!")

        job.progress = 30
        job.save()

        # 3. Process the file
        print(f"Worker Job {job_id}: Running Spark with pattern '{regex_pattern}'")
        self.update_state(
            state="RUNNING",
            meta={
                "current": 50,
                "total": 100,
                "status": "Running Spark",
            },
        )

        file_path = job.file.path

        # 4. Excel to CSV Conversion using Polars
        if file_path.endswith(".xlsx") or file_path.endswith(".xls"):
            print(f"Worker Job {job_id}: Converting Excel to CSV via Polars...")
            csv_path = file_path.replace(".xlsx", ".csv").replace(".xls", ".csv")

            # Read the Excel file and stream it directly to a CSV
            df = pl.read_excel(file_path)
            df.write_csv(csv_path)

            file_path = csv_path

        preview_data = process_data_with_spark(
            file=file_path,
            target_column=job.target_column,
            regex_pattern=regex_pattern,
            replacement_value=job.replacement_value,
        )

        # 5. Save the final results and mark as finished
        job.status = "SUCCESS"
        job.progress = 100
        job.result_data = {
            "message": f"Successfully processed data targeting {job.target_column}",
            "regex_used": regex_pattern,
            "preview": preview_data,
        }
        job.save()

    except Exception as e:
        job = ProcessingJob.objects.get(id=job_id)
        job.status = "FAILED"
        job.error_message = str(e)
        job.save()

        print(f"Worker Job {job_id} FAILED: {str(e)}")
