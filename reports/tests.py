from datetime import datetime, timezone
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from assignments.models import Assignment, Course, Student, StudentRepository

from github_integration import GitHubError

from .services import (
    extract_log_text,
    extract_named_scores,
    report_data,
    summarize_scores,
)


class ReportServiceTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="teacher")
        course = Course.objects.create(
            owner=user,
            name="Fall 2026",
            github_organization="example-org",
        )
        self.assignment = Assignment.objects.create(
            course=course,
            created_by=user,
            name="Hello World",
            template_repository="homework_0_hello_world",
            due_at=datetime(2026, 9, 20, 21, 5, tzinfo=timezone.utc),
            late_penalty=-2,
        )
        student = Student.objects.create(course=course, github_username="ada")
        StudentRepository.objects.create(
            assignment=self.assignment,
            student=student,
            repository_name="homework_0_hello_world_ada",
        )

    def test_extracts_only_autograder_test_scores(self):
        log_text = "\n".join(
            [
                "2026-09-22T12:00:00.0000000Z Receiving objects: 100% (12/12), done.",
                "2026-09-22T12:00:01.0000000Z Total points for compiles: 2.00/2",
                "2026-09-22T12:00:01.0000000Z Total points for hasCout: 1.50/3",
                "2026-09-22T12:00:02.0000000Z Grand total tests passed: 1/2",
                "2026-09-22T12:00:02.0000000Z ##[notice]Points 3.5/5",
            ]
        )

        self.assertEqual(
            extract_named_scores(log_text),
            {"compiles": "2/2", "hasCout": "1.5/3"},
        )

    def test_falls_back_to_autograder_total_without_test_lines(self):
        log_text = "Step 1/3\n##[notice]Points 6/10"

        self.assertEqual(extract_named_scores(log_text), {"Autograder total": "6/10"})

    def test_summarizes_scores_with_penalty(self):
        self.assertEqual(
            summarize_scores({"test": "8/10", "quiz": "90%"}, -2),
            {
                "earned": 98.0,
                "maximum": 110.0,
                "percentage": 89.09,
                "adjusted_earned": 96.0,
                "adjusted_percentage": 87.27,
            },
        )

    def test_report_data_collects_latest_run_and_applies_late_penalty(self):
        github = Mock()
        github.get_workflow_runs.return_value = [
            {"id": 1, "created_at": "2026-09-20T20:00:00Z"},
            {"id": 2, "created_at": "2026-09-20T22:00:00Z"},
        ]
        github.get_workflow_jobs.return_value = [
            {"id": 10, "steps": [{"name": "tests"}]},
        ]
        github.get_job_logs.return_value = b"Total points for tests: 8/10"

        data = report_data(self.assignment, github)

        self.assertEqual(
            data["summary"],
            {"students": 1, "submitted": 1, "missing": 0, "errors": 0},
        )
        row = data["rows"][0]
        self.assertEqual(row["status"], "submitted")
        self.assertEqual(row["submitted_at"], "2026-09-20T22:00:00+00:00")
        self.assertEqual(row["late_penalty"], -2)
        self.assertEqual(row["total"]["adjusted_earned"], 6.0)
        github.get_workflow_jobs.assert_called_once_with(
            "example-org",
            "homework_0_hello_world_ada",
            2,
        )

    def test_report_data_includes_students_without_workflow_runs(self):
        github = Mock()
        github.get_workflow_runs.return_value = []

        data = report_data(self.assignment, github)

        self.assertEqual(data["summary"]["missing"], 1)
        self.assertEqual(data["rows"][0]["status"], "no_runs")
        self.assertIsNone(data["rows"][0]["total"])

    def test_extract_log_text_accepts_plain_text(self):
        self.assertEqual(extract_log_text(b"plain output"), "plain output")

    def test_one_repository_error_does_not_discard_other_rows(self):
        second_student = Student.objects.create(
            course=self.assignment.course,
            github_username="grace",
        )
        StudentRepository.objects.create(
            assignment=self.assignment,
            student=second_student,
            repository_name="homework_0_hello_world_grace",
        )
        github = Mock()

        def get_runs(_organization, repository_name):
            if repository_name.endswith("grace"):
                raise GitHubError("temporary GitHub failure")
            return [{"id": 1, "created_at": "2026-09-20T20:00:00Z"}]

        github.get_workflow_runs.side_effect = get_runs
        github.get_workflow_jobs.return_value = []

        data = report_data(self.assignment, github)

        self.assertEqual(data["summary"]["errors"], 1)
        self.assertEqual(
            {row["status"] for row in data["rows"]},
            {"submitted", "error"},
        )
