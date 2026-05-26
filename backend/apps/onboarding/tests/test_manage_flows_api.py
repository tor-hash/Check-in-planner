"""Manager session API for onboarding flow CRUD."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from apps.onboarding.models import (
    FlowStep,
    OnboardingAssignment,
    OnboardingFlow,
    OnboardingProfile,
    StepProgress,
)
from apps.onboarding.services import create_employee_with_flow
from apps.onboarding.tests.factories import make_default_flow

User = get_user_model()


def _as_manager(user: User) -> User:
    group, _ = Group.objects.get_or_create(name="manager")
    user.groups.add(group)
    return user


class ManageFlowsApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        )
        self.regular = User.objects.create_user(
            username="user", email="user@blackcapitaltechnology.com"
        )
        make_default_flow()

    def test_anonymous_get_flows_401(self):
        response = self.client.get("/api/onboarding/manage/flows")
        self.assertEqual(response.status_code, 401)

    def test_regular_user_get_flows_403(self):
        self.client.force_login(self.regular)
        response = self.client.get("/api/onboarding/manage/flows")
        self.assertEqual(response.status_code, 403)

    def test_manager_list_flows(self):
        self.client.force_login(self.manager)
        response = self.client.get("/api/onboarding/manage/flows")
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["results"]), 1)

    def test_manager_create_flow_and_step(self):
        self.client.force_login(self.manager)
        create_resp = self.client.post(
            "/api/onboarding/manage/flows",
            data=json.dumps(
                {
                    "slug": "hr-flow",
                    "name": "HR Flow",
                    "description": "Test",
                    "is_default": False,
                    "is_active": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_resp.status_code, 201)
        self.assertEqual(create_resp.json()["slug"], "hr-flow")

        step_resp = self.client.post(
            "/api/onboarding/manage/flows/hr-flow/steps",
            data=json.dumps(
                {
                    "order": 1,
                    "component_type": "checkbox",
                    "title": "Badge photo",
                    "description": "",
                    "is_required": True,
                    "config": {"label": "Done?"},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(step_resp.status_code, 201)
        self.assertEqual(len(step_resp.json()["steps"]), 1)

    def test_invalid_step_config_400(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            "/api/onboarding/manage/flows/default/steps",
            data=json.dumps(
                {
                    "order": 10,
                    "component_type": "checkbox",
                    "title": "Bad",
                    "description": "",
                    "is_required": True,
                    "config": {},
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_reorder_steps(self):
        self.client.force_login(self.manager)
        flow = OnboardingFlow.objects.get(slug="default")
        ids = list(flow.steps.order_by("order").values_list("id", flat=True))
        reversed_ids = list(reversed(ids))
        response = self.client.put(
            "/api/onboarding/manage/flows/default/steps/reorder",
            data=json.dumps({"step_ids": reversed_ids}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        orders = [s["order"] for s in response.json()["steps"]]
        self.assertEqual(sorted(orders), [1, 2, 3])

    def test_delete_step_in_use_409(self):
        flow = make_default_flow("in-use")
        assignment, _ = create_employee_with_flow(
            data={
                "erp_employee_id": "E99",
                "email": "onboard@blackcapitaltechnology.com",
                "flow_slug": "in-use",
            }
        )
        step = assignment.flow.steps.first()
        self.assertTrue(StepProgress.objects.filter(step=step).exists())

        self.client.force_login(self.manager)
        response = self.client.delete(
            f"/api/onboarding/manage/flows/in-use/steps/{step.id}"
        )
        self.assertEqual(response.status_code, 409)

    def test_delete_flow_with_assignment_soft_deactivates(self):
        flow = make_default_flow("assigned")
        create_employee_with_flow(
            data={
                "erp_employee_id": "E88",
                "email": "a2@blackcapitaltechnology.com",
                "flow_slug": "assigned",
            }
        )
        self.assertTrue(OnboardingAssignment.objects.filter(flow__slug="assigned").exists())

        self.client.force_login(self.manager)
        response = self.client.delete("/api/onboarding/manage/flows/assigned")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["deactivated"])
        self.assertFalse(body["deleted"])
        flow.refresh_from_db()
        self.assertFalse(flow.is_active)

    def test_delete_flow_without_assignment_hard_deletes(self):
        self.client.force_login(self.manager)
        self.client.post(
            "/api/onboarding/manage/flows",
            data=json.dumps(
                {
                    "slug": "temp-flow",
                    "name": "Temp",
                    "description": "",
                    "is_default": False,
                    "is_active": True,
                }
            ),
            content_type="application/json",
        )
        response = self.client.delete("/api/onboarding/manage/flows/temp-flow")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(OnboardingFlow.objects.filter(slug="temp-flow").exists())

    def test_component_types_list(self):
        self.client.force_login(self.manager)
        response = self.client.get("/api/onboarding/manage/component-types")
        self.assertEqual(response.status_code, 200)
        types = {r["type_id"] for r in response.json()["results"]}
        self.assertIn("info_link", types)
        self.assertIn("calendar_meeting", types)
