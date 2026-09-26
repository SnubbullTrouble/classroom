from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView

from .views import (
    AssignmentDetailView,
    AssignmentListCreateView,
    AssignmentReportView,
    AssignmentRepositoriesView,
    AssignmentRefreshResultsView,
    AssignmentPublishView,
    AssignmentReportJobView,
    ReportJobStatusView,
    GitHubTemplatesView,
)


class ApiHealthView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({"status": "ok"})


urlpatterns = [
    path("health/", ApiHealthView.as_view(), name="api-health"),
    path("github/templates/", GitHubTemplatesView.as_view(), name="github-templates"),
    path("assignments/", AssignmentListCreateView.as_view(), name="assignment-list"),
    path(
        "assignments/<int:pk>/",
        AssignmentDetailView.as_view(),
        name="assignment-detail",
    ),
    path(
        "assignments/<int:assignment_id>/repositories/",
        AssignmentRepositoriesView.as_view(),
        name="assignment-repositories",
    ),
    path(
        "assignments/<int:assignment_id>/report/",
        AssignmentReportView.as_view(),
        name="assignment-report",
    ),
    path(
        "assignments/<int:assignment_id>/refresh-results/",
        AssignmentRefreshResultsView.as_view(),
        name="assignment-refresh-results",
    ),
    path(
        "assignments/<int:assignment_id>/publish/",
        AssignmentPublishView.as_view(),
        name="assignment-publish",
    ),
    path(
        "assignments/<int:assignment_id>/report-jobs/",
        AssignmentReportJobView.as_view(),
        name="assignment-report-job",
    ),
    path(
        "report-jobs/<int:job_id>/",
        ReportJobStatusView.as_view(),
        name="report-job-status",
    ),
]
