from rest_framework import serializers

from assignments.models import (
    Assignment,
    Report,
    StudentRepository,
)


class AssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Assignment
        fields = (
            "id",
            "course",
            "name",
            "template_repository",
            "due_at",
            "late_penalty",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "status", "created_at", "updated_at")

    def validate_course(self, course):
        request = self.context["request"]
        if course.owner_id != request.user.id:
            raise serializers.ValidationError("You do not own this course.")
        return course


class StudentRepositorySerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentRepository
        fields = (
            "id",
            "student",
            "repository_name",
            "status",
            "error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ("id", "assignment", "data", "generated_by", "generated_at")
        read_only_fields = fields
