from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import include, path

from accounts.views import github_callback, github_login, logout_view
from assignments.web_views import (
    assignment_dashboard,
    import_assignment,
    assignment_report_page,
    publish_assignment_view,
    retry_assignment_repositories_view,
    retry_report_job_view,
)


def health_check(request):
    return JsonResponse({"status": "ok"})


def homepage(request):
    return redirect("assignment-dashboard")


urlpatterns = [
    path("", homepage, name="service-index"),
    path("health/", health_check, name="health-check"),
    path("auth/github/login/", github_login, name="github-login"),
    path("auth/github/callback/", github_callback, name="github-callback"),
    path("auth/logout/", logout_view, name="logout"),
    path("assignments/", assignment_dashboard, name="assignment-dashboard"),
    path("assignments/import/", import_assignment, name="assignment-import"),
    path(
        "assignments/<int:assignment_id>/report/",
        assignment_report_page,
        name="assignment-report-page",
    ),
    path(
        "assignments/<int:assignment_id>/report/retry/",
        retry_report_job_view,
        name="assignment-report-retry",
    ),
    path(
        "assignments/<int:assignment_id>/publish/",
        publish_assignment_view,
        name="assignment-publish-page",
    ),
    path(
        "assignments/<int:assignment_id>/retry-repositories/",
        retry_assignment_repositories_view,
        name="assignment-retry-repositories",
    ),
    path("api/", include("api.urls")),
]
