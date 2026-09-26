import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from assignments.models import ReportJob
from reports.tasks import generate_report_job

job = ReportJob.objects.get(pk=3)

print("Current status:", job.status)
print("Valid statuses:", ReportJob._meta.get_field("status").choices)

job.status = "pending"  # use the correct value from the printed choices
job.completed_items = 0
job.error_message = ""
job.started_at = None
job.completed_at = None
job.report = None
job.save()

print(f"Reset job {job.id} to {job.status}")

generate_report_job.delay(job.id)
