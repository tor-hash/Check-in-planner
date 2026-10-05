"""Manager session API for the "Velkomstmail" tab: the template library."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from apps.onboarding.models import FlowStep, OnboardingFlow, WelcomeEmailTemplate
from apps.planner.tests.factories import PersonFactory

User = get_user_model()

BASE = "/api/onboarding/manage/welcome-emails"


def _as_manager(user: User) -> User:
    group, _ = Group.objects.get_or_create(name="manager")
    user.groups.add(group)
    return user


def _payload(**overrides):
    body = {
        "name": "Dansk standard",
        "language": "da",
        "subject": "Velkommen {{ employee_first_name }}",
        "html_body": "<p>Hej {{ employee_first_name }}</p>",
        "is_default": False,
    }
    body.update(overrides)
    return json.dumps(body)


class WelcomeEmailLibraryApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        )
        self.regular = User.objects.create_user(
            username="user", email="user@blackcapitaltechnology.com"
        )

    def test_anonymous_401_and_regular_403(self):
        self.assertEqual(self.client.get(BASE).status_code, 401)
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(BASE).status_code, 403)

    def test_empty_list_includes_starter(self):
        self.client.force_login(self.manager)
        body = self.client.get(BASE).json()
        self.assertEqual(body["results"], [])
        self.assertIn("{{ employee_first_name }}", body["starter"]["html_body"])

    def test_create_update_delete(self):
        self.client.force_login(self.manager)
        created = self.client.post(BASE, data=_payload(), content_type="application/json")
        self.assertEqual(created.status_code, 201, created.content)
        tid = created.json()["id"]
        self.assertEqual(created.json()["language"], "da")

        updated = self.client.put(
            f"{BASE}/{tid}", data=_payload(name="Norsk", language="no"),
            content_type="application/json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(WelcomeEmailTemplate.objects.get(pk=tid).language, "no")

        self.assertEqual(self.client.delete(f"{BASE}/{tid}").status_code, 200)
        self.assertFalse(WelcomeEmailTemplate.objects.exists())
        self.assertEqual(self.client.get(f"{BASE}/{tid}").status_code, 404)

    def test_default_is_per_language(self):
        self.client.force_login(self.manager)
        a = self.client.post(BASE, data=_payload(is_default=True), content_type="application/json").json()
        n = self.client.post(
            BASE, data=_payload(language="no", is_default=True), content_type="application/json"
        ).json()
        b = self.client.post(BASE, data=_payload(is_default=True), content_type="application/json").json()
        defaults = set(WelcomeEmailTemplate.objects.filter(is_default=True).values_list("pk", flat=True))
        self.assertEqual(defaults, {n["id"], b["id"]})
        self.assertNotIn(a["id"], defaults)

    def test_rejects_bad_syntax_missing_fields_and_bad_language(self):
        self.client.force_login(self.manager)
        for body in (
            _payload(html_body="{% if %}"),
            _payload(name=""),
            _payload(subject=""),
            _payload(language="sv"),
        ):
            r = self.client.post(BASE, data=body, content_type="application/json")
            self.assertEqual(r.status_code, 400, body)
        self.assertFalse(WelcomeEmailTemplate.objects.exists())


class WelcomeEmailPreviewApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _as_manager(
            User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        )
        self.flow = OnboardingFlow.objects.create(
            slug="f1", name="Flow One", is_active=True, is_default=True
        )
        FlowStep.objects.create(
            flow=self.flow, order=1, component_type="checkbox", title="Læs håndbogen",
            title_no="Les håndboken", config={"label": "Done?"},
        )
        self.client.force_login(self.manager)

    def _post(self, body=None):
        return self.client.post(
            f"{BASE}/preview",
            data=json.dumps(body) if body is not None else None,
            content_type="application/json",
        )

    def test_no_body_uses_sample_data_and_starter(self):
        r = self._post()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["source"], "starter")
        self.assertIn("Anna", body["subject"])
        self.assertIn("Anna", body["plain"])

    def test_country_picks_language_default_and_step_text(self):
        WelcomeEmailTemplate.objects.create(
            name="DK", language="da", subject="DK", html_body="<p>DK</p>", is_default=True
        )
        no = WelcomeEmailTemplate.objects.create(
            name="NO", language="no", subject="NO",
            html_body="{% for s in todo_steps %}<p>{{ s.title }}</p>{% endfor %}", is_default=True,
        )
        body = self._post({"country": "NO"}).json()
        self.assertEqual(body["template_id"], no.pk)
        self.assertIn("Les håndboken", body["html"])

    def test_template_id_and_real_person(self):
        PersonFactory(legacy_id="alice", email="alice@example.com", name="Alice Andersen")
        t = WelcomeEmailTemplate.objects.create(
            name="X", language="da", subject="Hej {{ employee_first_name }}",
            html_body="<p>{{ buddy_name }}</p>",
        )
        body = self._post({"template_id": t.pk, "erp_id": "alice", "buddy_name": "Rasmus"}).json()
        self.assertEqual(body["subject"], "Hej Alice")
        self.assertIn("Rasmus", body["html"])

    def test_draft_content(self):
        body = self._post({"subject": "Draft", "html_body": "<p>Draft body</p>"}).json()
        self.assertEqual(body["source"], "draft")
        self.assertIn("Draft body", body["html"])

    def test_errors(self):
        self.assertEqual(self._post({"erp_id": "nope"}).status_code, 404)
        self.assertEqual(self._post({"subject": "Hej", "html_body": "{% if %}"}).status_code, 400)
        self.assertEqual(self._post({"html_body": "<p>x</p>"}).status_code, 400)
        self.assertEqual(self._post({"buddy_email": "not-an-email"}).status_code, 400)
        self.assertEqual(self._post({"country": "SE"}).status_code, 400)
        self.assertEqual(self._post({"flow_slug": "nope"}).status_code, 404)
