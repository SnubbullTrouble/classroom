from datetime import datetime, timezone
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Assignment, Course
from .publish import publish_assignment


class PublishAssignmentTests(TestCase):
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
        )

    def test_publish_syncs_members_and_provisions_repositories(self):
        github = Mock()
        github.get_members.return_value = [
            {"login": "teacher"},
            {"login": "ada"},
            {"login": "grace"},
        ]
        github.get_repository.return_value = None

        summary = publish_assignment(self.assignment, github, "teacher")

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "active")
        self.assertEqual(summary["created"], ["ada", "grace"])
        self.assertEqual(self.assignment.course.students.count(), 2)
        github.check_template.assert_called_once_with(
            "example-org",
            "homework_0_hello_world",
        )

    def test_publish_requires_students(self):
        github = Mock()
        github.get_members.return_value = [{"login": "teacher"}]

        with self.assertRaisesRegex(Exception, "No organization members"):
            publish_assignment(self.assignment, github, "teacher")

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "draft")
