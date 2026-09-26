from django.db import transaction

from github_integration import GitHubError

from .models import StudentRepository


def provision_assignment_repositories(
    assignment,
    students,
    github_client,
    retry_existing=False,
):
    """Create assignment repositories and record per-student outcomes."""
    summary = {"created": [], "skipped": [], "failed": []}
    organization = assignment.course.github_organization

    for student in students:
        repository_name = f"{assignment.template_repository}_{student.github_username}"
        repository, _ = StudentRepository.objects.get_or_create(
            assignment=assignment,
            student=student,
            defaults={"repository_name": repository_name},
        )

        if repository.status == "created" and not retry_existing:
            summary["skipped"].append(student.github_username)
            continue

        try:
            with transaction.atomic():
                if github_client.get_repository(organization, repository_name) is None:
                    github_client.create_from_template(
                        template_owner=organization,
                        template_repository=assignment.template_repository,
                        owner=organization,
                        name=repository_name,
                    )
                github_client.add_collaborator(
                    owner=organization,
                    repository=repository_name,
                    username=student.github_username,
                    permission="push",
                )
                repository.status = "created"
                repository.error_message = ""
                repository.save(update_fields=["status", "error_message", "updated_at"])
            summary["created"].append(student.github_username)
        except GitHubError as exc:
            repository.status = "failed"
            repository.error_message = str(exc)
            repository.save(update_fields=["status", "error_message", "updated_at"])
            summary["failed"].append(student.github_username)

    return summary
