"""GET /api/onboarding/flows and /api/onboarding/flows/<slug>."""
from __future__ import annotations

from django.test import Client, TestCase, override_settings

from apps.onboarding.tests.factories import make_default_flow


@override_settings(ONBOARDING_API_TOKEN="secret")
class FlowsApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        make_default_flow()

    def test_list(self):
        response = self.client.get("/api/onboarding/flows", HTTP_X_API_KEY="secret")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["results"]), 1)
        self.assertEqual(body["results"][0]["slug"], "default")
        self.assertEqual(len(body["results"][0]["steps"]), 3)

    def test_detail(self):
        response = self.client.get(
            "/api/onboarding/flows/default", HTTP_X_API_KEY="secret"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["slug"], "default")

    def test_detail_404(self):
        response = self.client.get(
            "/api/onboarding/flows/nope", HTTP_X_API_KEY="secret"
        )
        self.assertEqual(response.status_code, 404)
