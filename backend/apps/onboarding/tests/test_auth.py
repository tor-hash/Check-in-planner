"""Auth gating for /api/onboarding/*."""
from __future__ import annotations

from django.test import Client, TestCase, override_settings


class ApiAuthTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_token_not_configured_returns_503(self):
        with override_settings(ONBOARDING_API_TOKEN=""):
            response = self.client.get("/api/onboarding/employees")
            self.assertEqual(response.status_code, 503)

    @override_settings(ONBOARDING_API_TOKEN="secret-abc")
    def test_missing_header_returns_401(self):
        response = self.client.get("/api/onboarding/employees")
        self.assertEqual(response.status_code, 401)

    @override_settings(ONBOARDING_API_TOKEN="secret-abc")
    def test_wrong_header_returns_403(self):
        response = self.client.get(
            "/api/onboarding/employees", HTTP_X_API_KEY="wrong"
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(ONBOARDING_API_TOKEN="secret-abc")
    def test_correct_header_passes(self):
        response = self.client.get(
            "/api/onboarding/employees", HTTP_X_API_KEY="secret-abc"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("results", body)
        self.assertEqual(body["count"], 0)
