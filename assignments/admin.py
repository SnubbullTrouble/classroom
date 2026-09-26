from django.contrib import admin

from .models import (
    Assignment,
    Course,
    Report,
    ReportJob,
    Score,
    Student,
    StudentRepository,
    WorkflowJob,
    WorkflowRun,
)

admin.site.register(
    [
        Assignment,
        Course,
        Report,
        ReportJob,
        Score,
        Student,
        StudentRepository,
        WorkflowJob,
        WorkflowRun,
    ]
)
