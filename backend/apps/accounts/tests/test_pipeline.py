"""Tests for apps.accounts.pipeline."""
from __future__ import annotations

from django.test import TestCase, override_settings
from social_core.exceptions import AuthForbidden

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
