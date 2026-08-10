"""Manager session API for onboarding employee CRUD (profile only — no flow)."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from apps.onboarding.models import OnboardingAssignment, OnboardingFlow, OnboardingProfile
from apps.onboarding.services import attach_flow, create_employee
from apps.onboarding.tests.factories import make_default_flow

User = get_user_model()


def _as_manager(user: User) -> User:
    group, _ = Group.objects.get_or_create(name="manager")
    user.groups.add(group)
    return user


class ManageEmployeesApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        )
        self.regular = User.objects.create_user(
            username="user", email="user@blackcapitaltechnology.com"
        )
        make_default_flow()
        self.alt_flow = OnboardingFlow.objects.create(
            slug="hr-only",
            name="HR only",
            description="",
            is_default=False,
            is_active=True,
        )

    def test_anonymous_list_employees_401(self):
        response = self.client.get("/api/onboarding/manage/employees")
        self.assertEqual(response.status_code, 401)

    def test_regular_user_list_employees_403(self):
        self.client.force_login(self.regular)
        response = self.client.get("/api/onboarding/manage/employees")
        self.assertEqual(response.status_code, 403)

    def test_manager_create_list_get_update_delete(self):
        self.client.force_login(self.manager)

        create_resp = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(
                {
                    "erp_employee_id": "E9001",
                    "email": "new.hire@blackcapitaltechnology.com",
                    "first_name": "New",
                    "last_name": "Hire",
                    "position": "Analyst",
                    "department": "Ops",
                    "start_date": "2026-07-01",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_resp.status_code, 201)
        body = create_resp.json()
        self.assertEqual(body["erp_employee_id"], "E9001")
        # Creating an employee never attaches a flow.
        self.assertIsNone(body["flow"])
        self.assertEqual(body["status"], "no_flow")

        list_resp = self.client.get("/api/onboarding/manage/employees")
        self.assertEqual(list_resp.status_code, 200)
        ids = [r["erp_employee_id"] for r in list_resp.json()["results"]]
        self.assertIn("E9001", ids)

        get_resp = self.client.get("/api/onboarding/manage/employees/E9001")
        self.assertEqual(get_resp.status_code, 200)
        self.assertEqual(get_resp.json()["email"], "new.hire@blackcapitaltechnology.com")

        patch_resp = self.client.patch(
            "/api/onboarding/manage/employees/E9001",
            data=json.dumps({"position": "Senior Analyst"}),
            content_type="application/json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertEqual(patch_resp.json()["position"], "Senior Analyst")

        del_resp = self.client.delete("/api/onboarding/manage/employees/E9001")
        self.assertEqual(del_resp.status_code, 200)
        self.assertFalse(OnboardingProfile.objects.filter(erp_employee_id="E9001").exists())

    def test_create_rejects_flow_slug_400(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(
                {
                    "erp_employee_id": "E9002",
                    "email": "x@blackcapitaltechnology.com",
                    "flow_slug": "default",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("flow_slug", response.json()["detail"])

    def test_update_rejects_flow_slug_400(self):
        self.client.force_login(self.manager)
        create_employee(data={"erp_employee_id": "E9005", "email": "x@blackcapitaltechnology.com"})
        response = self.client.patch(
            "/api/onboarding/manage/employees/E9005",
            data=json.dumps({"flow_slug": "hr-only"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("flow_slug", response.json()["detail"])

    def test_get_unknown_employee_404(self):
        self.client.force_login(self.manager)
        response = self.client.get("/api/onboarding/manage/employees/NOPE")
        self.assertEqual(response.status_code, 404)

    def test_delete_active_user_400(self):
        profile, _ = create_employee(
            data={"erp_employee_id": "E9003", "email": "active@blackcapitaltechnology.com"}
        )
        profile.user.is_active = True
        profile.user.save(update_fields=["is_active"])

        self.client.force_login(self.manager)
        response = self.client.delete("/api/onboarding/manage/employees/E9003")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(OnboardingProfile.objects.filter(erp_employee_id="E9003").exists())

    def test_create_idempotent_returns_200(self):
        self.client.force_login(self.manager)
        payload = {"erp_employee_id": "E9004", "email": "dup@blackcapitaltechnology.com"}
        first = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            OnboardingProfile.objects.filter(erp_employee_id="E9004").count(), 1
        )

    def test_list_includes_employees_with_and_without_a_flow(self):
        self.client.force_login(self.manager)
        profile, _ = create_employee(
            data={"erp_employee_id": "E9006", "email": "attached@blackcapitaltechnology.com"}
        )
        attach_flow(profile=profile, flow=self.alt_flow, requested_by=self.manager)
        create_employee(
            data={"erp_employee_id": "E9007", "email": "bare@blackcapitaltechnology.com"}
        )

        response = self.client.get("/api/onboarding/manage/employees")
        self.assertEqual(response.status_code, 200)
        by_id = {r["erp_employee_id"]: r for r in response.json()["results"]}
        self.assertEqual(by_id["E9006"]["flow"]["slug"], "hr-only")
        self.assertIsNone(by_id["E9007"]["flow"])
        self.assertEqual(by_id["E9007"]["status"], "no_flow")
