from django.urls import path
from . import views

urlpatterns = [
    path("upload/", views.upload_file, name="upload_file"),
    path("submit/<uuid:job_id>/", views.submit_job, name="submit_job"),
    path("status/<uuid:job_id>/", views.check_status, name="check_status"),
    path("cancel/<uuid:job_id>/", views.cancel_job, name="cancel_job"),
    path("results/<uuid:job_id>/", views.get_paginated_results, name="paginated_results"),
]
