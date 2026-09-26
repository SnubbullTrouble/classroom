from django.shortcuts import get_object_or_404
from django.conf import settings
from datetime import timedelta
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import GitHubConnection, GitHubIdentity
from assignments.models import Assignment, Report, ReportJob, StudentRepository
from assignments.publish import publish_assignment
from github_integration import GitHubClient, GitHubError
from reports.services import generate_report
from reports.tasks import generate_report_job

from .serializers import (
    AssignmentSerializer,
    ReportSerializer,
    StudentRepositorySerializer,
)


class AssignmentListCreateView(generics.ListCreateAPIView):
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        return Assignment.objects.filter(course__owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AssignmentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = AssignmentSerializer

    def get_queryset(self):
        return Assignment.objects.filter(course__owner=self.request.user)


class AssignmentRepositoriesView(generics.ListAPIView):
    serializer_class = StudentRepositorySerializer

    def get_queryset(self):
        assignment = get_object_or_404(
            Assignment,
            pk=self.kwargs["assignment_id"],
            course__owner=self.request.user,
        )
        return StudentRepository.objects.filter(assignment=assignment)


class GitHubTemplatesView(APIView):
    def get(self, request):
        organization = request.query_params.get("organization", "").strip()
        if not organization:
            return Response({"detail": "organization is required."}, status=400)

        identity = GitHubIdentity.objects.filter(
            user=request.user,
            revoked_at__isnull=True,
        ).first()
        if identity is None:
            return Response(
                {"detail": "GitHub authentication is required."},
                status=401,
            )

        try:
            repositories = GitHubClient(
                identity.encrypted_token
            ).get_organization_repositories(organization)
        except GitHubError as exc:
            return Response({"detail": str(exc)}, status=502)

        return Response(
            {
                "organization": organization,
                "templates": [
                    {"name": repository["name"]}
                    for repository in repositories
                    if repository.get("is_template")
                ],
            }
        )


class AssignmentReportView(APIView):
    def get(self, request, assignment_id):
        assignment = get_object_or_404(
            Assignment,
            pk=assignment_id,
            course__owner=request.user,
        )
        report = assignment.reports.first()
        if report is None:
            return Response({"detail": "No report has been generated."}, status=404)
        return Response(ReportSerializer(report).data)


class AssignmentRefreshResultsView(APIView):
    def post(self, request, assignment_id):
        assignment = get_object_or_404(
            Assignment,
            pk=assignment_id,
            course__owner=request.user,
        )
        connection = GitHubConnection.objects.filter(
            owner=request.user,
            organization=assignment.course.github_organization,
            revoked_at__isnull=True,
        ).first()
        identity = None
        if connection is None:
            identity = GitHubIdentity.objects.filter(
                user=request.user,
                revoked_at__isnull=True,
            ).first()
        if connection is None and identity is None:
            return Response(
                {"detail": "No active GitHub connection exists for this organization."},
                status=400,
            )

        try:
            report = generate_report(
                assignment,
                request.user,
                GitHubClient(
                    connection.encrypted_token
                    if connection is not None
                    else identity.encrypted_token
                ),
            )
        except GitHubError as exc:
            return Response({"detail": str(exc)}, status=502)

        credential = connection or identity
        credential.last_used_at = timezone.now()
        credential.save(update_fields=["last_used_at", "updated_at"])
        return Response(ReportSerializer(report).data, status=201)


class AssignmentReportJobView(APIView):
    def post(self, request, assignment_id):
        assignment = get_object_or_404(
            Assignment,
            pk=assignment_id,
            course__owner=request.user,
            status="active",
        )
        identity = GitHubIdentity.objects.filter(
            user=request.user,
            revoked_at__isnull=True,
        ).first()
        if identity is None:
            return Response(
                {"detail": "Sign in with GitHub before generating a report."},
                status=400,
            )
        active_job = ReportJob.objects.filter(
            assignment=assignment,
            status__in=["queued", "running"],
        ).first()
        if active_job is not None:
            return Response(self._job_data(active_job), status=202)

        recent_job = ReportJob.objects.filter(
            assignment=assignment,
            requested_by=request.user,
            status__in=["completed", "failed"],
            created_at__gte=timezone.now()
            - timedelta(seconds=settings.REPORT_REFRESH_COOLDOWN_SECONDS),
        ).first()
        if recent_job is not None:
            return Response(
                {
                    "detail": "Report refresh was recently requested. Please wait before trying again.",
                    "retry_after": settings.REPORT_REFRESH_COOLDOWN_SECONDS,
                },
                status=429,
                headers={"Retry-After": str(settings.REPORT_REFRESH_COOLDOWN_SECONDS)},
            )

        job = ReportJob.objects.create(
            assignment=assignment,
            requested_by=request.user,
            total_items=assignment.student_repositories.count(),
        )
        try:
            generate_report_job.delay(job.id)
        except Exception as exc:
            job.status = "failed"
            job.error_message = f"Unable to queue report job: {exc}"
            job.save(update_fields=["status", "error_message"])
            return Response(
                {
                    "id": job.id,
                    "status": job.status,
                    "error_message": job.error_message,
                },
                status=503,
            )
        return Response(self._job_data(job), status=202)

    @staticmethod
    def _job_data(job):
        return {
            "id": job.id,
            "status": job.status,
            "completed_items": job.completed_items,
            "total_items": job.total_items,
            "error_message": job.error_message,
            "report_id": job.report_id,
        }


class ReportJobStatusView(APIView):
    def get(self, request, job_id):
        job = get_object_or_404(
            ReportJob,
            pk=job_id,
            requested_by=request.user,
        )
        return Response(AssignmentReportJobView._job_data(job))


class AssignmentPublishView(APIView):
    def post(self, request, assignment_id):
        assignment = get_object_or_404(
            Assignment,
            pk=assignment_id,
            course__owner=request.user,
            status="draft",
        )
        identity = GitHubIdentity.objects.filter(
            user=request.user,
            revoked_at__isnull=True,
        ).first()
        if identity is None:
            return Response(
                {"detail": "Sign in with GitHub before publishing an assignment."},
                status=400,
            )

        try:
            summary = publish_assignment(
                assignment,
                GitHubClient(identity.encrypted_token),
                identity.github_username,
            )
        except GitHubError as exc:
            return Response({"detail": str(exc)}, status=502)

        identity.last_used_at = timezone.now()
        identity.save(update_fields=["last_used_at", "updated_at"])
        return Response(
            {
                "assignment_id": assignment.id,
                "status": assignment.status,
                "summary": summary,
            },
            status=200,
        )
