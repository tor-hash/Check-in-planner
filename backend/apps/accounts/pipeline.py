"""social-auth pipeline steps.

Two checks run against every Google sign-in:

1. **Workspace domain** — the user's email must come from one of the
   configured Google Workspace domains (set via ``GOOGLE_WORKSPACE_DOMAIN``).
2. **Allowlist OR open invitation** — the email must either be in the
   static ``GOOGLE_WORKSPACE_ALLOWED_EMAILS`` list (seed list, managed via
   env var) OR have an open ``apps.accounts.Invitation`` row created by an
   existing user. When the static list is empty *and* there are no
   invitations the table is effectively disabled and any user from the
   allowed domain may sign in.

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
    """Reject sign-ins from emails that are neither allowlisted nor invited.

    Decision tree:

    - Existing Django users are always allowed to re-authenticate (the gate
      only governs whether a *new* user row may be created).
    - If the static env allowlist is non-empty *or* any invitation exists,
      gating is "on" for first-time sign-ins: the email must be
      allowlisted or have an open invitation, otherwise we raise
      ``AuthForbidden``.
    - If both are empty, this step is a no-op — falls back to the domain
      check only (useful for dev / first-time bootstrap before any
      invitation has been created).
    - When an open invitation is consumed it is marked as accepted so the
      same row cannot be reused later.
    """
    from django.contrib.auth import get_user_model

    from .models import Invitation  # local import avoids AppRegistryNotReady

    allowed_emails = {
        addr.lower()
        for addr in getattr(settings, "GOOGLE_WORKSPACE_ALLOWED_EMAILS", [])
        if addr
    }

    email = (details.get("email") or "").strip().lower()

    if email and get_user_model().objects.filter(email__iexact=email).exists():
        return  # already a user, never re-gate on re-auth

    gating_enabled = bool(allowed_emails) or Invitation.objects.exists()
    if not gating_enabled:
        return  # nothing configured yet — fall through to domain-only check

    if email and email in allowed_emails:
        return

    invitation = (
        Invitation.objects.filter(email__iexact=email, accepted_at__isnull=True).first()
        if email
        else None
    )
    if invitation is not None:
        invitation.mark_accepted()
        return

    raise AuthForbidden(
        backend,
        "Your account is not on the allowlist for this app. Ask a colleague "
        "to invite you (from the planner home page) or contact an admin.",
    )
