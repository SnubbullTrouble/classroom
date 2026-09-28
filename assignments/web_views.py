from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from datetime import timedelta
from django.views.decorators.http import require_POST
import requests

from github_integration import GitHubClient, GitHubError

from .models import Assignment, ReportJob
from .forms import AssignmentImportForm
from .publish import publish_assignment, retry_assignment_repositories
from reports.tasks import generate_report_job

IMPORT_OPTIONS_CACHE_SECONDS = 300

# Dashboard sort options: key -> (label, ordering). Ties fall back to due date.
DASHBOARD_SORTS = {
    "due": ("Due date (soonest)", ["due_at", "name"]),
    "due_desc": ("Due date (latest)", ["-due_at", "name"]),
    "name": ("Name (A–Z)", ["name", "due_at"]),
    "course": ("Course", ["course__name", "due_at"]),
    "status": ("Status", ["status_order", "due_at"]),
    "newest": ("Recently added", ["-created_at"]),
}
DEFAULT_DASHBOARD_SORT = "due"
STATUS_ORDER = Case(
    *[
        When(status=value, then=Value(index))
        for index, (value, _) in enumerate(Assignment.STATUS_CHOICES)
    ],
    output_field=IntegerField(),
)


def _discover_import_options(identity, force_refresh=False):
    if identity is None or identity.revoked_at is not None:
        return [], [], ""

    cache_key = (
        f"github-import-options:{identity.user_id}:{identity.updated_at.isoformat()}"
    )
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return (*cached, "")

    try:
        github = GitHubClient(identity.encrypted_token)
        organizations = github.get_organizations()

        templates = []
        cache.set(
            cache_key,
            (organizations, templates),
            IMPORT_OPTIONS_CACHE_SECONDS,
        )
        return organizations, templates, ""
    except (GitHubError, requests.RequestException) as exc:
        return [], [], str(exc)


def _invalidate_reports(assignment):
    # Repository state just changed, so any existing report (and any job
    # tracking one) is stale and must not be served or polled again.
    assignment.report_jobs.all().delete()
    assignment.reports.all().delete()


def _redirect_to_github_login(request):
    messages.info(
        request,
        "Your GitHub sign-in has expired. Please sign in again to continue.",
    )
    login_url = reverse("github-login") + "?" + urlencode({"next": request.path})
    return redirect(login_url)


def _queue_new_report_job(request, assignment):
    job = ReportJob.objects.create(
        assignment=assignment,
        requested_by=request.user,
        total_items=assignment.student_repositories.count(),
    )
    try:
        generate_report_job.delay(job.id)
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
    return job


def _get_or_queue_report_job(request, assignment):
    job = assignment.report_jobs.filter(
        requested_by=request.user,
        status__in=["queued", "running"],
    ).first()
    if job is not None:
        return job

    recent_job = assignment.report_jobs.filter(
        requested_by=request.user,
        status__in=["completed", "failed"],
        created_at__gte=timezone.now()
        - timedelta(seconds=settings.REPORT_REFRESH_COOLDOWN_SECONDS),
    ).first()
    if recent_job is not None:
        return recent_job

    return _queue_new_report_job(request, assignment)


@login_required(login_url="/auth/github/login/")
def assignment_dashboard(request):
    # Remember the last chosen sort so it sticks between visits.
    sort = request.GET.get("sort") or request.session.get("dashboard_sort")
    if sort not in DASHBOARD_SORTS:
        sort = DEFAULT_DASHBOARD_SORT
    request.session["dashboard_sort"] = sort

    assignments = (
        Assignment.objects.filter(course__owner=request.user)
        .select_related("course")
        .annotate(
            repository_count=Count("student_repositories", distinct=True),
            created_repository_count=Count(
                "student_repositories",
                filter=Q(student_repositories__status="created"),
                distinct=True,
            ),
        )
        .annotate(status_order=STATUS_ORDER)
        .prefetch_related("student_repositories")
        .order_by(*DASHBOARD_SORTS[sort][1])
    )
    return render(
        request,
        "assignments/dashboard.html",
        {
            "assignments": assignments,
            "sort": sort,
            "sort_options": [(key, label) for key, (label, _) in DASHBOARD_SORTS.items()],
            "github_identity": getattr(request.user, "github_identity", None),
        },
    )


@login_required(login_url="/auth/github/login/")
def import_assignment(request):
    identity = getattr(request.user, "github_identity", None)
    organizations, templates, discovery_error = _discover_import_options(
        identity,
        force_refresh=request.GET.get("refresh") == "1",
    )

    form = AssignmentImportForm(
        request.POST or None,
        organizations=organizations,
        templates=templates,
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            course, _ = request.user.courses.get_or_create(
                name=form.cleaned_data["course_name"],
                defaults={
                    "github_organization": form.cleaned_data["github_organization"],
                },
            )
            assignment = Assignment.objects.create(
                course=course,
                created_by=request.user,
                name=form.cleaned_data["assignment_name"],
                template_repository=form.cleaned_data["template_repository"],
                due_at=form.cleaned_data["due_at"],
                late_penalty=form.cleaned_data["late_penalty"],
            )
        messages.success(request, f"Draft created for {assignment.name}.")
        return redirect("assignment-dashboard")

    return render(
        request,
        "assignments/import.html",
        {
            "form": form,
            "discovery_error": discovery_error,
            "organization_count": len(organizations),
            "template_count": len(templates),
        },
    )


@login_required(login_url="/auth/github/login/")
def assignment_report_page(request, assignment_id):
    assignment = get_object_or_404(
        Assignment,
        pk=assignment_id,
        course__owner=request.user,
    )

    if assignment.status != "active":
        messages.error(
            request,
            "Publish the assignment before generating a report.",
        )
        return redirect("assignment-dashboard")

    report = assignment.reports.first()

    if report is not None:
        data = report.data or {}
        summary = data.setdefault("summary", {})

        summary.setdefault("students", 0)
        summary.setdefault("submitted", 0)
        summary.setdefault("missing", 0)
        summary.setdefault("errors", 0)

        report.data = data

    if report is None or request.method == "POST":
        identity = getattr(request.user, "github_identity", None)

        if identity is None or identity.revoked_at is not None:
            return _redirect_to_github_login(request)

        job = _get_or_queue_report_job(request, assignment)

        if job.status in ["completed", "failed"] and report is not None:
            messages.info(
                request,
                "A report was refreshed recently. Please wait before refreshing again.",
            )
            return render(
                request,
                "assignments/report.html",
                {
                    "assignment": assignment,
                    "report": report,
                },
            )

        return render(
            request,
            "assignments/report_waiting.html",
            {
                "assignment": assignment,
                "job": job,
            },
        )

    return render(
        request,
        "assignments/report.html",
        {
            "assignment": assignment,
            "report": report,
        },
    )


@login_required(login_url="/auth/github/login/")
@require_POST
def retry_report_job_view(request, assignment_id):
    assignment = get_object_or_404(
        Assignment,
        pk=assignment_id,
        course__owner=request.user,
    )

    identity = getattr(request.user, "github_identity", None)
    if identity is None or identity.revoked_at is not None:
        return _redirect_to_github_login(request)

    # Drop any stuck queued/running job (e.g. left behind by a worker that
    # crashed mid-run) so a fresh one can take its place.
    assignment.report_jobs.filter(
        requested_by=request.user,
        status__in=["queued", "running"],
    ).delete()

    job = _queue_new_report_job(request, assignment)

    return render(
        request,
        "assignments/report_waiting.html",
        {
            "assignment": assignment,
            "job": job,
        },
    )


@login_required(login_url="/auth/github/login/")
@require_POST
def retry_assignment_repositories_view(request, assignment_id):
    assignment = get_object_or_404(
        Assignment,
        pk=assignment_id,
        course__owner=request.user,
        status="active",
    )
    identity = getattr(request.user, "github_identity", None)
    if identity is None or identity.revoked_at is not None:
        messages.error(request, "Sign in with GitHub before retrying repositories.")
        return redirect("assignment-dashboard")

    try:
        summary = retry_assignment_repositories(
            assignment,
            GitHubClient(identity.encrypted_token),
        )
    except GitHubError as exc:
        messages.error(request, str(exc))
        return redirect("assignment-dashboard")

    _invalidate_reports(assignment)
    identity.last_used_at = timezone.now()
    identity.save(update_fields=["last_used_at", "updated_at"])
    messages.success(
        request,
        f"Repository retry finished: {len(summary['created'])} processed, "
        f"{len(summary['failed'])} failed.",
    )
    return redirect("assignment-dashboard")


@login_required(login_url="/auth/github/login/")
@require_POST
def publish_assignment_view(request, assignment_id):
    assignment = get_object_or_404(
        Assignment,
        pk=assignment_id,
        course__owner=request.user,
        status="draft",
    )
    identity = getattr(request.user, "github_identity", None)
    if identity is None or identity.revoked_at is not None:
        messages.error(request, "Sign in with GitHub before publishing an assignment.")
        return redirect("assignment-dashboard")

    try:
        summary = publish_assignment(
            assignment,
            GitHubClient(identity.encrypted_token),
            identity.github_username,
        )
    except GitHubError as exc:
        messages.error(request, str(exc))
        return redirect("assignment-dashboard")

    _invalidate_reports(assignment)
    identity.last_used_at = timezone.now()
    identity.save(update_fields=["last_used_at", "updated_at"])
    messages.success(
        request,
        f"Published {assignment.name}: {len(summary['created'])} repositories created or linked.",
    )
    return redirect("assignment-dashboard")
