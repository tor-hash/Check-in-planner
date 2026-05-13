"""Regression: an onboardee (User is_active=False) must not be able to
reach the check-in planner or trip up the social-auth allowlist gate.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from social_core.exceptions import AuthForbidden

from apps.accounts.pipeline import ensure_allowed_email


class _FakeBackend:
    name = "google-oauth2"


class OnboardeeCannotReachPlannerTests(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.onboardee = User.objects.create_user(
            username="E1",
            email="onboardee@blackcapitaltechnology.com",
            password=None,
        )
        self.onboardee.set_unusable_password()
        self.onboardee.is_active = False
        self.onboardee.save(update_fields=["password", "is_active"])

    def test_login_required_endpoints_redirect_or_forbid(self):
        response = self.client.get("/api/state")
        self.assertIn(response.status_code, (302, 403))

    def test_force_login_with_inactive_user_does_not_grant_access(self):
        # Even if some bug let us call force_login on an inactive user,
        # the planner views should still require an authenticated active
        # session. Django's auth backends reject is_active=False at login,
        # but we double-check by hitting a write endpoint.
        self.client.force_login(self.onboardee)
        response = self.client.put(
            "/api/state/update", data="{}", content_type="application/json"
        )
        # 302 (login redirect because login_required treats inactive as
        # anonymous) or 403 (manager check) are both acceptable.
        self.assertIn(response.status_code, (302, 403))

    @override_settings(
        GOOGLE_WORKSPACE_ALLOWED_EMAILS=["someone-else@blackcapitaltechnology.com"]
    )
    def test_inactive_user_does_not_bypass_allowlist_via_reauth_short_circuit(self):
        # pipeline.ensure_allowed_email has a "existing user can always
        # re-auth" branch. That branch must NOT fire for inactive users,
        # otherwise an onboardee whose email later somehow becomes
        # invited could slip past the gate. With a non-empty allowlist
        # that excludes them, an inactive user should be rejected.
        with self.assertRaises(AuthForbidden):
            ensure_allowed_email(
                _FakeBackend(),
                details={"email": self.onboardee.email},
                response={},
            )
