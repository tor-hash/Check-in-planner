"""Smoke test for the /onboarding/flows/ page itself (not the JSON APIs)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

User = get_user_model()


class FlowsEditorViewTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_anonymous_redirects_to_login(self):
        response = self.client.get("/onboarding/flows/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_regular_user_redirects_to_planner_home(self):
        user = User.objects.create_user(username="user", email="user@blackcapitaltechnology.com")
        self.client.force_login(user)
        response = self.client.get("/onboarding/flows/")
        self.assertEqual(response.status_code, 302)

    def test_manager_sees_all_three_tabs_including_welcome_email(self):
        group, _ = Group.objects.get_or_create(name="manager")
        manager = User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        manager.groups.add(group)
        self.client.force_login(manager)

        response = self.client.get("/onboarding/flows/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('id="tab-flows"', content)
        self.assertIn('id="tab-employees"', content)
        self.assertIn('id="tab-welcome-email"', content)
        self.assertIn('id="welcome-email-view"', content)
        # The literal merge-tag syntax must survive Django's own template
        # rendering (it's written with {% templatetag %}, not a raw {{ }}).
        self.assertIn("{{ buddy_name }}", content)
        # Substring only, not the exact filename: ManifestStaticFilesStorage
        # (used in staging/prod) rewrites this to a hashed filename like
        # welcome-email-editor.<hash>.js.
        self.assertIn("welcome-email-editor", content)
