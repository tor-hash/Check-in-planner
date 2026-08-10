"""API-level tests for the flow-attach automation wired into assign_flow.

Verifies: a new assignment sends the welcome email once and attempts
booking; assigned_by gets recorded; re-attaching (or the manual retry
endpoint) does not resend the email but does retry booking; and none of
this requires the person to have a team (unlike the check-in planner's own
auto-booking, which this deliberately does not touch).
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase

from apps.onboarding.calendar_booking import BookingRunResult, StepBookingResult
from apps.onboarding.models import FlowStep, OnboardingAssignment, OnboardingFlow, OnboardingProfile
from apps.planner.tests.factories import PersonFactory

User = get_user_model()


def _as_manager(user: User) -> User:
    group, _ = Group.objects.get_or_create(name="manager")
    user.groups.add(group)
    return user


def _connect_google(user: User) -> User:
    """Give ``user`` a fake Google connection.

    Needed for the ``assign_flow`` pre-flight check
    (``has_google_credentials``) to pass — every test in this file exercises
    that endpoint, so every manager here needs one unless the test is
    specifically checking the "not connected" block.
    """
    from social_django.models import UserSocialAuth

    UserSocialAuth.objects.create(
        user=user,
        provider="google-oauth2",
        uid=f"google-uid-{user.pk}",
        extra_data={"refresh_token": "fake-refresh-token", "access_token": "fake-access-token"},
    )
    return user


def _empty_booking_result() -> BookingRunResult:
    return BookingRunResult()


def _one_booked_result() -> BookingRunResult:
    result = BookingRunResult()
    result.booked.append(
        StepBookingResult(
            step_id=1, step_order=2, step_title="1:1 with manager",
            organizer_email="mgr@blackcapitaltechnology.com", success=True,
            google_html_link="http://cal/evt-1",
        )
    )
    return result


class AssignFlowAutomationApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.manager = _connect_google(
            _as_manager(
                User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
            )
        )
        self.flow = OnboardingFlow.objects.create(slug="mtg-flow", name="Meeting flow", is_active=True)
        FlowStep.objects.create(
            flow=self.flow, order=1, component_type="checkbox", title="Say hi", config={"label": "Said hi?"},
        )
        FlowStep.objects.create(
            flow=self.flow, order=2, component_type="calendar_meeting", title="1:1 with manager",
            config={"with_email": "assigning_manager", "duration_minutes": 30},
        )

        self.person = PersonFactory(legacy_id="alice", email="alice@example.com", name="Alice")
        emp_user = User.objects.create_user(
            username="alice-emp", email="alice.emp@blackcapitaltechnology.com", is_active=False
        )
        self.profile = OnboardingProfile.objects.create(user=emp_user, erp_employee_id="alice")
        self.person.onboarding_profile = self.profile
        self.person.save(update_fields=["onboarding_profile"])

        self.client.force_login(self.manager)

    def _assign(self, *, buddy_name=None, buddy_email=None):
        body = {"flow_slug": self.flow.slug}
        if buddy_name is not None:
            body["buddy_name"] = buddy_name
        if buddy_email is not None:
            body["buddy_email"] = buddy_email
        return self.client.post(
            "/api/onboarding/manage/employees/alice/assign-flow",
            data=json.dumps(body),
            content_type="application/json",
        )

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    @patch("apps.onboarding.welcome_email.send_onboarding_welcome_email")
    def test_new_assignment_sets_assigned_by_sends_email_and_books(self, mock_email, mock_book):
        mock_book.return_value = _one_booked_result()

        response = self._assign()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()

        mock_email.assert_called_once()
        mock_book.assert_called_once()

        self.assertEqual(body["automation"]["welcomeEmail"], {"sent": True})
        self.assertEqual(len(body["automation"]["meetings"]["booked"]), 1)
        # No SLACK_BOT_TOKEN in test settings -> reported, not an error.
        self.assertEqual(body["automation"]["slackInvite"], {"sent": False, "reason": "not_configured"})

        assignment = OnboardingAssignment.objects.get(profile=self.profile)
        self.assertEqual(assignment.assigned_by_id, self.manager.id)

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    @patch("apps.onboarding.welcome_email.send_onboarding_welcome_email")
    def test_reattach_does_not_resend_email_but_retries_booking(self, mock_email, mock_book):
        mock_book.return_value = _empty_booking_result()

        first = self._assign()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(mock_email.call_count, 1)
        self.assertEqual(mock_book.call_count, 1)

        second = self._assign()
        self.assertEqual(second.status_code, 200, second.content)
        body = second.json()
        # No resend -- welcomeEmail is not set at all on the replay path.
        self.assertIsNone(body["automation"]["welcomeEmail"])
        # But booking is retried.
        self.assertEqual(mock_email.call_count, 1)
        self.assertEqual(mock_book.call_count, 2)

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    @patch("apps.onboarding.welcome_email.send_onboarding_welcome_email")
    def test_welcome_email_failure_does_not_block_assignment_or_booking(self, mock_email, mock_book):
        mock_email.side_effect = Exception("gmail down")
        mock_book.return_value = _one_booked_result()

        response = self._assign()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["automation"]["welcomeEmail"]["sent"], False)
        self.assertIn("gmail down", body["automation"]["welcomeEmail"]["error"])
        # Booking still ran despite the email failure.
        mock_book.assert_called_once()
        self.assertTrue(OnboardingAssignment.objects.filter(profile=self.profile).exists())

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    def test_book_calendar_meetings_endpoint_does_not_require_a_team(self, mock_book):
        """The manual retry button must not resurrect the old team guard."""
        mock_book.return_value = _one_booked_result()
        # No TeamMembership is created for self.person anywhere in this test.
        response = self.client.post(
            "/api/onboarding/manage/employees/alice/book-calendar-meetings"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["booked"]), 1)

    def test_missing_employee_email_blocks_attach(self):
        """A hard block, before anything is created — not a best-effort warning."""
        self.person.email = ""
        self.person.save(update_fields=["email"])

        response = self._assign()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("email", response.json()["detail"].lower())
        self.assertFalse(OnboardingAssignment.objects.filter(profile=self.profile).exists())

    def test_manager_without_google_blocks_attach(self):
        """A hard block, before anything is created."""
        from social_django.models import UserSocialAuth

        UserSocialAuth.objects.filter(user=self.manager).delete()

        response = self._assign()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("google", response.json()["detail"].lower())
        self.assertFalse(OnboardingAssignment.objects.filter(profile=self.profile).exists())

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    @patch("apps.onboarding.welcome_email.send_onboarding_welcome_email")
    @patch("apps.onboarding.slack_invite.send_onboarding_slack_invite")
    def test_slack_invite_runs_on_new_assignment_and_failure_does_not_block(
        self, mock_slack, mock_email, mock_book
    ):
        from apps.onboarding.slack_invite import SlackInviteResult

        mock_book.return_value = _empty_booking_result()
        mock_slack.side_effect = Exception("slack API down")

        response = self._assign()
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["automation"]["slackInvite"]["sent"], False)
        self.assertEqual(body["automation"]["slackInvite"]["reason"], "error")
        self.assertIn("slack API down", body["automation"]["slackInvite"]["error"])
        self.assertTrue(OnboardingAssignment.objects.filter(profile=self.profile).exists())

        mock_slack.reset_mock(side_effect=True)
        mock_slack.side_effect = None
        mock_slack.return_value = SlackInviteResult(sent=True, slack_user_id="U123", channels_joined=["C1"])
        # Re-attach: doesn't re-run since it's not a "new" assignment.
        second = self._assign()
        self.assertIsNone(second.json()["automation"]["slackInvite"])

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    @patch("apps.onboarding.welcome_email.send_onboarding_welcome_email")
    def test_buddy_fields_are_stored_on_first_attach(self, mock_email, mock_book):
        mock_book.return_value = _empty_booking_result()

        response = self._assign(buddy_name="Rasmus", buddy_email="rasmus@blackcapitaltechnology.com")
        self.assertEqual(response.status_code, 201, response.content)

        assignment = OnboardingAssignment.objects.get(profile=self.profile)
        self.assertEqual(assignment.buddy_name, "Rasmus")
        self.assertEqual(assignment.buddy_email, "rasmus@blackcapitaltechnology.com")
        self.assertEqual(response.json()["buddy_name"], "Rasmus")

    def test_invalid_buddy_email_blocks_attach(self):
        response = self._assign(buddy_name="Rasmus", buddy_email="not-an-email")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(OnboardingAssignment.objects.filter(profile=self.profile).exists())

    @patch("apps.onboarding.calendar_booking.book_onboarding_calendar_meetings")
    @patch("apps.onboarding.welcome_email._send_gmail")
    def test_welcome_email_end_to_end_renders_buddy_name_into_real_send(self, mock_send_gmail, mock_book):
        """Full path (no mocking welcome_email itself): assign-flow -> render
        the resolved template with the real merge context -> _send_gmail.
        Confirms the rendering wiring in welcome_email.py is actually
        connected to assign_flow, not just unit-tested in isolation.
        """
        mock_book.return_value = _empty_booking_result()

        response = self._assign(buddy_name="Rasmus")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["automation"]["welcomeEmail"], {"sent": True})

        mock_send_gmail.assert_called_once()
        kwargs = mock_send_gmail.call_args.kwargs
        self.assertIn("Alice", kwargs["subject"])
        self.assertIn("Rasmus", kwargs["html"])
        self.assertIn("Alice", kwargs["plain_text"])
