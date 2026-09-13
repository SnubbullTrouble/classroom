#!/usr/bin/env python3

"""
ex: python classroom.py create --template <template-repo-name>
"""

import argparse
import os
import sys
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"


@dataclass(frozen=True)
class Config:
    token: str
    org: str
    ssh_host: str
    debug: bool


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, token: str, debug: bool = False):
        self.debug = debug

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
            }
        )

    def request(self, method, path, **kwargs):
        url = f"{API_URL}{path}"

        if self.debug:
            print(f"[DEBUG] {method} {path}")

        response = self.session.request(
            method,
            url,
            timeout=30,
            **kwargs,
        )

        if self.debug:
            print(f"[DEBUG] Response: {response.status_code}")

        if not response.ok:
            try:
                data = response.json()
                message = data.get(
                    "message",
                    response.text,
                )
            except ValueError:
                message = response.text

            raise GitHubError(
                f"{method} {path} failed " f"({response.status_code}): {message}"
            )

        if not response.content:
            return None

        return response.json()

    def get_authenticated_user(self):
        return self.request("GET", "/user")

    def get_organization(self, org):
        return self.request(
            "GET",
            f"/orgs/{org}",
        )

    def get_members(self, org):
        """Return all members of the organization."""

        members = []
        page = 1

        while True:
            data = self.request(
                "GET",
                f"/orgs/{org}/members",
                params={
                    "per_page": 100,
                    "page": page,
                },
            )

            if not data:
                break

            members.extend(data)

            if len(data) < 100:
                break

            page += 1

        return members

    def get_repo(self, owner, repo):
        try:
            return self.request(
                "GET",
                f"/repos/{owner}/{repo}",
            )
        except GitHubError as exc:
            if "(404)" in str(exc):
                return None
            raise

    def repo_exists(self, owner, repo):
        return self.get_repo(owner, repo) is not None

    def check_template(self, owner, repo):
        data = self.get_repo(owner, repo)

        if data is None:
            raise GitHubError(f"Template repository does not exist: " f"{owner}/{repo}")

        if not data.get("is_template"):
            raise GitHubError(
                f"Repository is not configured as a " f"template: {owner}/{repo}"
            )

    def create_from_template(
        self,
        template_owner,
        template_repo,
        owner,
        name,
    ):
        return self.request(
            "POST",
            f"/repos/{template_owner}/" f"{template_repo}/generate",
            json={
                "owner": owner,
                "name": name,
                "private": True,
                "include_all_branches": False,
            },
        )

    def add_collaborator(
        self,
        owner,
        repo,
        username,
        permission="push",
    ):
        return self.request(
            "PUT",
            f"/repos/{owner}/{repo}/" f"collaborators/{username}",
            json={
                "permission": permission,
            },
        )

    def get_workflow_runs(self, owner, repo):
        try:
            return self.request(
                "GET",
                f"/repos/{owner}/{repo}/actions/runs",
                params={"per_page": 100},
            ).get("workflow_runs", [])
        except GitHubError as exc:
            if "(404)" in str(exc):
                return []
            raise

    def get_workflow_jobs(self, owner, repo, run_id):
        jobs = []
        page = 1

        while True:
            data = self.request(
                "GET",
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                params={"per_page": 100, "page": page},
            )
            page_jobs = data.get("jobs", [])
            jobs.extend(page_jobs)

            if len(page_jobs) < 100:
                break

            page += 1

        return jobs

    def get_job_logs(self, owner, repo, job_id):
        response = self.session.get(
            f"{API_URL}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            timeout=30,
            allow_redirects=True,
        )

        if not response.ok:
            raise GitHubError(
                f"GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs failed "
                f"({response.status_code}): {response.text}"
            )

        return response.content


def load_config():
    load_dotenv()

    token = os.getenv("GITHUB_TOKEN")
    org = os.getenv("GITHUB_ORG")
    ssh_host = os.getenv("GITHUB_SSH_HOST")

    missing = []

    if not token:
        missing.append("GITHUB_TOKEN")

    if not org:
        missing.append("GITHUB_ORG")

    if not ssh_host:
        missing.append("GITHUB_SSH_HOST")

    if missing:
        raise RuntimeError("Missing .env values: " + ", ".join(missing))

    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes", "on")

    return Config(
        token=token,
        org=org,
        ssh_host=ssh_host,
        debug=debug,
    )


def get_students(github, config):
    """Get organization members except the authenticated user."""

    me = github.get_authenticated_user()
    my_username = me["login"]

    members = github.get_members(config.org)

    students = [
        member["login"]
        for member in members
        if member["login"].lower() != my_username.lower()
    ]

    return my_username, students


def make_clone_url(config, repo):
    return f"git clone " f"{config.ssh_host}:" f"{config.org}/{repo}.git"


def ensure_repo_from_template(
    self,
    template_owner,
    template_repo,
    owner,
    repo,
):
    """
    Create a private repository from a template if it
    does not already exist.

    Returns True if created, False if it already existed.
    """

    if self.repo_exists(owner, repo):
        return False

    self.create_from_template(
        template_owner=template_owner,
        template_repo=template_repo,
        owner=owner,
        name=repo,
    )

    return True


def create_assignment(
    github,
    config,
    template,
    students,
):
    created = []
    skipped = []
    failed = []

    print()
    print(f"Organization : {config.org}")
    print(f"Template     : {template}")
    print(f"Students     : {len(students)}")
    print()

    for username in students:
        # Template name + "_" + GitHub username.
        repo = f"{template}_{username}"

        # Never touch an existing repository.
        if github.repo_exists(config.org, repo):
            print(f"SKIP    {repo} " f"(already exists)")
            skipped.append(username)
            continue

        try:
            print(f"CREATE  {repo}")

            github.create_from_template(
                template_owner=config.org,
                template_repo=template,
                owner=config.org,
                name=repo,
            )

            print(f"        granting {username} " f"push access")

            github.add_collaborator(
                owner=config.org,
                repo=repo,
                username=username,
                permission="push",
            )

            print(f"        clone: " f"{make_clone_url(config, repo)}")

            created.append(username)

        except GitHubError as exc:
            print(
                f"ERROR   {repo}: {exc}",
                file=sys.stderr,
            )
            failed.append(username)

    print()
    print("Summary")
    print("-------")
    print(f"Created : {len(created)}")
    print(f"Skipped : {len(skipped)}")
    print(f"Failed  : {len(failed)}")

    if skipped:
        print()
        print("Already existed:")
        for username in skipped:
            print(f"  {username}")

    if failed:
        print()
        print("Failed:")
        for username in failed:
            print(f"  {username}")

        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(
        description=("Lightweight GitHub Classroom replacement.")
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    create = subparsers.add_parser(
        "create",
        help="Create repositories for a template.",
    )

    create.add_argument(
        "--template",
        required=True,
        help="Template repository name.",
    )

    args = parser.parse_args()

    try:
        config = load_config()

        github = GitHub(
            config.token,
            debug=config.debug,
        )

        # Verify authentication.
        me = github.get_authenticated_user()
        print(f"Authenticated as: {me['login']}")

        # Verify organization access.
        github.get_organization(config.org)

        # Verify template.
        github.check_template(
            config.org,
            args.template,
        )

        # Organization membership is the roster.
        owner, students = get_students(
            github,
            config,
        )

        print(f"Organization owner: {owner}")

        # Attempt create owner copy
        owner_repo = f"{args.template}_{owner}"

        if ensure_repo_from_template(
            github,
            template_owner=config.org,
            template_repo=args.template,
            owner=config.org,
            repo=owner_repo,
        ):
            print(f"Created test repo: {owner_repo}")
        else:
            print(f"Test repo already exists: {owner_repo}")

        # Verify that there are students to create repos for.
        if not students:
            raise RuntimeError("No students found in the organization.")

        return create_assignment(
            github=github,
            config=config,
            template=args.template,
            students=students,
        )

    except (
        GitHubError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        print(
            f"\nERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
