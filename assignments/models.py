from django.conf import settings
from django.db import models


class Course(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses",
    )
    name = models.CharField(max_length=200)
    github_organization = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="unique_course_owner_name",
            )
        ]

    def __str__(self):
        return self.name


class Assignment(models.Model):
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("provisioning", "Provisioning"),
        ("active", "Active"),
        ("closed", "Closed"),
    ]

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assignments",
    )
    name = models.CharField(max_length=200)
    template_repository = models.CharField(max_length=100)
    due_at = models.DateTimeField()
    late_penalty = models.IntegerField(default=-2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "name"],
                name="unique_assignment_course_name",
            )
        ]

    def __str__(self):
        return f"{self.course}: {self.name}"


class Student(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="students",
    )
    github_username = models.CharField(max_length=100)
    display_name = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["github_username"]
        constraints = [
            models.UniqueConstraint(
                fields=["course", "github_username"],
                name="unique_student_course_username",
            )
        ]

    def __str__(self):
        return self.display_name or self.github_username


class StudentRepository(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("created", "Created"),
        ("failed", "Failed"),
    ]

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="student_repositories",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="repositories",
    )
    repository_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["student__github_username"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "student"],
                name="unique_assignment_student_repository",
            ),
            models.UniqueConstraint(
                fields=["assignment", "repository_name"],
                name="unique_assignment_repository_name",
            ),
        ]

    def __str__(self):
        return self.repository_name


class WorkflowRun(models.Model):
    repository = models.ForeignKey(
        StudentRepository,
        on_delete=models.CASCADE,
        related_name="workflow_runs",
    )
    github_id = models.BigIntegerField()
    created_at = models.DateTimeField()
    status = models.CharField(max_length=30, blank=True)
    conclusion = models.CharField(max_length=30, blank=True)
    raw_data = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "github_id"],
                name="unique_repository_workflow_run",
            )
        ]


class WorkflowJob(models.Model):
    workflow_run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    github_id = models.BigIntegerField()
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=30, blank=True)
    conclusion = models.CharField(max_length=30, blank=True)
    raw_data = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workflow_run", "github_id"],
                name="unique_workflow_run_job",
            )
        ]


class Score(models.Model):
    workflow_job = models.ForeignKey(
        WorkflowJob,
        on_delete=models.CASCADE,
        related_name="scores",
    )
    test_name = models.CharField(max_length=200)
    score_text = models.CharField(max_length=100)
    earned = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    maximum = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workflow_job", "test_name"],
                name="unique_workflow_job_test_score",
            )
        ]


class Report(models.Model):
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="reports",
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_reports",
    )
    data = models.JSONField(default=dict)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]


class ReportJob(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="report_jobs",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="report_jobs",
    )
    report = models.ForeignKey(
        Report,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="job",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    completed_items = models.PositiveIntegerField(default=0)
    total_items = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
