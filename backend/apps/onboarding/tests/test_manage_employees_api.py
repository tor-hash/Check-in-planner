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

    def test_create_with_no_prior_roster_entry_creates_a_person(self):
        """"+ Ny medarbejder" with nobody matching in the planner roster yet.

        Regression test: previously ``_link_person_if_unlinked`` only ever
        linked an *existing* unlinked Person, so an employee created from
        scratch here (no prior check-in-planner entry) got no Person at
        all — invisible in every Person-backed view, and a same-request
        attempt to set their leder/buddy via ``PATCH .../people/<id>/roles``
        404'd with "Person not found" (exactly what a manager hit setting
        leder/buddy right after using "+ Ny medarbejder").
        """
        self.client.force_login(self.manager)
        create_resp = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(
                {
                    "erp_employee_id": "E9008",
                    "email": "brand.new@blackcapitaltechnology.com",
                    "first_name": "Brand",
                    "last_name": "New",
                    "position": "Tester",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_resp.status_code, 201)

        from apps.planner.models import Person

        person = Person.objects.filter(legacy_id="E9008").first()
        self.assertIsNotNone(person)
        self.assertEqual(person.name, "Brand New")
        self.assertEqual(person.email, "brand.new@blackcapitaltechnology.com")
        self.assertEqual(person.title, "Tester")

        people_resp = self.client.get("/api/onboarding/manage/people")
        self.assertIn("E9008", [p["legacy_id"] for p in people_resp.json()["results"]])

        leder = Person.objects.create(legacy_id="leder-e9008", name="Leder Person")
        roles_resp = self.client.patch(
            "/api/onboarding/manage/people/E9008/roles",
            data=json.dumps({"leder_id": "leder-e9008"}),
            content_type="application/json",
        )
        self.assertEqual(roles_resp.status_code, 200)
        self.assertEqual(roles_resp.json()["leder_id"], "leder-e9008")

    def test_orphaned_profile_gets_backfilled_a_person_on_replay_or_update(self):
        """A profile created before a Person-backfill existed isn't stuck orphaned.

        Simulates the exact situation a manager could hit live: an
        ``OnboardingProfile`` that already exists with no linked ``Person``
        (e.g. from before this backfill was deployed). Both re-POSTing the
        same create payload (the idempotent-replay path) and PATCHing the
        employee (the ordinary "Gem" on an existing employee) must each
        backfill the missing ``Person`` rather than silently doing nothing.
        """
        from apps.planner.models import Person

        from apps.onboarding.models import OnboardingProfile as Profile

        user = User.objects.create_user(
            username="E9009", email="orphan@blackcapitaltechnology.com"
        )
        Profile.objects.create(
            user=user, erp_employee_id="E9009", first_name="Orphan", last_name="Case"
        )
        self.assertFalse(Person.objects.filter(legacy_id="E9009").exists())

        self.client.force_login(self.manager)

        # Idempotent replay of the create call.
        replay_resp = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(
                {"erp_employee_id": "E9009", "email": "orphan@blackcapitaltechnology.com"}
            ),
            content_type="application/json",
        )
        self.assertEqual(replay_resp.status_code, 200)
        self.assertTrue(Person.objects.filter(legacy_id="E9009").exists())

        # Clear it again and verify the ordinary update path backfills it too.
        Person.objects.filter(legacy_id="E9009").delete()
        patch_resp = self.client.patch(
            "/api/onboarding/manage/employees/E9009",
            data=json.dumps({"position": "Backfilled"}),
            content_type="application/json",
        )
        self.assertEqual(patch_resp.status_code, 200)
        self.assertTrue(Person.objects.filter(legacy_id="E9009").exists())

    def test_editing_email_after_the_initial_link_updates_the_linked_person(self):
        """Editing "E-mail" (or name/position) on an already-linked employee
        must propagate to the linked Person — not just the Django User.

        Regression test: a manager created a test employee with a
        throwaway placeholder address, onboarding auto-linked/created a
        Person from it, and *then* the manager corrected the address via
        "Gem" on the employee editor. The form looked like it updated the
        employee's email everywhere, but welcome-email sending and
        calendar-meeting booking both read the recipient/attendee address
        straight off Person.email (see welcome_email.py / calendar_booking.py)
        — which silently kept the original placeholder forever, because
        ``_link_person_if_unlinked`` only ever creates a Person the first
        time, never updates an already-linked one. Automation kept firing
        "successfully" against the stale address with no visible error.
        """
        self.client.force_login(self.manager)
        create_resp = self.client.post(
            "/api/onboarding/manage/employees",
            data=json.dumps(
                {
                    "erp_employee_id": "E9010",
                    "email": "placeholder@test.dk",
                    "first_name": "Test",
                    "last_name": "Testersen",
                    "position": "Tester",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(create_resp.status_code, 201)

        from apps.planner.models import Person

        person = Person.objects.get(legacy_id="E9010")
        self.assertEqual(person.email, "placeholder@test.dk")

        patch_resp = self.client.patch(
            "/api/onboarding/manage/employees/E9010",
            data=json.dumps(
                {
                    "email": "real.address@blackcapitaltechnology.com",
                    "first_name": "Testina",
                    "position": "Senior Tester",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(patch_resp.status_code, 200)

        person.refresh_from_db()
        self.assertEqual(person.email, "real.address@blackcapitaltechnology.com")
        self.assertEqual(person.name, "Testina Testersen")
        self.assertEqual(person.title, "Senior Tester")


class PersonRolesApiTests(TestCase):
    """PATCH /api/onboarding/manage/people/<legacy_id>/roles"""

    def setUp(self):
        from apps.planner.tests.factories import PersonFactory

        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(username="mgr-roles", email="mgr-roles@blackcapitaltechnology.com")
        )
        self.client.force_login(self.manager)
        self.alice = PersonFactory(legacy_id="alice-r", name="Alice")
        self.leder = PersonFactory(legacy_id="leder-r", name="Lena Leder")
        self.buddy = PersonFactory(legacy_id="buddy-r", name="Rasmus Buddy")

    def test_sets_leder_and_buddy(self):
        response = self.client.patch(
            "/api/onboarding/manage/people/alice-r/roles",
            data=json.dumps({"leder_id": "leder-r", "buddy_id": "buddy-r"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["leder_id"], "leder-r")
        self.assertEqual(body["leder_name"], "Lena Leder")
        self.assertEqual(body["buddy_id"], "buddy-r")

        self.alice.refresh_from_db()
        self.assertEqual(self.alice.leder_id, self.leder.id)
        self.assertEqual(self.alice.buddy_id, self.buddy.id)

    def test_clears_with_null(self):
        self.alice.leder = self.leder
        self.alice.save(update_fields=["leder"])

        response = self.client.patch(
            "/api/onboarding/manage/people/alice-r/roles",
            data=json.dumps({"leder_id": None}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.alice.refresh_from_db()
        self.assertIsNone(self.alice.leder_id)

    def test_cannot_reference_self(self):
        response = self.client.patch(
            "/api/onboarding/manage/people/alice-r/roles",
            data=json.dumps({"leder_id": "alice-r"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_unknown_person_404(self):
        response = self.client.patch(
            "/api/onboarding/manage/people/does-not-exist/roles",
            data=json.dumps({"leder_id": "leder-r"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_requires_manager(self):
        self.client.logout()
        non_mgr = User.objects.create_user(
            username="reader-r", email="reader-r@blackcapitaltechnology.com"
        )
        self.client.force_login(non_mgr)
        response = self.client.patch(
            "/api/onboarding/manage/people/alice-r/roles",
            data=json.dumps({"leder_id": "leder-r"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
