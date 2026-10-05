import json

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse

from apps.planner.tests.factories import ManagerFactory, UserFactory


class PlannerApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tester", email="tester@blackcapitaltechnology.com", password="x")

    def test_app_requires_login(self):
        response = self.client.get(reverse("planner:app"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_state_get_authenticated(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("people", body)
        self.assertIn("bookings", body)
        self.assertIsInstance(body["bookings"], list)
        self.assertIn("_meta", body)

    def test_state_put_requires_manager_role(self):
        self.client.force_login(self.user)
        payload = {
            "people": [],
            "mgrs": [],
            "teams": {"team-1": [], "team-2": [], "team-3": [], "pool": []},
            "startDate": "2026-01-05",
            "customDates": {},
            "workHours": {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True},
            "projects": [],
            "journal": {},
            "fnTags": [],
        }
        response = self.client.put("/api/state/update", data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_state_put_with_manager_role(self):
        manager_group, _ = Group.objects.get_or_create(name="manager")
        self.user.groups.add(manager_group)
        self.client.force_login(self.user)
        payload = {
            "people": [],
            "mgrs": [],
            "teams": {"team-1": [], "team-2": [], "team-3": [], "pool": []},
            "startDate": "2026-01-05",
            "customDates": {},
            "workHours": {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True},
            "projects": [],
            "journal": {},
            "fnTags": [],
        }
        response = self.client.put("/api/state/update", data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 200)


class ManagerSettingsApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.mgr_a = ManagerFactory(legacy_id="mgr-a")
        self.mgr_b = ManagerFactory(legacy_id="mgr-b")
        self.user_a = UserFactory(manager_role=True)
        self.mgr_a.user = self.user_a
        self.mgr_a.save(update_fields=["user"])
        self.url_a = f"/api/managers/{self.mgr_a.legacy_id}/settings"
        self.url_b = f"/api/managers/{self.mgr_b.legacy_id}/settings"

    def test_get_requires_manager_or_admin(self):
        plain_user = User.objects.create_user(username="plain", email="plain@blackcapitaltechnology.com")
        self.client.force_login(plain_user)
        response = self.client.get(self.url_a)
        self.assertEqual(response.status_code, 403)

    def test_defaults_match_new_settings(self):
        self.client.force_login(self.user_a)
        response = self.client.get(self.url_a)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["preferredMeetingDurationMinutes"], 15)
        self.assertEqual(body["maxAutoBookingsPerDay"], 2)
        self.assertEqual(body["bookingGapMinutes"], 30)
        self.assertEqual(body["autoBookingPeriodsAhead"], 2)

    def test_manager_can_update_periods_ahead(self):
        self.client.force_login(self.user_a)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"autoBookingPeriodsAhead": 4}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.auto_booking_periods_ahead, 4)

    def test_periods_ahead_out_of_range_rejected(self):
        self.client.force_login(self.user_a)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"autoBookingPeriodsAhead": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"autoBookingPeriodsAhead": 13}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_manager_can_update_own_limits(self):
        self.client.force_login(self.user_a)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"maxAutoBookingsPerDay": 4, "bookingGapMinutes": 15}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.max_auto_bookings_per_day, 4)
        self.assertEqual(self.mgr_a.booking_gap_minutes, 15)

    def test_manager_cannot_update_another_managers_settings(self):
        self.client.force_login(self.user_a)
        response = self.client.put(
            self.url_b,
            data=json.dumps({"maxAutoBookingsPerDay": 5}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_super_admin_can_update_another_managers_settings(self):
        admin_group, _ = Group.objects.get_or_create(name="admin")
        super_admin = UserFactory()
        super_admin.groups.add(admin_group)
        self.client.force_login(super_admin)
        response = self.client.put(
            self.url_b,
            data=json.dumps({"maxAutoBookingsPerDay": 6, "bookingGapMinutes": 10}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_b.max_auto_bookings_per_day, 6)
        self.assertEqual(self.mgr_b.booking_gap_minutes, 10)

    def test_max_bookings_per_day_out_of_range_rejected(self):
        self.client.force_login(self.user_a)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"maxAutoBookingsPerDay": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"maxAutoBookingsPerDay": 11}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_booking_gap_minutes_out_of_range_rejected(self):
        self.client.force_login(self.user_a)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"bookingGapMinutes": -5}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            self.url_a,
            data=json.dumps({"bookingGapMinutes": 121}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_managers_directory_includes_names(self):
        self.client.force_login(self.user_a)
        response = self.client.get("/api/managers")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("managers", body)
        ids = {m["id"] for m in body["managers"]}
        self.assertIn(self.mgr_a.legacy_id, ids)
        self.assertIn(self.mgr_b.legacy_id, ids)


class PlannerConfigStateApiTests(TestCase):
    """``PlannerConfig.auto_booking_allow_same_day`` -- the org-wide toggle
    for whether the auto-booking job may pick a same-day slot -- round
    trips through GET/PUT /api/state like the other global settings
    (workHours, weeksPerSession, ...)."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="cfg-tester", email="cfg-tester@blackcapitaltechnology.com")
        manager_group, _ = Group.objects.get_or_create(name="manager")
        self.user.groups.add(manager_group)

    def test_state_defaults_to_false(self):
        self.client.force_login(self.user)
        response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["autoBookingAllowSameDay"])

    def test_manager_can_update_it(self):
        self.client.force_login(self.user)
        payload = {
            "people": [],
            "mgrs": [],
            "teams": {"team-1": [], "team-2": [], "team-3": [], "pool": []},
            "startDate": "2026-01-05",
            "customDates": {},
            "workHours": {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True},
            "projects": [],
            "journal": {},
            "fnTags": [],
            "autoBookingAllowSameDay": True,
        }
        response = self.client.put("/api/state/update", data=payload, content_type="application/json")
        self.assertEqual(response.status_code, 200)

        from apps.planner.models import PlannerConfig
        self.assertTrue(PlannerConfig.singleton().auto_booking_allow_same_day)

        response = self.client.get("/api/state")
        self.assertTrue(response.json()["autoBookingAllowSameDay"])
