import uuid

from django.db import models


def job_directory_path(instance, filename):
    return f"uploads/{instance.id}/{filename}"


class ProcessingJob(models.Model):
    STATUS_CHOICES = (
        ("QUEUED", "Queued"),
        ("RUNNING", "Running"),
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
    )

    # Tracking the state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="QUEUED")
    progress = models.IntegerField(default=0)

    # Storing the user inputs
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=job_directory_path)
    target_column = models.CharField(max_length=255)
    prompt = models.TextField()
    replacement_value = models.CharField(max_length=255, blank=True, default="")

    # Storing the final output
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Job {self.id} - {self.status}"
