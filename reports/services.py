import io
import re
import zipfile
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

import requests

from django.utils import timezone as django_timezone

from assignments.models import Assignment, Report
from github_integration import GitHubClient, GitHubError

SCORE_PATTERNS = (
    re.compile(
        r"\btotal\s+points\s+for\s+[^:\r\n]{1,200}:\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bscore\s*[:=]\s*(\d+(?:\.\d+)?)\s*(?:/|out of)\s*(\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bscore\s*[:=]\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
)


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def extract_log_text(log_bytes):
    if not isinstance(log_bytes, bytes):
        raise TypeError(f"Expected bytes, got {type(log_bytes).__name__}")

    if zipfile.is_zipfile(io.BytesIO(log_bytes)):
        with zipfile.ZipFile(io.BytesIO(log_bytes)) as archive:
            parts = []

            for name in archive.namelist():
                if not name.endswith("/"):  # skip directories
                    parts.append(archive.read(name).decode("utf-8", errors="replace"))

            return "\n".join(parts)

    # Not a ZIP: treat it as ordinary text
    return log_bytes.decode("utf-8", errors="replace")


NUMBER = r"\d+(?:\.\d+)?"

NAMED_SCORE_PATTERN = re.compile(
    rf"^\s*(?P<test_name>[^:\r\n]+?)\s*:\s*"
    rf"(?P<earned>{NUMBER})\s*/\s*(?P<maximum>{NUMBER})\s*$",
    re.IGNORECASE,
)


def extract_named_scores(log_text):
    scores = {}

    for line in log_text.splitlines():
        match = NAMED_SCORE_PATTERN.match(line)
        if not match:
            continue

        test_name = match.group("test_name").strip()
        earned = match.group("earned")
        maximum = match.group("maximum")

        scores[test_name] = f"{earned}/{maximum}"

    return scores


def score_value(score):
    if score == "-":
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", score)
    if match:
        earned, maximum = (float(value) for value in match.groups())
        return earned, maximum
    match = re.fullmatch(r"(\d+(?:\.\d+)?)%", score)
    if match:
        return float(match.group(1)), 100.0
    return None


def summarize_scores(scores, penalty=0):
    values = [score_value(score) for score in scores.values()]
    values = [value for value in values if value is not None]
    if not values:
        return None
    earned = sum(value[0] for value in values)
    maximum = sum(value[1] for value in values)
    adjusted_earned = max(0, earned + penalty)
    return {
        "earned": earned,
        "maximum": maximum,
        "percentage": round(earned / maximum * 100, 2) if maximum else 0,
        "adjusted_earned": adjusted_earned,
        "adjusted_percentage": (
            round(adjusted_earned / maximum * 100, 2) if maximum else 0
        ),
    }


def _latest_run(runs):
    missing_time = datetime.min.replace(tzinfo=timezone.utc)
    return max(
        runs,
        key=lambda candidate: parse_time(candidate.get("created_at")) or missing_time,
    )


def _collect_job_scores(github_client, organization, repository_name, run_id):
    jobs = github_client.get_workflow_jobs(
        organization,
        repository_name,
        run_id,
    )

    def collect_job(job):
        client = _client_for_worker(github_client)

        try:
            log_text = extract_log_text(
                client.get_job_logs(
                    organization,
                    repository_name,
                    job["id"],
                )
            )
        except (GitHubError, requests.RequestException):
            return {}

        return extract_named_scores(log_text)

    with ThreadPoolExecutor(max_workers=8) as executor:
        scores = {}

        for job_scores in executor.map(collect_job, jobs):
            scores.update(job_scores)

    return scores


NUMBER = r"\d+(?:\.\d+)?"

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

NAMED_SCORE_PATTERN = re.compile(
    rf"(?P<test_name>[A-Za-z0-9][^:\r\n]{{0,200}}?)"
    rf"\s*(?::|=|-)\s*"
    rf"(?P<earned>{NUMBER})\s*/\s*(?P<maximum>{NUMBER})",
    re.IGNORECASE,
)

GENERIC_SCORE_PATTERN = re.compile(
    rf"\b(?P<earned>{NUMBER})\s*/\s*(?P<maximum>{NUMBER})\b"
)


def extract_named_scores(log_text):
    scores = {}

    for raw_line in log_text.splitlines():
        line = ANSI_ESCAPE.sub("", raw_line).strip()

        # Remove common GitHub Actions log prefixes such as:
        # 2026-09-22T12:34:56.000Z
        line = re.sub(
            r"^\d{4}-\d{2}-\d{2}T[^\s]+\s*",
            "",
            line,
        ).strip()

        match = NAMED_SCORE_PATTERN.search(line)

        if match:
            test_name = match.group("test_name").strip()
            earned = match.group("earned")
            maximum = match.group("maximum")

            # Prevent generic summary labels from becoming test names.
            if test_name.casefold() not in {
                "score",
                "points",
                "total",
                "total points",
                "tests passed",
            }:
                scores[test_name] = f"{earned}/{maximum}"

            continue

        # Handles lines like:
        # Autograder points: 8/10
        # Score: 9/10
        match = GENERIC_SCORE_PATTERN.search(line)

        if match and re.search(
            r"\b(score|points?|passed|total|autograder)\b",
            line,
            re.IGNORECASE,
        ):
            test_name = line[: match.start()].strip(" :-=")

            if not test_name:
                test_name = "Unnamed test"

            scores[test_name] = f"{match.group('earned')}/{match.group('maximum')}"

    return scores


def _missing_submission(student_username, repository_name):
    return {
        "student": student_username,
        "repository": repository_name,
        "status": "no_runs",
        "submitted_at": None,
        "late_penalty": 0,
        "scores": {},
        "total": None,
    }


def _error_submission(student_username, repository_name, error):
    return {
        "student": student_username,
        "repository": repository_name,
        "status": "error",
        "submitted_at": None,
        "late_penalty": 0,
        "scores": {},
        "total": None,
        "error": str(error),
    }


def _client_for_worker(github_client):
    if isinstance(github_client, GitHubClient):
        return github_client.clone()
    return github_client


def _collect_repository_row(assignment, repository, github_client):
    organization = assignment.course.github_organization
    client = _client_for_worker(github_client)
    runs = client.get_workflow_runs(organization, repository.repository_name)
    if not runs:
        return _missing_submission(
            repository.student.github_username,
            repository.repository_name,
        )

    run = _latest_run(runs)
    run_time = parse_time(run.get("created_at"))
    late_penalty = (
        assignment.late_penalty if run_time and run_time > assignment.due_at else 0
    )
    scores = _collect_job_scores(
        client,
        organization,
        repository.repository_name,
        run["id"],
    )
    return {
        "student": repository.student.github_username,
        "repository": repository.repository_name,
        "status": "submitted",
        "submitted_at": run_time.isoformat() if run_time else None,
        "late_penalty": late_penalty,
        "scores": scores,
        "total": summarize_scores(scores, late_penalty),
    }


def _collect_repository_row_safe(assignment, repository, github_client):
    try:
        return _collect_repository_row(assignment, repository, github_client)
    except (GitHubError, requests.RequestException) as exc:
        return _error_submission(
            repository.student.github_username,
            repository.repository_name,
            exc,
        )


def collect_rows(assignment, github_client, progress_callback=None):
    repositories = list(assignment.student_repositories.select_related("student"))
    with ThreadPoolExecutor(max_workers=12) as executor:
        results = executor.map(
            lambda repository: _collect_repository_row_safe(
                assignment,
                repository,
                github_client,
            ),
            repositories,
        )
        rows = []
        for result in results:
            rows.append(result)
            if progress_callback:
                progress_callback(len(rows), len(repositories))
        return rows


def report_data(assignment, github_client, progress_callback=None):
    rows = collect_rows(assignment, github_client, progress_callback)
    return {
        "assignment_id": assignment.id,
        "assignment": assignment.name,
        "generated_at": django_timezone.now().isoformat(),
        "summary": {
            "students": len(rows),
            "submitted": sum(row["status"] == "submitted" for row in rows),
            "missing": sum(row["status"] == "no_runs" for row in rows),
            "errors": sum(row["status"] == "error" for row in rows),
        },
        "rows": rows,
    }


def generate_report(
    assignment: Assignment,
    generated_by,
    github_client,
    progress_callback=None,
):
    data = report_data(assignment, github_client, progress_callback)
    return Report.objects.create(
        assignment=assignment,
        generated_by=generated_by,
        data=data,
    )
