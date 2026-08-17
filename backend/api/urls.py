from django.urls import path
from . import views

urlpatterns = [
    # Step 1: The Initial Entry Point
    # No ID is needed here because the job hasn't been created in the database yet.
    path("upload/", views.upload_file, name="upload_file"),

    # URL ROUTING SECURITY: The `<uuid:job_id>` path converter.
    # By specifying `uuid:` instead of `str:` or `int:`, Django automatically validates
    # the format of the incoming URL. If a user or bot tries to hit
    # /api/status/drop-database/, Django immediately returns a 404 Not Found before
    # the request ever reaches your views.py, protecting your database from bad lookups.

    # Step 2: Attach the execution parameters to the specific draft job
    path("submit/<uuid:job_id>/", views.submit_job, name="submit_job"),

    # Step 3: The Polling Endpoint
    # Since HTTP is stateless, the frontend must continuously pass the job_id in the
    # URL so the server knows which SQLite row and Redis task to check.
    path("status/<uuid:job_id>/", views.check_status, name="check_status"),

    # Step 4 (Optional): The Kill Switch
    path("cancel/<uuid:job_id>/", views.cancel_job, name="cancel_job"),

    # Step 5: The Lazy-Loading Endpoint
    # Separating the result fetching from the status polling ensures that the frontend
    # only requests the heavy data payload exactly once, after success is confirmed.
    path("results/<uuid:job_id>/", views.get_paginated_results, name="paginated_results"),
]
