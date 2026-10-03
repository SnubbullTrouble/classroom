from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone as django_timezone

from accounts.models import GitHubIdentity

from .models import Assignment, Course, Report, ReportJob, Student, StudentRepository


class AssignmentDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="teacher")
        self.other_user = get_user_model().objects.create_user(username="other")
        self.course = Course.objects.create(
            owner=self.user,
            name="Fall 2026",
            github_organization="example-org",
        )
        Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Hello World",
            template_repository="homework_0_hello_world",
            due_at=datetime(2026, 9, 20, 21, 5, tzinfo=timezone.utc),
        )

    def test_anonymous_user_is_sent_to_github_login(self):
        response = self.client.get("/assignments/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/github/login/", response["Location"])

    def test_authenticated_user_sees_owned_assignments(self):
        self.client.force_login(self.user)

        response = self.client.get("/assignments/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hello World")
        self.assertContains(response, "Fall 2026")
        self.assertContains(response, "Publish assignment")
        self.assertNotContains(response, "No assignments yet")

    def test_dashboard_reports_linked_repository_count(self):
        assignment = Assignment.objects.first()
        student = Student.objects.create(
            course=self.course,
            github_username="ada",
        )
        StudentRepository.objects.create(
            assignment=assignment,
            student=student,
            repository_name="homework_0_hello_world_ada",
            status="created",
        )
        self.client.force_login(self.user)

        response = self.client.get("/assignments/")

        self.assertContains(response, "1 linked")

    def test_publish_page_requires_github_identity(self):
        assignment = Assignment.objects.first()
        self.client.force_login(self.user)

        response = self.client.post(f"/assignments/{assignment.id}/publish/")

        self.assertRedirects(response, "/assignments/")
        self.assertEqual(assignment.status, "draft")

    def _names_in_order(self, response):
        return [assignment.name for assignment in response.context["assignments"]]

    def test_dashboard_sorts_by_due_date_by_default_and_remembers_choice(self):
        Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Arrays",
            template_repository="homework_1_arrays",
            due_at=datetime(2026, 9, 10, 21, 5, tzinfo=timezone.utc),
        )
        self.client.force_login(self.user)

        response = self.client.get("/assignments/")
        self.assertEqual(self._names_in_order(response), ["Arrays", "Hello World"])

        response = self.client.get("/assignments/?sort=due_desc")
        self.assertEqual(self._names_in_order(response), ["Hello World", "Arrays"])

        response = self.client.get("/assignments/")
        self.assertEqual(self._names_in_order(response), ["Hello World", "Arrays"])

    def test_dashboard_sorts_by_status_in_workflow_order(self):
        Assignment.objects.create(
            course=self.course,
            created_by=self.user,
            name="Arrays",
            template_repository="homework_1_arrays",
            due_at=datetime(2026, 9, 10, 21, 5, tzinfo=timezone.utc),
            status="active",
        )
        self.client.force_login(self.user)

        response = self.client.get("/assignments/?sort=status")

        self.assertEqual(self._names_in_order(response), ["Hello World", "Arrays"])

    def test_dashboard_ignores_unknown_sort(self):
        self.client.force_login(self.user)

        response = self.client.get("/assignments/?sort=bogus")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["sort"], "due")

    def test_dashboard_does_not_show_another_users_assignments(self):
        other_course = Course.objects.create(
            owner=self.other_user,
            name="Other Course",
            github_organization="other-org",
        )
        Assignment.objects.create(
            course=other_course,
            created_by=self.other_user,
            name="Private Assignment",
            template_repository="private-template",
            due_at=datetime(2026, 9, 20, 21, 5, tzinfo=timezone.utc),
        )
        self.client.force_login(self.user)

        response = self.client.get("/assignments/")

        self.assertNotContains(response, "Private Assignment")

    def test_import_page_creates_a_draft_without_github_calls(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/assignments/import/",
            {
                "course_name": "Spring 2027",
                "github_organization": "example-org",
                "assignment_name": "Loops",
                "template_repository": "homework_3_loops",
                "due_at": "2026-10-01T17:05",
                "late_penalty": "-2",
            },
        )

        self.assertRedirects(response, "/assignments/")
        assignment = Assignment.objects.get(name="Loops")
        self.assertEqual(assignment.status, "draft")
        self.assertEqual(assignment.course.github_organization, "example-org")

    def test_import_page_requires_login(self):
        response = self.client.get("/assignments/import/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/github/login/", response["Location"])

    def test_report_page_renders_a_stored_report(self):
        assignment = Assignment.objects.first()
        assignment.status = "active"
        assignment.save(update_fields=["status"])
        Report.objects.create(
            assignment=assignment,
            generated_by=self.user,
            data={
                "summary": {"students": 1, "submitted": 1, "missing": 0},
                "rows": [
                    {
                        "student": "ada",
                        "repository": "homework_0_hello_world_ada",
                        "status": "submitted",
                        "submitted_at": "2026-09-20T20:00:00+00:00",
                        "scores": {"tests": "10/10"},
                        "total": {
                            "adjusted_earned": 10,
                            "maximum": 10,
                            "adjusted_percentage": 100,
                        },
                    }
                ],
            },
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/assignments/{assignment.id}/report/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hello World")
        self.assertContains(response, "ada")
        self.assertContains(response, "10/10")
        self.assertContains(response, "score-good")
        self.assertContains(response, "submission-on-time")
        self.assertContains(response, "Sep 20, 2026 - 4:00 PM")

    @patch("assignments.web_views.queue_report_job")
    def test_report_page_queues_work_when_no_report_exists(self, delay_mock):
        assignment = Assignment.objects.first()
        assignment.status = "active"
        assignment.save(update_fields=["status"])
        GitHubIdentity.objects.create(
            user=self.user,
            github_id=123,
            github_username="teacher",
            encrypted_token="github-token",
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/assignments/{assignment.id}/report/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generating Hello World")
        delay_mock.assert_called_once()

    @patch("assignments.web_views.queue_report_job")
    def test_report_page_can_refresh_an_existing_report(self, delay_mock):
        assignment = Assignment.objects.first()
        assignment.status = "active"
        assignment.save(update_fields=["status"])
        Report.objects.create(
            assignment=assignment,
            generated_by=self.user,
            data={"summary": {}, "rows": []},
        )
        GitHubIdentity.objects.create(
            user=self.user,
            github_id=456,
            github_username="teacher",
            encrypted_token="github-token",
        )
        self.client.force_login(self.user)

        response = self.client.post(f"/assignments/{assignment.id}/report/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generating Hello World")
        delay_mock.assert_called_once()

    @patch("assignments.web_views.queue_report_job")
    def test_report_page_surfaces_the_real_error_when_the_job_fails_to_queue(
        self, delay_mock
    ):
        # e.g. the background thread fails to start.
        delay_mock.side_effect = Exception("Could not start background thread.")
        assignment = Assignment.objects.first()
        assignment.status = "active"
        assignment.save(update_fields=["status"])
        Report.objects.create(
            assignment=assignment,
            generated_by=self.user,
            data={"summary": {}, "rows": []},
        )
        GitHubIdentity.objects.create(
            user=self.user,
            github_id=456,
            github_username="teacher",
            encrypted_token="github-token",
        )
        self.client.force_login(self.user)

        response = self.client.post(f"/assignments/{assignment.id}/report/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Report refresh failed: Could not start background thread.",
        )
        self.assertNotContains(response, "refreshed recently")

    @patch("assignments.web_views.queue_report_job")
    def test_report_page_retries_after_reauth_instead_of_replaying_stale_auth_failure(
        self, delay_mock
    ):
        assignment = Assignment.objects.first()
        assignment.status = "active"
        assignment.save(update_fields=["status"])
        identity = GitHubIdentity.objects.create(
            user=self.user,
            github_id=789,
            github_username="teacher",
            encrypted_token="github-token",
        )
        failed_job = ReportJob.objects.create(
            assignment=assignment,
            requested_by=self.user,
            status="failed",
            error_message="Your GitHub sign-in is no longer valid. Please sign in again.",
            completed_at=django_timezone.now(),
        )
        # Re-authenticating refreshes the identity's updated_at to after the
        # failure, which is the signal that the old error is now stale.
        identity.save(update_fields=["updated_at"])
        self.client.force_login(self.user)

        response = self.client.get(f"/assignments/{assignment.id}/report/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Generating Hello World")
        delay_mock.assert_called_once()
        new_job = ReportJob.objects.exclude(id=failed_job.id).get()
        delay_mock.assert_called_once_with(new_job.id)
