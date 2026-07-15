from django.contrib import admin

from .models import ProcessingJob


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "target_column", "progress")
    list_filter = ("status",)
    readonly_fields = ("id", "result_data", "error_message")
