"""social-auth pipeline steps.

Two checks run against every Google sign-in:

1. **Workspace domain** — the user's email must come from one of the configured
   Google Workspace domains (set via ``GOOGLE_WORKSPACE_DOMAIN``).
2. **Per-email allowlist** — if ``GOOGLE_WORKSPACE_ALLOWED_EMAILS`` is set,
   the user's exact email must also appear in that list. When empty/unset,
   any email from the allowed domain may sign in.

Both checks happen before ``social_user`` / ``create_user`` so a rejected
caller never gets a Django user row.
"""
from __future__ import annotations

from django.conf import settings
from social_core.exceptions import AuthForbidden


def ensure_workspace_domain(backend, details, response, *args, **kwargs):
    email = (details.get("email") or "").strip().lower()
    domain = email.split("@")[-1] if "@" in email else ""

    allowed_domains = {
        d.lower()
        for d in getattr(settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS", [])
        if d
    }
    if allowed_domains and domain not in allowed_domains:
        raise AuthForbidden(backend, "Only allowed Google Workspace domain can sign in.")


def ensure_allowed_email(backend, details, response, *args, **kwargs):
    """Reject sign-ins from emails not in the per-user allowlist.

    No-op when ``GOOGLE_WORKSPACE_ALLOWED_EMAILS`` is empty. Combine with
    ``ensure_workspace_domain`` for defence in depth.
    """
    allowed_emails = {
        addr.lower()
        for addr in getattr(settings, "GOOGLE_WORKSPACE_ALLOWED_EMAILS", [])
        if addr
    }
    if not allowed_emails:
        return  # allowlist disabled - fall back to domain-only check

    email = (details.get("email") or "").strip().lower()
    if email not in allowed_emails:
        raise AuthForbidden(
            backend,
            "Your account is not on the allowlist for this app. Contact an admin "
            "to be added.",
        )
