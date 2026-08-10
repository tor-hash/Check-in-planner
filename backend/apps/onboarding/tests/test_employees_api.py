"""POST/GET /api/onboarding/employees + GET /api/onboarding/employees/<erp_id>."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from apps.onboarding.models import OnboardingAssignment, OnboardingProfile, StepProgress
from apps.onboarding.tests.factories import make_default_flow


@override_settings(ONBOARDING_API_TOKEN="secret")
class CreateEmployeeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.flow = make_default_flow()

    def _post(self, payload, **extra):
        return self.client.post(
            "/api/onboarding/employees",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
            **extra,
        )

    def test_creates_user_and_profile_with_no_flow_attached(self):
        response = self._post(
            {
                "erp_employee_id": "E1234",
                "email": "jane@blackcapitaltechnology.com",
                "first_name": "Jane",
                "last_name": "Doe",
                "position": "Backend dev",
                "department": "Tech",
                "start_date": "2026-06-01",
            }
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["erp_employee_id"], "E1234")
        self.assertEqual(body["email"], "jane@blackcapitaltechnology.com")
        # Creation never attaches a flow — see services.py module docstring.
        self.assertEqual(body["status"], "no_flow")
        self.assertIsNone(body["flow"])
        self.assertEqual(body["steps"], [])

        User = get_user_model()
        user = User.objects.get(email="jane@blackcapitaltechnology.com")
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())

        profile = OnboardingProfile.objects.get(erp_employee_id="E1234")
        self.assertEqual(profile.position, "Backend dev")
        self.assertEqual(OnboardingAssignment.objects.filter(profile=profile).count(), 0)
        self.assertEqual(StepProgress.objects.filter(assignment__profile=profile).count(), 0)

    def test_idempotent_replay_returns_200(self):
        payload = {
            "erp_employee_id": "E1234",
            "email": "jane@blackcapitaltechnology.com",
        }
        self.assertEqual(self._post(payload).status_code, 201)
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(OnboardingProfile.objects.filter(erp_employee_id="E1234").count(), 1)

    def test_rejects_bad_email(self):
        response = self._post({"erp_employee_id": "E1", "email": "not-an-email"})
        self.assertEqual(response.status_code, 400)

    def test_rejects_flow_slug(self):
        response = self._post(
            {
                "erp_employee_id": "E1",
                "email": "x@blackcapitaltechnology.com",
                "flow_slug": "nope",
            }
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("flow_slug", response.json()["detail"])


@override_settings(ONBOARDING_API_TOKEN="secret")
class GetEmployeeTests(TestCase):
    def setUp(self):
        self.client = Client()
        make_default_flow()
        self.client.post(
            "/api/onboarding/employees",
            data=json.dumps(
                {"erp_employee_id": "E1", "email": "x@blackcapitaltechnology.com"}
            ),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )

    def test_get_returns_employee_with_no_flow_attached(self):
        response = self.client.get(
            "/api/onboarding/employees/E1", HTTP_X_API_KEY="secret"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["erp_employee_id"], "E1")
        self.assertIsNone(body["flow"])
        self.assertEqual(body["status"], "no_flow")

    def test_get_missing_returns_404(self):
        response = self.client.get(
            "/api/onboarding/employees/NOPE", HTTP_X_API_KEY="secret"
        )
        self.assertEqual(response.status_code, 404)

    def test_list_returns_results(self):
        response = self.client.get(
            "/api/onboarding/employees", HTTP_X_API_KEY="secret"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["results"][0]["erp_employee_id"], "E1")


@override_settings(ONBOARDING_API_TOKEN="secret")
class EmployeesByEmailTests(TestCase):
    def setUp(self):
        self.client = Client()
        make_default_flow()
        self.client.post(
            "/api/onboarding/employees",
            data=json.dumps(
                {
                    "erp_employee_id": "E1",
                    "email": "lookup@blackcapitaltechnology.com",
                    "first_name": "Look",
                    "last_name": "Up",
                }
            ),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )

    def test_get_by_email_query_returns_employee_state(self):
        response = self.client.get(
            "/api/onboarding/employees/by-email",
            {"email": "lookup@blackcapitaltechnology.com"},
            HTTP_X_API_KEY="secret",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["erp_employee_id"], "E1")
        self.assertEqual(body["email"], "lookup@blackcapitaltechnology.com")
        self.assertIsNone(body["flow"])

    def test_get_by_email_is_case_insensitive(self):
        response = self.client.get(
            "/api/onboarding/employees/by-email",
            {"email": "LOOKUP@blackcapitaltechnology.com"},
            HTTP_X_API_KEY="secret",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["erp_employee_id"], "E1")

    def test_post_by_email_body_returns_assignment(self):
        response = self.client.post(
            "/api/onboarding/employees/by-email",
            data=json.dumps({"email": "lookup@blackcapitaltechnology.com"}),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["erp_employee_id"], "E1")

    def test_unknown_email_returns_404(self):
        response = self.client.get(
            "/api/onboarding/employees/by-email",
            {"email": "nobody@blackcapitaltechnology.com"},
            HTTP_X_API_KEY="secret",
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_email_returns_400(self):
        response = self.client.get(
            "/api/onboarding/employees/by-email",
            HTTP_X_API_KEY="secret",
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_api_key(self):
        response = self.client.get(
            "/api/onboarding/employees/by-email",
            {"email": "lookup@blackcapitaltechnology.com"},
        )
        self.assertEqual(response.status_code, 401)
