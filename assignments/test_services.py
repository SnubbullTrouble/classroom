from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from github_integration import GitHubError

from .models import Assignment, Course, Student, StudentRepository
from .services import provision_assignment_repositories
from .publish import retry_assignment_repositories


class ProvisionAssignmentRepositoriesTests(TestCase):
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
            due_at="2026-09-20T21:05:00Z",
        )
        self.students = [
            Student.objects.create(course=course, github_username="ada"),
            Student.objects.create(course=course, github_username="grace"),
        ]

    def test_provisions_each_student_and_records_created_status(self):
        github = Mock()
        github.get_repository.return_value = None

        summary = provision_assignment_repositories(
            self.assignment,
            self.students,
            github,
        )

        self.assertEqual(
            summary, {"created": ["ada", "grace"], "skipped": [], "failed": []}
        )
        self.assertEqual(
            StudentRepository.objects.filter(status="created").count(),
            2,
        )
        self.assertEqual(github.create_from_template.call_count, 2)
        self.assertEqual(github.add_collaborator.call_count, 2)

    def test_records_a_failure_without_stopping_other_students(self):
        github = Mock()
        github.get_repository.side_effect = [GitHubError("bad credentials"), None]

        summary = provision_assignment_repositories(
            self.assignment,
            self.students,
            github,
        )

        self.assertEqual(summary["failed"], ["ada"])
        self.assertEqual(summary["created"], ["grace"])
        failed = StudentRepository.objects.get(student=self.students[0])
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.error_message, "bad credentials")

    def test_retry_reprocesses_created_repositories(self):
        github = Mock()
        github.get_repository.return_value = {"name": "existing"}
        StudentRepository.objects.create(
            assignment=self.assignment,
            student=self.students[0],
            repository_name="homework_0_hello_world_ada",
            status="created",
        )

        summary = retry_assignment_repositories(self.assignment, github)

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "active")
        self.assertEqual(summary["created"], ["ada", "grace"])
        self.assertEqual(summary["skipped"], [])
        self.assertEqual(github.add_collaborator.call_count, 2)
