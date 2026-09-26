from django.contrib import admin

from .models import GitHubConnection, GitHubIdentity


@admin.register(GitHubConnection)
class GitHubConnectionAdmin(admin.ModelAdmin):
    list_display = ("owner", "organization", "github_username", "created_at")
    exclude = ("encrypted_token",)


@admin.register(GitHubIdentity)
class GitHubIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "github_username", "github_id", "last_used_at")
    exclude = ("encrypted_token",)
