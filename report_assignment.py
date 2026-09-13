#!/usr/bin/env python3

"""Print GitHub Actions test results for a Classroom assignment."""

import argparse
import io
import re
import sys
import zipfile
from datetime import datetime
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table
from rich.text import Text

from create_assignment import GitHub, GitHubError, get_students, load_config

ASSIGNMENT_DUE_DATES = {
    "homework_0_hello_world": "2026-09-08T17:05:00-04:00",
    "homework_1_favorite_hobby": "2026-09-08T17:05:00-04:00",
    "homework_2_grade_calculator": "2026-09-19T17:05:00-04:00",
}

EASTERN_TIME = ZoneInfo("America/New_York")

SCORE_PATTERNS = (
    re.compile(
        r"\btotal\s+points\s+for\s+.+?:\s*(\d+(?:\.\d+)?)\s*/\s*" r"(\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bscore\s*[:=]\s*(\d+(?:\.\d+)?)\s*(?:/|out of)\s*" r"(\d+(?:\.\d+)?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bscore\s*[:=]\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
)


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_due_date(value):
    parsed = parse_time(value)
    if parsed is None or parsed.tzinfo is None:
        raise ValueError(
            "Due date must be configured as timezone-aware ISO-8601 in "
            "ASSIGNMENT_DUE_DATES."
        )
    return parsed


def assignment_due_date(template):
    if template not in ASSIGNMENT_DUE_DATES:
        raise ValueError(f"No due date configured for assignment: {template}")
    return parse_due_date(ASSIGNMENT_DUE_DATES[template])


def format_time(value):
    parsed = parse_time(value)
    return parsed.astimezone(EASTERN_TIME).strftime("%m-%d--%H-%M") if parsed else "-"


def extract_log_text(log_bytes):
    try:
        with zipfile.ZipFile(io.BytesIO(log_bytes)) as archive:
            return "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
            )
    except zipfile.BadZipFile:
        return log_bytes.decode("utf-8", errors="replace")


def extract_scores(log_text, step_name):
    matches = []
    for line in log_text.splitlines():
        if step_name.lower() not in line.lower() and "score" not in line.lower():
            continue
        for pattern in SCORE_PATTERNS:
            match = pattern.search(line)
            if match:
                if len(match.groups()) == 2:
                    matches.append(f"{match.group(1)}/{match.group(2)}")
                else:
                    matches.append(f"{match.group(1)}%")
                break
    return ", ".join(dict.fromkeys(matches)) or "-"


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


def score_style(score):
    values = score_value(score)
    if values is None:
        return "dim"
    earned, maximum = values
    if maximum and earned >= maximum:
        return "green"
    if earned > 0:
        return "yellow"
    return "red"


def styled_score(score):
    return Text(score, style=score_style(score))


def styled_penalty(penalty):
    return Text(str(penalty), style="red" if penalty < 0 else "green")


def total_score(scores):
    values = [score_value(score) for score in scores.values()]
    values = [value for value in values if value is not None]
    if not values:
        return "-"
    earned = sum(value[0] for value in values)
    maximum = sum(value[1] for value in values)
    percentage = earned / maximum * 100 if maximum else 0
    return f"{earned:g}/{maximum:g} ({percentage:.0f}%)"


def adjusted_total_score(scores, penalty):
    values = [score_value(score) for score in scores.values()]
    values = [value for value in values if value is not None]
    if not values:
        return "-"
    earned = max(0, sum(value[0] for value in values) + penalty)
    maximum = sum(value[1] for value in values)
    percentage = earned / maximum * 100 if maximum else 0
    return f"{earned:g}/{maximum:g} ({percentage:.0f}%)"


def styled_total(score):
    if score == "-":
        return Text(score, style="dim")
    percentage = float(re.search(r"\((\d+(?:\.\d+)?)%\)", score).group(1))
    if percentage >= 100:
        style = "bold green"
    elif percentage > 0:
        style = "bold yellow"
    else:
        style = "bold red"
    return Text(score, style=style)


def collect_rows(github, config, template, usernames, due_date):
    rows = []
    for username in usernames:
        repo = f"{template}_{username}"
        runs = github.get_workflow_runs(config.org, repo)
        if not runs:
            continue

        run = max(
            runs,
            key=lambda candidate: parse_time(candidate.get("created_at"))
            or datetime.min.replace(tzinfo=due_date.tzinfo),
        )
        run_time = parse_time(run.get("created_at"))
        late_penalty = -2 if run_time and run_time > due_date else 0
        scores = {}
        for job in github.get_workflow_jobs(config.org, repo, run["id"]):
            try:
                log_text = extract_log_text(
                    github.get_job_logs(config.org, repo, job["id"])
                )
            except GitHubError:
                log_text = ""

            for step in job.get("steps") or []:
                test_name = step.get("name", "").strip()
                score = extract_scores(log_text, test_name)
                if test_name and score != "-":
                    scores[test_name] = score

        rows.append(
            {
                "username": username,
                "time": format_time(run.get("created_at")),
                "scores": scores,
                "late_penalty": late_penalty,
            }
        )
    return rows


def print_report(rows, template):
    table = Table(
        title=f"GitHub Actions report: {template}",
        caption="Scores come from the latest workflow run. Late runs receive a -2 penalty.",
        expand=True,
    )
    test_names = list(
        dict.fromkeys(test_name for row in rows for test_name in row["scores"])
    )
    for column in [
        "Username",
        "Time",
        *test_names,
        "Total score",
        "Late submissions",
        "Final score",
    ]:
        table.add_column(column, overflow="fold")

    for row in rows:
        scores = [
            styled_score(row["scores"].get(test_name, "-")) for test_name in test_names
        ]
        table.add_row(
            row["username"],
            row["time"],
            *scores,
            styled_total(total_score(row["scores"])),
            styled_penalty(row["late_penalty"]),
            styled_total(adjusted_total_score(row["scores"], row["late_penalty"])),
        )
    Console().print(table)


def main():
    parser = argparse.ArgumentParser(
        description="Report GitHub Actions tests for a Classroom assignment."
    )
    parser.add_argument("--template", required=True, help="Homework repository prefix.")
    args = parser.parse_args()

    try:
        due_date = assignment_due_date(args.template)
        config = load_config()
        github = GitHub(config.token, debug=config.debug)
        github.get_organization(config.org)
        owner, students = get_students(github, config)
        rows = collect_rows(
            github,
            config,
            args.template,
            [owner, *students],
            due_date,
        )
        print_report(rows, args.template)
        if not rows:
            Console().print("No workflow runs or test jobs were found.")
        return 0
    except (GitHubError, RuntimeError, ValueError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
