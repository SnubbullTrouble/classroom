import secrets

from django.contrib.auth import get_user_model, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from .models import GitHubIdentity
from .oauth import GitHubOAuthError, authorization_url, exchange_code, get_user


@require_GET
def github_login(request):
    state = secrets.token_urlsafe(32)
    request.session["github_oauth_state"] = state
    # Remember where @login_required came from so the callback can return there.
    next_url = request.GET.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        request.session["github_oauth_next"] = next_url
    else:
        request.session.pop("github_oauth_next", None)
    try:
        url = authorization_url(state)
    except GitHubOAuthError as exc:
        return JsonResponse({"detail": str(exc)}, status=503)
    return redirect(url)


@require_GET
def github_callback(request):
    error = request.GET.get("error")
    if error:
        return JsonResponse(
            {"detail": request.GET.get("error_description", error)},
            status=400,
        )

    expected_state = request.session.pop("github_oauth_state", "")
    received_state = request.GET.get("state", "")
    if not expected_state or not constant_time_compare(expected_state, received_state):
        return JsonResponse({"detail": "Invalid OAuth state."}, status=400)

    code = request.GET.get("code")
    if not code:
        return JsonResponse(
            {"detail": "GitHub did not return an authorization code."}, status=400
        )

    try:
        access_token = exchange_code(code)
        github_user = get_user(access_token)
    except GitHubOAuthError as exc:
        return JsonResponse({"detail": str(exc)}, status=502)

    login_name = github_user.get("login")
    github_id = github_user.get("id")
    if not login_name or not github_id:
        return JsonResponse(
            {"detail": "GitHub returned an incomplete user profile."}, status=502
        )

    user_model = get_user_model()
    with transaction.atomic():
        user, _ = user_model.objects.get_or_create(
            username=login_name,
            defaults={"email": github_user.get("email", "") or ""},
        )
        if github_user.get("email") and user.email != github_user["email"]:
            user.email = github_user["email"]
            user.save(update_fields=["email"])
        GitHubIdentity.objects.update_or_create(
            user=user,
            defaults={
                "github_id": github_id,
                "github_username": login_name,
                "encrypted_token": access_token,
                "revoked_at": None,
            },
        )

    next_url = request.session.pop("github_oauth_next", "")
    login(request, user)
    if next_url:
        return redirect(next_url)
    return JsonResponse(
        {
            "authenticated": True,
            "username": user.username,
            "github_username": login_name,
        }
    )


@require_GET
def logout_view(request):
    print("Before logout:", request.user, request.user.is_authenticated)

    logout(request)

    print("After logout:", request.user, request.user.is_authenticated)

    if request.accepts("text/html"):
        response = redirect("/")
    else:
        response = JsonResponse({"authenticated": False})

    response["Cache-Control"] = "no-store"
    return response
