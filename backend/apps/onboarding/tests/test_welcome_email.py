"""Tests for the combined onboarding welcome + calendar-share email."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.onboarding.models import FlowStep, OnboardingFlow, OnboardingProfile, WelcomeEmailTemplate
from apps.onboarding.welcome_email import (
    build_merge_context,
    html_to_plain,
    render_merge_tags,
    render_welcome_email,
    resolve_welcome_email_template,
    send_onboarding_welcome_email,
    validate_template_syntax,
)
from apps.planner.google.credentials import GoogleCredentialsUnavailable
from apps.planner.models import CalendarShareRequest
from apps.planner.tests.factories import PersonFactory

User = get_user_model()


class RenderMergeTagsTests(TestCase):
    def test_substitutes_plain_values_and_escapes_html(self):
        out = render_merge_tags(
            "Hej {{ employee_first_name }}, buddy: {{ buddy_name }}",
            {"employee_first_name": "Alice", "buddy_name": "<script>bad</script>"},
        )
        self.assertIn("Hej Alice", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>bad</script>", out)

    def test_supports_conditionals_and_loops(self):
        out = render_merge_tags(
            "{% if buddy_name %}Buddy: {{ buddy_name }}{% else %}No buddy{% endif %}"
            "{% for s in todo_steps %}<li>{{ s.title }}</li>{% endfor %}",
            {"buddy_name": "", "todo_steps": [{"title": "Step A"}, {"title": "Step B"}]},
        )
        self.assertIn("No buddy", out)
        self.assertIn("<li>Step A</li><li>Step B</li>", out)

    def test_bad_syntax_raises_validation_error(self):
        with self.assertRaises(Exception):
            validate_template_syntax(subject="{% if %}", html_body="fine")


class HtmlToPlainTests(TestCase):
    def test_block_tags_become_newlines_and_blank_runs_collapse(self):
        html = "<p>Hej</p><p>Verden</p><br><br><br><div>Sidste linje</div>"
        plain = html_to_plain(html)
        self.assertIn("Hej", plain)
        self.assertIn("Verden", plain)
        self.assertIn("Sidste linje", plain)
        # No run of more than one consecutive blank line.
        self.assertNotIn("\n\n\n", plain)


class BuildMergeContextAndResolveTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="mgr", email="mgr@blackcapitaltechnology.com", first_name="Bob", last_name="Manager"
        )
        self.person = PersonFactory(legacy_id="alice", email="alice@example.com", name="Alice Andersen")
        self.flow = OnboardingFlow.objects.create(slug="f1", name="Onboarding", is_active=True)
        FlowStep.objects.create(
            flow=self.flow, order=1, component_type="checkbox", title="Photo taken",
            config={"label": "Done?"},
        )
        FlowStep.objects.create(
            flow=self.flow, order=2, component_type="calendar_meeting", title="1:1 with manager",
            config={"with_email": "assigning_manager", "duration_minutes": 30},
        )

    def test_context_splits_todo_and_meeting_steps(self):
        context = build_merge_context(
            person=self.person, flow=self.flow, requested_by=self.manager,
            buddy_name="Rasmus", buddy_email="rasmus@blackcapitaltechnology.com",
        )
        self.assertEqual(context["employee_name"], "Alice Andersen")
        self.assertEqual(context["employee_first_name"], "Alice")
        self.assertEqual(context["manager_name"], "Bob Manager")
        self.assertEqual(context["buddy_name"], "Rasmus")
        self.assertEqual([s["title"] for s in context["todo_steps"]], ["Photo taken"])
        self.assertEqual([s["title"] for s in context["meeting_steps"]], ["1:1 with manager"])

    def test_resolves_to_starter_when_nothing_configured(self):
        template, source, fallback_slug = resolve_welcome_email_template(self.flow)
        self.assertEqual(source, "starter")
        self.assertIsNone(fallback_slug)
        self.assertIn("{{ employee_first_name }}", template.html_body)

    def test_resolves_to_own_template_when_present(self):
        WelcomeEmailTemplate.objects.create(
            flow=self.flow, subject="Hej {{ employee_first_name }}", html_body="<p>Custom</p>"
        )
        template, source, fallback_slug = resolve_welcome_email_template(self.flow)
        self.assertEqual(source, "own")
        self.assertIsNone(fallback_slug)
        self.assertEqual(template.html_body, "<p>Custom</p>")

    def test_resolves_to_default_fallback_from_another_flow(self):
        other_flow = OnboardingFlow.objects.create(slug="other", name="Other", is_active=True)
        WelcomeEmailTemplate.objects.create(
            flow=other_flow, subject="Fallback subject", html_body="<p>Fallback</p>",
            is_default_fallback=True,
        )
        template, source, fallback_slug = resolve_welcome_email_template(self.flow)
        self.assertEqual(source, "fallback")
        self.assertEqual(fallback_slug, "other")
        self.assertEqual(template.html_body, "<p>Fallback</p>")

    def test_only_one_template_can_be_default_fallback(self):
        other_flow = OnboardingFlow.objects.create(slug="other2", name="Other 2", is_active=True)
        t1 = WelcomeEmailTemplate.objects.create(
            flow=self.flow, subject="A", html_body="A", is_default_fallback=True
        )
        t2 = WelcomeEmailTemplate.objects.create(
            flow=other_flow, subject="B", html_body="B", is_default_fallback=True
        )
        t1.refresh_from_db()
        self.assertFalse(t1.is_default_fallback)
        self.assertTrue(t2.is_default_fallback)

    def test_render_welcome_email_uses_resolved_template(self):
        context = build_merge_context(
            person=self.person, flow=self.flow, requested_by=self.manager, buddy_name="Rasmus"
        )
        subject, plain, html, source = render_welcome_email(flow=self.flow, context=context)
        self.assertEqual(source, "starter")
        self.assertIn("Alice", subject)
        self.assertIn("Rasmus", html)
        self.assertIn("Alice", plain)


class SendOnboardingWelcomeEmailTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="mgr", email="mgr@blackcapitaltechnology.com", first_name="Mgr"
        )
        self.person = PersonFactory(legacy_id="alice", email="alice@example.com", name="Alice")
        emp_user = User.objects.create_user(
            username="alice-emp", email="alice.emp@blackcapitaltechnology.com", is_active=False
        )
        self.profile = OnboardingProfile.objects.create(user=emp_user, erp_employee_id="alice")
        self.flow = OnboardingFlow.objects.create(slug="f2", name="Onboarding", is_active=True)
        FlowStep.objects.create(
            flow=self.flow, order=1, component_type="checkbox", title="Step 1", config={"label": "Done?"}
        )
        self.assignment = self.profile.assignments.create(flow=self.flow, assigned_by=self.manager)

    @patch("apps.onboarding.welcome_email._send_gmail")
    def test_success_records_share_request_and_marks_sent(self, mock_send):
        record = send_onboarding_welcome_email(
            person=self.person, assignment=self.assignment, requested_by=self.manager
        )
        mock_send.assert_called_once()
        self.assertTrue(record.success)
        self.assertEqual(CalendarShareRequest.objects.count(), 1)
        self.assignment.refresh_from_db()
        self.assertIsNotNone(self.assignment.welcome_email_sent_at)

    @patch("apps.onboarding.welcome_email._send_gmail", side_effect=GoogleCredentialsUnavailable("no creds"))
    def test_missing_credentials_raises_and_records_failure(self, mock_send):
        with self.assertRaises(ValidationError):
            send_onboarding_welcome_email(
                person=self.person, assignment=self.assignment, requested_by=self.manager
            )
        record = CalendarShareRequest.objects.get()
        self.assertFalse(record.success)
        self.assignment.refresh_from_db()
        self.assertIsNone(self.assignment.welcome_email_sent_at)

    def test_no_employee_email_raises_without_side_effects(self):
        self.person.email = ""
        self.person.save(update_fields=["email"])
        with self.assertRaises(ValidationError):
            send_onboarding_welcome_email(
                person=self.person, assignment=self.assignment, requested_by=self.manager
            )
        self.assertEqual(CalendarShareRequest.objects.count(), 0)
