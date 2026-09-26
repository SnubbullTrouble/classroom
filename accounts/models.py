from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


class EncryptedTextField(models.TextField):
    description = "Text encrypted with the application Fernet key"

    def _fernet(self):
        key = settings.GITHUB_TOKEN_ENCRYPTION_KEY
        if not key:
            raise ImproperlyConfigured(
                "GITHUB_TOKEN_ENCRYPTION_KEY must be configured before using encrypted credentials."
            )
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(
                "GITHUB_TOKEN_ENCRYPTION_KEY must be a valid Fernet key."
            ) from exc

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return self._fernet().encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ImproperlyConfigured(
                "Unable to decrypt a GitHub credential. Check the encryption key."
            ) from exc

    def to_python(self, value):
        return value


class GitHubConnection(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="github_connections",
    )
    organization = models.CharField(max_length=100)
    github_username = models.CharField(max_length=100)
    encrypted_token = EncryptedTextField()
    token_expires_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "organization"],
                name="unique_github_connection_owner_org",
            )
        ]

    def __str__(self):
        return f"{self.github_username} @ {self.organization}"


class GitHubIdentity(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="github_identity",
    )
    github_id = models.BigIntegerField(unique=True)
    github_username = models.CharField(max_length=100)
    encrypted_token = EncryptedTextField()
    revoked_at = models.DateTimeField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.github_username
