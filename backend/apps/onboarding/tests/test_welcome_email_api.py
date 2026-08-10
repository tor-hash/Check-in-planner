"""Manager session API for the "Velkomstmail" (welcome-email template) tab."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from apps.onboarding.models import OnboardingFlow, WelcomeEmailTemplate
from apps.planner.tests.factories import PersonFactory

User = get_user_model()


def _as_manager(user: User) -> User:
    group, _ = Group.objects.get_or_create(name="manager")
    user.groups.add(group)
    return user


class WelcomeEmailTemplateApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(
                username="mgr", email="mgr@blackcapitaltechnology.com", first_name="Mgr"
            )
        )
        self.regular = User.objects.create_user(
            username="user", email="user@blackcapitaltechnology.com"
        )
        self.flow = OnboardingFlow.objects.create(slug="f1", name="Flow One", is_active=True)
        self.flow2 = OnboardingFlow.objects.create(slug="f2", name="Flow Two", is_active=True)

    def _url(self, slug: str) -> str:
        return f"/api/onboarding/manage/flows/{slug}/welcome-email"

    def test_anonymous_401(self):
        response = self.client.get(self._url("f1"))
        self.assertEqual(response.status_code, 401)

    def test_regular_user_403(self):
        self.client.force_login(self.regular)
        response = self.client.get(self._url("f1"))
        self.assertEqual(response.status_code, 403)

    def test_get_unknown_flow_404(self):
        self.client.force_login(self.manager)
        response = self.client.get(self._url("nope"))
        self.assertEqual(response.status_code, 404)

    def test_get_with_no_template_anywhere_returns_starter(self):
        self.client.force_login(self.manager)
        response = self.client.get(self._url("f1"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["source"], "starter")
        self.assertFalse(body["has_own_template"])
        self.assertIn("{{ employee_first_name }}", body["html_body"])

    def test_put_creates_own_template(self):
        self.client.force_login(self.manager)
        response = self.client.put(
            self._url("f1"),
            data=json.dumps({"subject": "Hej {{ employee_first_name }}", "html_body": "<p>Hi</p>"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["has_own_template"])
        self.assertEqual(body["source"], "own")
        self.assertEqual(body["html_body"], "<p>Hi</p>")
        self.assertEqual(body["updated_by"], "mgr@blackcapitaltechnology.com")
        self.assertTrue(WelcomeEmailTemplate.objects.filter(flow=self.flow).exists())

    def test_put_rejects_bad_template_syntax(self):
        self.client.force_login(self.manager)
        response = self.client.put(
            self._url("f1"),
            data=json.dumps({"subject": "Hej", "html_body": "{% if %}"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(WelcomeEmailTemplate.objects.filter(flow=self.flow).exists())

    def test_put_rejects_missing_fields(self):
        self.client.force_login(self.manager)
        response = self.client.put(
            self._url("f1"), data=json.dumps({"subject": "Hej"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

    def test_put_is_default_fallback_unsets_previous_default(self):
        self.client.force_login(self.manager)
        self.client.put(
            self._url("f1"),
            data=json.dumps({"subject": "A", "html_body": "A", "is_default_fallback": True}),
            content_type="application/json",
        )
        response = self.client.put(
            self._url("f2"),
            data=json.dumps({"subject": "B", "html_body": "B", "is_default_fallback": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_default_fallback"])
        t1 = WelcomeEmailTemplate.objects.get(flow=self.flow)
        self.assertFalse(t1.is_default_fallback)

    def test_flow_without_own_template_inherits_default_fallback(self):
        self.client.force_login(self.manager)
        self.client.put(
            self._url("f1"),
            data=json.dumps({"subject": "A subject", "html_body": "<p>A body</p>", "is_default_fallback": True}),
            content_type="application/json",
        )
        response = self.client.get(self._url("f2"))
        body = response.json()
        self.assertEqual(body["source"], "fallback")
        self.assertEqual(body["fallback_flow_slug"], "f1")
        self.assertEqual(body["html_body"], "<p>A body</p>")

    def test_delete_reverts_to_starter(self):
        self.client.force_login(self.manager)
        self.client.put(
            self._url("f1"),
            data=json.dumps({"subject": "A", "html_body": "A"}),
            content_type="application/json",
        )
        response = self.client.delete(self._url("f1"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source"], "starter")
        self.assertFalse(WelcomeEmailTemplate.objects.filter(flow=self.flow).exists())

    def test_delete_without_own_template_404(self):
        self.client.force_login(self.manager)
        response = self.client.delete(self._url("f1"))
        self.assertEqual(response.status_code, 404)


class WelcomeEmailPreviewApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(
                username="mgr", email="mgr@blackcapitaltechnology.com", first_name="Mgr"
            )
        )
        self.flow = OnboardingFlow.objects.create(slug="f1", name="Flow One", is_active=True)
        self.client.force_login(self.manager)

    def _url(self, slug: str) -> str:
        return f"/api/onboarding/manage/flows/{slug}/welcome-email/preview"

    def test_preview_with_no_body_uses_sample_data_and_starter_template(self):
        response = self.client.post(self._url("f1"), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["source"], "starter")
        self.assertIn("Anna", body["subject"])
        self.assertIn("Anna", body["html"])
        self.assertIn("Anna", body["plain"])

    def test_preview_with_erp_id_uses_real_person_and_buddy_fields(self):
        PersonFactory(legacy_id="alice", email="alice@example.com", name="Alice Andersen")
        response = self.client.post(
            self._url("f1"),
            data=json.dumps({"erp_id": "alice", "buddy_name": "Rasmus"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIn("Alice", body["subject"])
        self.assertIn("Rasmus", body["html"])

    def test_preview_unknown_erp_id_404(self):
        response = self.client.post(
            self._url("f1"), data=json.dumps({"erp_id": "nope"}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)

    def test_preview_draft_content_does_not_touch_saved_template(self):
        response = self.client.post(
            self._url("f1"),
            data=json.dumps({"subject": "Draft {{ employee_first_name }}", "html_body": "<p>Draft body</p>"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertNotIn("source", body)
        self.assertIn("Draft body", body["html"])
        self.assertFalse(WelcomeEmailTemplate.objects.filter(flow=self.flow).exists())

    def test_preview_bad_draft_syntax_400(self):
        response = self.client.post(
            self._url("f1"),
            data=json.dumps({"subject": "Hej", "html_body": "{% if %}"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_preview_html_only_without_subject_400(self):
        response = self.client.post(
            self._url("f1"),
            data=json.dumps({"html_body": "<p>Only html</p>"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_preview_bad_buddy_email_400(self):
        response = self.client.post(
            self._url("f1"),
            data=json.dumps({"buddy_email": "not-an-email"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
