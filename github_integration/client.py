from urllib.parse import quote

import requests

API_URL = "https://api.github.com"
API_VERSION = "2022-11-28"
REQUEST_TIMEOUT = (5, 12)
LOG_TIMEOUT = (5, 20)


class GitHubError(Exception):
    """Raised when GitHub rejects an API request."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class GitHubAuthError(GitHubError):
    """Raised when GitHub rejects an API request because the token is invalid."""


class GitHubClient:
    def __init__(self, token, *, base_url=API_URL, debug=False, session=None):
        self.base_url = base_url.rstrip("/")
        self.debug = debug
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": API_VERSION,
            }
        )

    def clone(self):
        """Create an independent client for concurrent I/O."""
        authorization = self.session.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ")
        return type(self)(
            token,
            base_url=self.base_url,
            debug=self.debug,
        )

    def request(self, method, path, **kwargs):
        if self.debug:
            print(f"[DEBUG] {method} {path}")

        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )

        if self.debug:
            print(f"[DEBUG] Response: {response.status_code}")

        if not response.ok:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            error_class = (
                GitHubAuthError if response.status_code == 401 else GitHubError
            )
            raise error_class(
                f"{method} {path} failed ({response.status_code}): {message}",
                status_code=response.status_code,
            )

        if not response.content:
            return None
        return response.json()

    def get_authenticated_user(self):
        return self.request("GET", "/user")

    def get_organizations(self):
        organizations = []
        page = 1
        while True:
            page_organizations = self.request(
                "GET",
                "/user/orgs",
                params={"per_page": 100, "page": page},
            )
            if not page_organizations:
                break
            organizations.extend(page_organizations)
            if len(page_organizations) < 100:
                break
            page += 1
        return organizations

    def get_organization_repositories(self, organization):
        repositories = []
        page = 1
        organization = quote(organization, safe="")
        while True:
            page_repositories = self.request(
                "GET",
                f"/orgs/{organization}/repos",
                params={"type": "all", "per_page": 100, "page": page},
            )
            if not page_repositories:
                break
            repositories.extend(page_repositories)
            if len(page_repositories) < 100:
                break
            page += 1
        return repositories

    def get_organization(self, organization):
        return self.request("GET", f"/orgs/{quote(organization, safe='')}")

    def get_members(self, organization):
        members = []
        page = 1
        organization = quote(organization, safe="")
        while True:
            page_members = self.request(
                "GET",
                f"/orgs/{organization}/members",
                params={"per_page": 100, "page": page},
            )
            if not page_members:
                break
            members.extend(page_members)
            if len(page_members) < 100:
                break
            page += 1
        return members

    def get_repository(self, owner, repository):
        owner = quote(owner, safe="")
        repository = quote(repository, safe="")
        try:
            return self.request("GET", f"/repos/{owner}/{repository}")
        except GitHubError as exc:
            if "(404)" in str(exc):
                return None
            raise

    def check_template(self, owner, repository):
        data = self.get_repository(owner, repository)
        if data is None:
            raise GitHubError(
                f"Template repository does not exist: {owner}/{repository}"
            )
        if not data.get("is_template"):
            raise GitHubError(
                f"Repository is not configured as a template: {owner}/{repository}"
            )
        return data

    def create_from_template(self, template_owner, template_repository, owner, name):
        return self.request(
            "POST",
            f"/repos/{quote(template_owner, safe='')}/{quote(template_repository, safe='')}/generate",
            json={
                "owner": owner,
                "name": name,
                "private": True,
                "include_all_branches": False,
            },
        )

    def add_collaborator(self, owner, repository, username, permission="push"):
        return self.request(
            "PUT",
            f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/collaborators/{quote(username, safe='')}",
            json={"permission": permission},
        )

    def get_workflow_runs(self, owner, repository):
        try:
            data = self.request(
                "GET",
                f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/actions/runs",
                params={"per_page": 100},
            )
        except GitHubError as exc:
            if "(404)" in str(exc):
                return []
            raise
        return data.get("workflow_runs", [])

    def get_workflow_jobs(self, owner, repository, run_id):
        jobs = []
        page = 1
        owner = quote(owner, safe="")
        repository = quote(repository, safe="")
        while True:
            data = self.request(
                "GET",
                f"/repos/{owner}/{repository}/actions/runs/{run_id}/jobs",
                params={"per_page": 100, "page": page},
            )
            page_jobs = data.get("jobs", [])
            jobs.extend(page_jobs)
            if len(page_jobs) < 100:
                break
            page += 1
        return jobs

    def get_job_logs(self, owner, repository, job_id):
        path = f"/repos/{quote(owner, safe='')}/{quote(repository, safe='')}/actions/jobs/{job_id}/logs"
        response = self.session.get(
            f"{self.base_url}{path}",
            timeout=LOG_TIMEOUT,
            allow_redirects=True,
        )
        if not response.ok:
            error_class = (
                GitHubAuthError if response.status_code == 401 else GitHubError
            )
            raise error_class(
                f"GET {path} failed ({response.status_code}): {response.text}",
                status_code=response.status_code,
            )
        return response.content
