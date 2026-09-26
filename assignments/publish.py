from github_integration import GitHubError

from .models import Student
from .services import provision_assignment_repositories


def publish_assignment(assignment, github_client, github_username):
    """Validate and provision an assignment as one explicit publish action."""
    organization = assignment.course.github_organization

    github_client.check_template(
        organization,
        assignment.template_repository,
    )

    members = github_client.get_members(organization)
    students = []

    for member in members:
        username = member.get("login")

        if not username or username.lower() == github_username.lower():
            continue

        student, _ = Student.objects.get_or_create(
            course=assignment.course,
            github_username=username,
        )
        students.append(student)

    if not students:
        raise GitHubError("No organization members were found to publish.")

    assignment.status = "provisioning"
    assignment.save(update_fields=["status", "updated_at"])

    try:
        summary = provision_assignment_repositories(
            assignment,
            students,
            github_client,
        )
    except Exception:
        assignment.status = "active"
        assignment.save(update_fields=["status", "updated_at"])
        raise

    assignment.status = "active"
    assignment.save(update_fields=["status", "updated_at"])

    return summary


def retry_assignment_repositories(assignment, github_client):
    """Retry repository creation and collaborator access for known students."""
    students = list(assignment.course.students.all())

    if not students:
        raise GitHubError("No students are linked to this assignment.")

    assignment.status = "provisioning"
    assignment.save(update_fields=["status", "updated_at"])

    try:
        summary = provision_assignment_repositories(
            assignment,
            students,
            github_client,
            retry_existing=True,
        )
    except Exception:
        assignment.status = "active"
        assignment.save(update_fields=["status", "updated_at"])
        raise

    assignment.status = "active"
    assignment.save(update_fields=["status", "updated_at"])

    return summary
