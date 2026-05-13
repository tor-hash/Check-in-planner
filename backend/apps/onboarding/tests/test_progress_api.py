"""PATCH /api/onboarding/employees/<erp_id>/steps/<step_id>."""
from __future__ import annotations

import json

from django.test import Client, TestCase, override_settings

from apps.onboarding.models import OnboardingAssignment
from apps.onboarding.tests.factories import make_default_flow


@override_settings(ONBOARDING_API_TOKEN="secret")
class StepProgressTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.flow = make_default_flow()
        response = self.client.post(
            "/api/onboarding/employees",
            data=json.dumps(
                {"erp_employee_id": "E1", "email": "x@blackcapitaltechnology.com"}
            ),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )
        self.steps_by_order = {
            step["order"]: step for step in response.json()["steps"]
        }

    def _patch(self, step_id: int, body: dict):
        return self.client.patch(
            f"/api/onboarding/employees/E1/steps/{step_id}",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )

    def test_complete_info_link_step_transitions_assignment_to_in_progress(self):
        step_id = self.steps_by_order[1]["id"]
        response = self._patch(step_id, {"status": "completed", "completion_data": {}})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["assignment_status"], "in_progress")
        self.assertEqual(body["step"]["status"], "completed")

    def test_complete_checkbox_rejects_bad_completion_data(self):
        step_id = self.steps_by_order[2]["id"]
        response = self._patch(step_id, {"status": "completed", "completion_data": {}})
        self.assertEqual(response.status_code, 400)

    def test_complete_checkbox_with_valid_data(self):
        step_id = self.steps_by_order[2]["id"]
        response = self._patch(
            step_id,
            {"status": "completed", "completion_data": {"checked": True}, "completed_by": "hr-portal"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["step"]["completed_by"], "hr-portal")

    def test_assignment_completes_when_all_required_done(self):
        # Steps 1 and 2 are required; step 3 (form) is optional in our fixture.
        self._patch(
            self.steps_by_order[1]["id"], {"status": "completed", "completion_data": {}}
        )
        response = self._patch(
            self.steps_by_order[2]["id"],
            {"status": "completed", "completion_data": {"checked": True}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assignment_status"], "completed")
        assignment = OnboardingAssignment.objects.get(profile__erp_employee_id="E1")
        self.assertIsNotNone(assignment.completed_at)

    def test_reopen_step_resets_assignment(self):
        step_id = self.steps_by_order[1]["id"]
        self._patch(step_id, {"status": "completed", "completion_data": {}})
        response = self._patch(step_id, {"status": "pending", "completion_data": {}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assignment_status"], "pending")

    def test_unknown_step_returns_404(self):
        response = self._patch(99999, {"status": "completed", "completion_data": {}})
        self.assertEqual(response.status_code, 404)

    def test_unknown_employee_returns_404(self):
        response = self.client.patch(
            "/api/onboarding/employees/NOPE/steps/1",
            data=json.dumps({"status": "completed", "completion_data": {}}),
            content_type="application/json",
            HTTP_X_API_KEY="secret",
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_status_returns_400(self):
        step_id = self.steps_by_order[1]["id"]
        response = self._patch(step_id, {"status": "made-up", "completion_data": {}})
        self.assertEqual(response.status_code, 400)
