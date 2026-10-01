import threading

from django.utils import timezone
import requests

from accounts.models import GitHubIdentity
from assignments.models import ReportJob
from github_integration import GitHubAuthError, GitHubClient, GitHubError

from .services import generate_report


def generate_report_job(job_id):
    job = ReportJob.objects.select_related(
        "assignment",
        "requested_by",
    ).get(id=job_id)

    def mark_failed(message):
        ReportJob.objects.filter(id=job.id).update(
            status="failed",
            error_message=str(message),
            completed_at=timezone.now(),
        )

    try:
        job.status = "running"
        job.started_at = timezone.now()
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "started_at",
                "error_message",
            ]
        )

        job.total_items = job.assignment.student_repositories.count()
        job.save(update_fields=["total_items"])

        identity = GitHubIdentity.objects.filter(
            user=job.requested_by,
            revoked_at__isnull=True,
        ).first()

        if identity is None:
            mark_failed("No active GitHub identity is available.")
            return

        def update_progress(completed, total):
            ReportJob.objects.filter(id=job.id).update(
                completed_items=completed,
                total_items=total,
            )

        report = generate_report(
            job.assignment,
            job.requested_by,
            GitHubClient(identity.encrypted_token),
            progress_callback=update_progress,
        )

        job.status = "completed"
        job.report = report
        job.completed_items = job.total_items
        job.completed_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "report",
                "completed_items",
                "completed_at",
            ]
        )

        identity.last_used_at = timezone.now()
        identity.save(update_fields=["last_used_at", "updated_at"])

    except GitHubAuthError:
        identity.revoked_at = timezone.now()
        identity.save(update_fields=["revoked_at", "updated_at"])
        mark_failed("Your GitHub sign-in is no longer valid. Please sign in again.")
        return

    except (GitHubError, requests.RequestException) as exc:
        mark_failed(exc)
        return

    except Exception as exc:
        mark_failed(f"Unexpected report error: {exc}")
        raise

    finally:
        # Safety net for exceptions that do not get handled as expected.
        if job is not None:
            ReportJob.objects.filter(
                id=job.id,
                status="running",
            ).update(
                status="failed",
                error_message="Report task exited unexpectedly.",
                completed_at=timezone.now(),
            )


def queue_report_job(job_id):
    # Runs in-process instead of via a Celery worker: report generation is
    # I/O-bound (GitHub API calls), so a plain thread keeps the web request
    # from blocking without needing a separate worker service/broker. A job
    # left "running" by a dead thread (e.g. a mid-job deploy) is recovered by
    # the existing cancel-and-retry flow rather than any retry here.
    threading.Thread(target=generate_report_job, args=(job_id,), daemon=True).start()
