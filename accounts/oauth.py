from urllib.parse import urlencode

import requests
from django.conf import settings

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_URL = "https://api.github.com"


class GitHubOAuthError(Exception):
    """Raised when GitHub OAuth cannot complete."""


def _require_settings():
    if not settings.GITHUB_CLIENT_ID or not settings.GITHUB_CLIENT_SECRET:
        raise GitHubOAuthError(
            "CLIENT_ID and CLIENT_SECRET must be configured."
        )


def authorization_url(state):
    _require_settings()
    query = urlencode(
        {
            "client_id": settings.GITHUB_CLIENT_ID,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
            "scope": settings.GITHUB_OAUTH_SCOPES,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def exchange_code(code):
    _require_settings()
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
            "redirect_uri": settings.GITHUB_OAUTH_REDIRECT_URI,
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if not response.ok:
        raise GitHubOAuthError(
            f"GitHub token exchange failed ({response.status_code})."
        )
    data = response.json()
    if data.get("error") or not data.get("access_token"):
        raise GitHubOAuthError(
            data.get("error_description", "GitHub did not return a token.")
        )
    return data["access_token"]


def get_user(access_token):
    response = requests.get(
        f"{API_URL}/user",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    if not response.ok:
        raise GitHubOAuthError(f"GitHub user lookup failed ({response.status_code}).")
    return response.json()
