from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from .models import GitHubIdentity


@override_settings(
    GITHUB_CLIENT_ID="client-id",
    GITHUB_CLIENT_SECRET="client-secret",
    GITHUB_OAUTH_REDIRECT_URI="http://testserver/auth/github/callback/",
    GITHUB_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
)
class GitHubOAuthTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_login_returns_github_authorization_url(self):
        response = self.client.get("/auth/github/login/")

        self.assertEqual(response.status_code, 302)
        authorization_url = response["Location"]
        self.assertIn("https://github.com/login/oauth/authorize?", authorization_url)
        self.assertIn("client_id=client-id", authorization_url)
        self.assertIn("state=", authorization_url)

    @patch("accounts.views.get_user")
    @patch("accounts.views.exchange_code")
    def test_callback_creates_session_and_encrypted_identity(
        self,
        exchange_code_mock,
        get_user_mock,
    ):
        session = self.client.session
        session["github_oauth_state"] = "expected-state"
        session.save()
        exchange_code_mock.return_value = "github-access-token"
        get_user_mock.return_value = {
            "id": 12345,
            "login": "octocat",
            "email": "octocat@example.com",
        }

        response = self.client.get(
            "/auth/github/callback/?code=oauth-code&state=expected-state"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "octocat")
        user = get_user_model().objects.get(username="octocat")
        self.assertTrue(user.is_authenticated)
        identity = GitHubIdentity.objects.get(user=user)
        identity.refresh_from_db()
        self.assertEqual(identity.encrypted_token, "github-access-token")
        exchange_code_mock.assert_called_once_with("oauth-code")

    def test_callback_rejects_invalid_state(self):
        session = self.client.session
        session["github_oauth_state"] = "expected-state"
        session.save()

        response = self.client.get(
            "/auth/github/callback/?code=oauth-code&state=wrong-state"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid OAuth state", response.json()["detail"])

    def test_browser_logout_redirects_to_service_index(self):
        response = self.client.get("/auth/logout/", HTTP_ACCEPT="text/html")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_api_logout_returns_authenticated_false(self):
        response = self.client.get("/auth/logout/", HTTP_ACCEPT="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": False})
