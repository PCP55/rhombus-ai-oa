import uuid

from django.db import models


def job_directory_path(instance, filename):
    return f"uploads/{instance.id}/{filename}"


class ProcessingJob(models.Model):
    STATUS_CHOICES = (
        ("DRAFT", "Draft"),
        ("QUEUED", "Queued"),
        ("RUNNING", "Running"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    )

    # Tracking the state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    progress = models.IntegerField(default=0)

    # Storing the user inputs
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=job_directory_path)
    columns = models.JSONField(default=list, blank=True)
    target_column = models.CharField(max_length=255, blank=True, default="")
    prompt = models.TextField(blank=True, default="")
    replacement_value = models.CharField(max_length=255, blank=True, default="")

    # Storing the final output
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Job {self.id} - {self.status}"
