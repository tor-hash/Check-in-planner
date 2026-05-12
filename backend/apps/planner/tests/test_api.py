from django.contrib.auth.models import Group, User
from django.test import Client, TestCase
from django.urls import reverse


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
