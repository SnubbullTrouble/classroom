from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import GitHubIdentity
from assignments.models import Assignment, Course, ReportJob


class AssignmentApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="teacher",
            password="password",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-teacher",
            password="password",
        )
        self.course = Course.objects.create(
            owner=self.user,
            name="Fall 2026",
            github_organization="example-org",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_authenticated_user_can_create_and_list_assignments(self):
        payload = {
            "course": self.course.id,
            "name": "Hello World",
            "template_repository": "homework_0_hello_world",
            "due_at": "2026-09-20T21:05:00Z",
            "late_penalty": -2,
        }

        response = self.client.post("/api/assignments/", payload, format="json")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "draft")
        self.assertEqual(self.client.get("/api/assignments/").status_code, 200)

    def test_user_cannot_create_assignment_in_another_users_course(self):
        other_course = Course.objects.create(
            owner=self.other_user,
            name="Other Course",
            github_organization="other-org",
        )
        response = self.client.post(
            "/api/assignments/",
            {
                "course": other_course.id,
                "name": "Not Allowed",
                "template_repository": "template",
                "due_at": datetime(2026, 9, 20, tzinfo=timezone.utc).isoformat(),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("course", response.data)

    def test_anonymous_user_cannot_list_assignments(self):
        self.client.force_authenticate(None)
        response = self.client.get("/api/assignments/")
        self.assertEqual(response.status_code, 403)

    def test_refresh_requires_an_active_github_connection(self):
        assignment = Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Reportable assignment",
            template_repository="homework_0_hello_world",
            due_at="2026-09-20T21:05:00Z",
        )

        response = self.client.post(
            f"/api/assignments/{assignment.id}/refresh-results/",
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("GitHub connection", response.data["detail"])

    def test_publish_requires_github_identity(self):
        assignment = Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Publishable assignment",
            template_repository="homework_0_hello_world",
            due_at="2026-09-20T21:05:00Z",
        )

        response = self.client.post(
            f"/api/assignments/{assignment.id}/publish/",
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Sign in with GitHub", response.data["detail"])

    @patch("api.views.queue_report_job")
    def test_report_refresh_queues_one_job_and_reuses_it(self, delay_mock):
        identity = GitHubIdentity.objects.create(
            user=self.user,
            github_id=999,
            github_username="teacher",
            encrypted_token="encrypted-token",
        )
        assignment = Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Async report",
            template_repository="homework_0_hello_world",
            due_at="2026-09-20T21:05:00Z",
            status="active",
        )

        first = self.client.post(
            f"/api/assignments/{assignment.id}/report-jobs/",
            format="json",
        )
        second = self.client.post(
            f"/api/assignments/{assignment.id}/report-jobs/",
            format="json",
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.data["id"], second.data["id"])
        delay_mock.assert_called_once_with(first.data["id"])
        status = self.client.get(f"/api/report-jobs/{first.data['id']}/")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.data["status"], "queued")

    @patch("api.views.GitHubClient.get_organization_repositories")
    def test_template_discovery_uses_selected_organization(self, repositories_mock):
        GitHubIdentity.objects.create(
            user=self.user,
            github_id=1000,
            github_username="teacher",
            encrypted_token="encrypted-token",
        )
        repositories_mock.return_value = [
            {"name": "homework", "is_template": True},
            {"name": "notes", "is_template": False},
        ]

        response = self.client.get("/api/github/templates/?organization=example-org")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["templates"], [{"name": "homework"}])
        repositories_mock.assert_called_once_with("example-org")

    @patch("api.views.queue_report_job")
    def test_report_refresh_is_throttled_after_completed_job(self, delay_mock):
        identity = GitHubIdentity.objects.create(
            user=self.user,
            github_id=1001,
            github_username="teacher",
            encrypted_token="encrypted-token",
        )
        assignment = Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Throttled report",
            template_repository="homework_0_hello_world",
            due_at="2026-09-20T21:05:00Z",
            status="active",
        )
        first = self.client.post(
            f"/api/assignments/{assignment.id}/report-jobs/",
            format="json",
        )
        job = ReportJob.objects.get(id=first.data["id"])
        job.status = "completed"
        job.save(update_fields=["status"])

        second = self.client.post(
            f"/api/assignments/{assignment.id}/report-jobs/",
            format="json",
        )

        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second)
        delay_mock.assert_called_once_with(job.id)
