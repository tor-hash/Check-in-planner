"""Build google.oauth2 credentials from social-auth's persisted refresh tokens.

Each Django ``User`` with a Google sign-in has a ``UserSocialAuth`` row whose
``extra_data`` JSON looks like::

    {
        "auth_time": 1715000000,
        "expires": 3599,
        "token_type": "Bearer",
        "refresh_token": "1//0g...",
        "access_token": "ya29...",
        "id_token": "eyJ..."
    }

We use ``refresh_token`` to mint a fresh access token whenever needed.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class GoogleCredentialsUnavailable(RuntimeError):
    """Raised when we cannot build credentials for a given user/manager."""


def _social_auth_for_user(user) -> object | None:
    """Return the GoogleOAuth2 social_auth row for ``user`` or None."""
    if not user or not user.is_authenticated:
        return None
    try:
        from social_django.models import UserSocialAuth
    except ImportError:  # pragma: no cover - dep is required in our settings
        return None
    return UserSocialAuth.objects.filter(user=user, provider="google-oauth2").first()


def credentials_for_user(user):
    """Return ``google.oauth2.credentials.Credentials`` for ``user``.

    Raises GoogleCredentialsUnavailable if the user has not connected Google
    yet, or if the persisted refresh token is missing.
    """
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover
        raise GoogleCredentialsUnavailable(
            "google-auth is not installed. Add it to requirements.txt."
        ) from exc

    social = _social_auth_for_user(user)
    if not social:
        raise GoogleCredentialsUnavailable(
            "User has not signed in with Google yet."
        )
    extra = social.extra_data or {}
    refresh_token = extra.get("refresh_token")
    access_token = extra.get("access_token")
    if not refresh_token:
        raise GoogleCredentialsUnavailable(
            "No Google refresh_token on file. The user must re-consent with "
            "prompt=consent + access_type=offline."
        )

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
        client_secret=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET,
        scopes=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE,
    )
    return creds


def credentials_for_manager(manager_profile):
    """Convenience: load creds for the Django user linked to a ManagerProfile."""
    if manager_profile is None:
        raise GoogleCredentialsUnavailable("ManagerProfile is None.")
    if not getattr(manager_profile, "user_id", None):
        raise GoogleCredentialsUnavailable(
            f"Manager '{manager_profile.legacy_id}' is not linked to a Django user. "
            "Sign in with the manager's Google account once to link the accounts."
        )
    return credentials_for_user(manager_profile.user)
