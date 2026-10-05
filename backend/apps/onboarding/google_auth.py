"""Google sign-in with an *opt-in* Drive scope.

Everyone signs in with the normal scopes (calendar, gmail.send). Google
Drive access is only requested when someone explicitly clicks "Giv
Drive-adgang" on the Onboarding → Indstillinger tab — in practice once, as
the shared scheduler account, which then uploads employee documents
(``drive.py``). That way managers are never asked to hand over full Drive
access just to log in.

How: ``drive_connect`` (views.py) sets a session flag and starts the normal
Google login; this backend adds the Drive scope while the flag is set, and
``clear_drive_connect_flag`` (last pipeline step) removes it again. The
backend keeps the name ``google-oauth2``, so the redirect URI and the stored
``UserSocialAuth`` rows are exactly the same as before. Because sign-in
uses ``include_granted_scopes=true``, later normal logins keep the Drive
grant.
"""
from __future__ import annotations

from social_core.backends.google import GoogleOAuth2

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
DRIVE_CONNECT_SESSION_KEY = "onboarding_drive_connect"


class GoogleOAuth2WithOptionalDrive(GoogleOAuth2):
    name = "google-oauth2"

    def get_scope(self):
        scope = list(super().get_scope())
        if self.strategy.session_get(DRIVE_CONNECT_SESSION_KEY) and DRIVE_SCOPE not in scope:
            scope.append(DRIVE_SCOPE)
        return scope


def clear_drive_connect_flag(strategy, *args, **kwargs):
    """Pipeline step: forget the one-off "also ask for Drive" request."""
    if strategy.session_get(DRIVE_CONNECT_SESSION_KEY):
        strategy.session_pop(DRIVE_CONNECT_SESSION_KEY)


def has_drive_access(user) -> bool:
    """Whether ``user``'s stored Google grant includes the Drive scope."""
    from apps.planner.google.credentials import _granted_scopes_from_extra, _social_auth_for_user

    social = _social_auth_for_user(user)
    if not social:
        return False
    extra = social.extra_data or {}
    if not extra.get("refresh_token"):
        return False
    return DRIVE_SCOPE in (_granted_scopes_from_extra(extra) or [])
