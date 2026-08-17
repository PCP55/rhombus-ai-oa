import uuid
from django.db import models

def job_directory_path(instance, filename):
    """
    DATA ISOLATION:
    If two users upload a file named 'data.csv' at the exact same time, saving
    them to the same folder would cause a collision and overwrite the data.
    This function dynamically creates a unique folder for every single job
    (e.g., 'uploads/123e4567-.../data.csv').
    """
    return f"uploads/{instance.id}/{filename}"


class ProcessingJob(models.Model):
    # THE STATE MACHINE: This tuple strictly defines the allowed states.
    # It perfectly mirrors the Next.js UI states (DRAFT -> QUEUED -> RUNNING -> SUCCESS).
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

    # SECURITY (IDOR Prevention):
    # Instead of an auto-incrementing integer (1, 2, 3), we use a random UUID.
    # If a user's job is ID '2', they might guess URL /api/status/1/ and see
    # someone else's private data. A UUID makes guessing another job mathematically impossible.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    file = models.FileField(upload_to=job_directory_path)

    # JSONField allows us to store an array of strings (the column names) directly
    # in SQLite without needing to create a complex secondary relational table.
    columns = models.JSONField(default=list, blank=True)

    # TWO-STEP UPLOAD DESIGN:
    # Notice how target_column, prompt, and replacement_value all have `blank=True`.
    # Because our architecture splits the upload (Step 1) from the submission (Step 2),
    # the database MUST allow these fields to be empty when the row is first created.
    target_column = models.CharField(max_length=255, blank=True, default="")
    prompt = models.TextField(blank=True, default="")
    replacement_value = models.CharField(max_length=255, blank=True, default="")

    # Storing the final output
    result_data = models.JSONField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Job {self.id} - {self.status}"
