"""POST /api/onboarding/provision — hire + default flow for integrators."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from apps.onboarding.models import FlowStep, OnboardingFlow, OnboardingProfile


@override_settings(ONBOARDING_API_TOKEN="secret")
class ProvisionApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        OnboardingFlow.objects.all().delete()

    def _post(self, payload):
        return self.client.post(
            "/api/onboarding/provision",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )

    def test_provision_seeds_default_flow_and_creates_employee(self):
        response = self._post(
            {
                "erp_employee_id": "E5001",
                "email": "hire@blackcapitaltechnology.com",
                "first_name": "New",
                "last_name": "Hire",
            }
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["created"])
        self.assertTrue(body["default_flow_created"])
        self.assertEqual(body["default_flow_slug"], "default")
        self.assertEqual(body["employee"]["erp_employee_id"], "E5001")
        self.assertEqual(body["employee"]["email"], "hire@blackcapitaltechnology.com")
        self.assertEqual(body["flow"]["slug"], "default")
        self.assertEqual(len(body["flow"]["steps"]), 4)
        self.assertEqual(len(body["steps"]), 4)
        self.assertEqual(body["assignment"]["status"], "pending")

        flow = OnboardingFlow.objects.get(slug="default")
        self.assertTrue(flow.is_default)
        self.assertEqual(FlowStep.objects.filter(flow=flow).count(), 4)

        User = get_user_model()
        user = User.objects.get(email="hire@blackcapitaltechnology.com")
        self.assertFalse(user.is_active)

    def test_provision_replay_is_idempotent(self):
        payload = {
            "erp_employee_id": "E5002",
            "email": "replay@blackcapitaltechnology.com",
        }
        self.assertEqual(self._post(payload).status_code, 201)
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["created"])
        self.assertFalse(body["default_flow_created"])
        self.assertEqual(OnboardingProfile.objects.filter(erp_employee_id="E5002").count(), 1)

    def test_provision_rejects_flow_slug(self):
        OnboardingFlow.objects.create(
            slug="default", name="Default", is_default=True, is_active=True
        )
        response = self._post(
            {
                "erp_employee_id": "E5003",
                "email": "x@blackcapitaltechnology.com",
                "flow_slug": "default",
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("flow_slug", response.json()["detail"])

    def test_provision_requires_api_key(self):
        response = self.client.post(
            "/api/onboarding/provision",
            data=json.dumps(
                {"erp_employee_id": "E1", "email": "x@blackcapitaltechnology.com"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
