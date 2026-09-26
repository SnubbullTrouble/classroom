from unittest.mock import Mock

from django.test import SimpleTestCase

from .client import REQUEST_TIMEOUT, GitHubClient, GitHubError


class GitHubClientTests(SimpleTestCase):
    def test_request_sets_github_headers_and_returns_json(self):
        response = Mock(ok=True, content=b'{"login":"teacher"}', status_code=200)
        response.json.return_value = {"login": "teacher"}
        session = Mock()
        session.request.return_value = response

        client = GitHubClient("secret-token", session=session)
        result = client.get_authenticated_user()

        self.assertEqual(result, {"login": "teacher"})
        session.request.assert_called_once_with(
            "GET",
            "https://api.github.com/user",
            timeout=REQUEST_TIMEOUT,
        )
        headers = session.headers.update.call_args.args[0]
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertNotIn("secret-token", str(result))

    def test_request_raises_github_error_with_api_message(self):
        response = Mock(
            ok=False, content=b'{"message":"Bad credentials"}', status_code=401
        )
        response.json.return_value = {"message": "Bad credentials"}
        session = Mock()
        session.request.return_value = response

        with self.assertRaisesRegex(GitHubError, "Bad credentials"):
            GitHubClient("secret-token", session=session).get_authenticated_user()

    def test_discovers_organizations_and_repositories(self):
        organizations_response = Mock(
            ok=True,
            content=b'[{"login":"example-org"}]',
            status_code=200,
        )
        organizations_response.json.return_value = [{"login": "example-org"}]
        repositories_response = Mock(
            ok=True,
            content=b'[{"name":"homework","is_template":true}]',
            status_code=200,
        )
        repositories_response.json.return_value = [
            {"name": "homework", "is_template": True}
        ]
        session = Mock()
        session.request.side_effect = [organizations_response, repositories_response]

        client = GitHubClient("secret-token", session=session)

        self.assertEqual(client.get_organizations(), [{"login": "example-org"}])
        self.assertEqual(
            client.get_organization_repositories("example-org"),
            [{"name": "homework", "is_template": True}],
        )
        self.assertEqual(session.request.call_count, 2)
