"""Tests for apps.accounts.pipeline."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from social_core.exceptions import AuthForbidden

from apps.accounts.models import Invitation
from apps.accounts.pipeline import ensure_allowed_email, ensure_workspace_domain


class _FakeBackend:
    name = "google-oauth2"


@override_settings(
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS=["blackcapitaltechnology.com"],
)
class WorkspaceDomainTests(TestCase):
    def test_allows_configured_domain(self):
        ensure_workspace_domain(
            _FakeBackend(),
            details={"email": "alice@blackcapitaltechnology.com"},
            response={},
        )

    def test_rejects_other_domain(self):
        with self.assertRaises(AuthForbidden):
            ensure_workspace_domain(
                _FakeBackend(),
                details={"email": "alice@gmail.com"},
                response={},
            )

    def test_rejects_missing_email(self):
        with self.assertRaises(AuthForbidden):
            ensure_workspace_domain(
                _FakeBackend(),
                details={"email": ""},
                response={},
            )

    def test_case_insensitive(self):
        ensure_workspace_domain(
            _FakeBackend(),
            details={"email": "Alice@BlackCapitalTechnology.com"},
            response={},
        )


class AllowedEmailTests(TestCase):
    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_empty_allowlist_is_noop(self):
        # No raise — allowlist disabled means domain-only check applies.
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "anybody@blackcapitaltechnology.com"},
            response={},
        )

    @override_settings(
        GOOGLE_WORKSPACE_ALLOWED_EMAILS=[
            "tor@blackcapitaltechnology.com",
            "mr@blackcapitaltechnology.com",
        ]
    )
    def test_allowlisted_email_passes(self):
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "tor@blackcapitaltechnology.com"},
            response={},
        )

    @override_settings(
        GOOGLE_WORKSPACE_ALLOWED_EMAILS=["tor@blackcapitaltechnology.com"]
    )
    def test_non_allowlisted_email_rejected(self):
        with self.assertRaises(AuthForbidden):
            ensure_allowed_email(
                _FakeBackend(),
                details={"email": "stranger@blackcapitaltechnology.com"},
                response={},
            )

    @override_settings(
        GOOGLE_WORKSPACE_ALLOWED_EMAILS=["tor@blackcapitaltechnology.com"]
    )
    def test_email_match_is_case_insensitive(self):
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "TOR@BlackCapitalTechnology.com"},
            response={},
        )

    @override_settings(
        GOOGLE_WORKSPACE_ALLOWED_EMAILS=["tor@blackcapitaltechnology.com"]
    )
    def test_missing_email_rejected(self):
        with self.assertRaises(AuthForbidden):
            ensure_allowed_email(
                _FakeBackend(),
                details={"email": ""},
                response={},
            )


class InvitationGateTests(TestCase):
    """ensure_allowed_email should also accept open invitations."""

    def setUp(self):
        User = get_user_model()
        self.inviter = User.objects.create_user(
            username="inviter",
            email="inviter@blackcapitaltechnology.com",
            password="x",
        )

    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_invited_email_passes_and_invitation_accepted(self):
        inv = Invitation.objects.create(
            email="newhire@blackcapitaltechnology.com", invited_by=self.inviter
        )
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "newhire@blackcapitaltechnology.com"},
            response={},
        )
        inv.refresh_from_db()
        self.assertIsNotNone(inv.accepted_at)

    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_invitation_match_is_case_insensitive(self):
        Invitation.objects.create(
            email="newhire@blackcapitaltechnology.com", invited_by=self.inviter
        )
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "NewHire@BlackCapitalTechnology.com"},
            response={},
        )

    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_accepted_invitation_cannot_be_reused(self):
        from django.utils import timezone

        Invitation.objects.create(
            email="stale@blackcapitaltechnology.com",
            invited_by=self.inviter,
            accepted_at=timezone.now(),
        )
        with self.assertRaises(AuthForbidden):
            ensure_allowed_email(
                _FakeBackend(),
                details={"email": "stale@blackcapitaltechnology.com"},
                response={},
            )

    @override_settings(
        GOOGLE_WORKSPACE_ALLOWED_EMAILS=["seed@blackcapitaltechnology.com"]
    )
    def test_allowlist_and_invitation_can_coexist(self):
        # Allowlisted email passes without needing an invitation.
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "seed@blackcapitaltechnology.com"},
            response={},
        )
        # Non-allowlisted email needs an invitation.
        with self.assertRaises(AuthForbidden):
            ensure_allowed_email(
                _FakeBackend(),
                details={"email": "uninvited@blackcapitaltechnology.com"},
                response={},
            )
        Invitation.objects.create(
            email="uninvited@blackcapitaltechnology.com", invited_by=self.inviter
        )
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "uninvited@blackcapitaltechnology.com"},
            response={},
        )

    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_empty_allowlist_and_no_invitations_is_open(self):
        # No gating configured at all -> domain-only check (this step no-ops).
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": "anyone@blackcapitaltechnology.com"},
            response={},
        )

    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_invitations_exist_but_caller_not_invited_is_rejected(self):
        # Once invitations exist, gating turns on for first-time callers
        # that are not invited.
        Invitation.objects.create(
            email="other@blackcapitaltechnology.com", invited_by=self.inviter
        )
        with self.assertRaises(AuthForbidden):
            ensure_allowed_email(
                _FakeBackend(),
                details={"email": "stranger@blackcapitaltechnology.com"},
                response={},
            )

    @override_settings(GOOGLE_WORKSPACE_ALLOWED_EMAILS=[])
    def test_existing_user_can_always_reauthenticate(self):
        # self.inviter already has a Django row. Even though they're neither
        # in the (empty) allowlist nor have an invitation, an invitation
        # existing for someone else flips gating on - the inviter must
        # still be able to sign back in.
        Invitation.objects.create(
            email="newhire@blackcapitaltechnology.com", invited_by=self.inviter
        )
        ensure_allowed_email(
            _FakeBackend(),
            details={"email": self.inviter.email},
            response={},
        )
