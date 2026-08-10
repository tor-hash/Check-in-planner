"""Unit tests for the onboarding meeting-booking engine.

Key behaviours under test:
- Organizer resolution (literal email, the ``assigning_manager`` sentinel,
  and unknown-user failure) — this replaces the old team/rotation lookup.
- A missing Google connection for one step's organizer fails only that
  step; other steps (even with a different organizer) still get booked.
- No team membership is required anywhere in this path.
"""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.onboarding.calendar_booking import (
    OrganizerResolutionError,
    _resolve_organizer,
    book_onboarding_calendar_meetings,
)
from apps.onboarding.components import CalendarMeetingComponent
from apps.onboarding.models import FlowStep, OnboardingFlow, OnboardingProfile, StepProgress
from apps.onboarding.slot_finder import OnboardingSlotResult
from apps.planner.google.credentials import GoogleCredentialsUnavailable
from apps.planner.google.events import CreatedEvent
from apps.planner.tests.factories import PersonFactory

User = get_user_model()


def _make_flow(steps: list[dict], slug: str = "mtg-flow") -> OnboardingFlow:
    flow = OnboardingFlow.objects.create(slug=slug, name="Meeting flow", is_active=True)
    for i, cfg in enumerate(steps, start=1):
        FlowStep.objects.create(
            flow=flow,
            order=i,
            component_type=cfg.get("component_type", "calendar_meeting"),
            title=cfg["title"],
            config=cfg["config"],
            is_required=True,
        )
    return flow


def _make_person_with_profile(*, legacy_id: str, manager: User | None = None) -> tuple:
    person = PersonFactory(legacy_id=legacy_id, email=f"{legacy_id}@blackcapitaltechnology.com")
    user = User.objects.create_user(
        username=legacy_id, email=f"{legacy_id}.employee@blackcapitaltechnology.com", is_active=False
    )
    profile = OnboardingProfile.objects.create(user=user, erp_employee_id=legacy_id)
    person.onboarding_profile = profile
    person.save(update_fields=["onboarding_profile"])
    return person, profile


class OrganizerResolutionTests(TestCase):
    def test_literal_email_resolves_to_matching_user(self):
        it_user = User.objects.create_user(username="it", email="it@blackcapitaltechnology.com")
        person, profile = _make_person_with_profile(legacy_id="bob")
        flow = _make_flow([{"title": "IT setup", "config": {"with_email": "it@blackcapitaltechnology.com"}}])
        assignment = profile.assignments.create(flow=flow)

        user, email = _resolve_organizer(
            step_config={"with_email": "it@blackcapitaltechnology.com"}, assignment=assignment
        )
        self.assertEqual(user, it_user)
        self.assertEqual(email, "it@blackcapitaltechnology.com")

    def test_unknown_email_raises(self):
        person, profile = _make_person_with_profile(legacy_id="carol")
        flow = _make_flow([{"title": "X", "config": {"with_email": "nobody@blackcapitaltechnology.com"}}])
        assignment = profile.assignments.create(flow=flow)

        with self.assertRaises(OrganizerResolutionError):
            _resolve_organizer(
                step_config={"with_email": "nobody@blackcapitaltechnology.com"}, assignment=assignment
            )

    def test_assigning_manager_sentinel_resolves_to_assigned_by(self):
        manager = User.objects.create_user(username="mgr", email="mgr@blackcapitaltechnology.com")
        person, profile = _make_person_with_profile(legacy_id="dave")
        flow = _make_flow(
            [{"title": "1:1", "config": {"with_email": CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL}}]
        )
        assignment = profile.assignments.create(flow=flow, assigned_by=manager)

        user, email = _resolve_organizer(
            step_config={"with_email": CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL},
            assignment=assignment,
        )
        self.assertEqual(user, manager)
        self.assertEqual(email, "mgr@blackcapitaltechnology.com")

    def test_assigning_manager_sentinel_without_assigned_by_raises(self):
        person, profile = _make_person_with_profile(legacy_id="erin")
        flow = _make_flow(
            [{"title": "1:1", "config": {"with_email": CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL}}]
        )
        assignment = profile.assignments.create(flow=flow)  # assigned_by left unset

        with self.assertRaises(OrganizerResolutionError):
            _resolve_organizer(
                step_config={"with_email": CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL},
                assignment=assignment,
            )


class BookOnboardingCalendarMeetingsTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username="mgr2", email="mgr2@blackcapitaltechnology.com")
        self.it_user = User.objects.create_user(username="it2", email="it2@blackcapitaltechnology.com")

    def test_no_profile_returns_top_level_error(self):
        person = PersonFactory(legacy_id="noprofile")
        result = book_onboarding_calendar_meetings(person)
        self.assertFalse(result.ok)
        self.assertIn("OnboardingProfile", result.error)

    def test_no_pending_meeting_steps_is_a_noop(self):
        person, profile = _make_person_with_profile(legacy_id="frank")
        flow = _make_flow([{"title": "Read", "component_type": "checkbox", "config": {"label": "Done?"}}])
        assignment = profile.assignments.create(flow=flow, assigned_by=self.manager)
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)

        result = book_onboarding_calendar_meetings(person)
        self.assertTrue(result.ok)
        self.assertEqual(result.booked, [])
        self.assertEqual(result.failed, [])

    def test_no_team_required_meeting_still_books(self):
        """The person has no TeamMembership at all -- booking must still work."""
        person, profile = _make_person_with_profile(legacy_id="grace")
        flow = _make_flow(
            [{"title": "1:1 with manager", "config": {"with_email": CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL, "duration_minutes": 30}}]
        )
        assignment = profile.assignments.create(flow=flow, assigned_by=self.manager)
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)

        with patch("apps.onboarding.slot_finder.find_organizer_slot") as mock_slot, \
             patch("apps.planner.google.events.create_checkin_event") as mock_create:
            from django.utils import timezone as dj_tz

            mock_slot.return_value = OnboardingSlotResult(
                starts_at=dj_tz.now() + dj_tz.timedelta(days=1), duration_minutes=30
            )
            mock_create.return_value = CreatedEvent(
                google_event_id="evt-1", html_link="http://cal/evt-1",
                start=dj_tz.now(), end=dj_tz.now(),
            )
            result = book_onboarding_calendar_meetings(person)

        self.assertTrue(result.ok)
        self.assertEqual(len(result.booked), 1)
        self.assertEqual(result.booked[0].organizer_email, "mgr2@blackcapitaltechnology.com")
        progress = StepProgress.objects.get(assignment=assignment)
        self.assertEqual(progress.status, StepProgress.STATUS_COMPLETED)
        self.assertEqual(progress.completion_data["google_event_id"], "evt-1")

    def test_missing_organizer_credentials_fails_only_that_step(self):
        """Two meetings, two different organizers -- one has no Google
        connection. Only that step should fail; the other still books."""
        person, profile = _make_person_with_profile(legacy_id="henry")
        flow = _make_flow(
            [
                {
                    "title": "1:1 with manager",
                    "config": {"with_email": "mgr2@blackcapitaltechnology.com", "duration_minutes": 30},
                },
                {
                    "title": "IT intro",
                    "config": {"with_email": "it2@blackcapitaltechnology.com", "duration_minutes": 30},
                },
            ]
        )
        assignment = profile.assignments.create(flow=flow, assigned_by=self.manager)
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)

        from django.utils import timezone as dj_tz

        def fake_find_slot(*, organizer_user, organizer_email, **kwargs):
            if organizer_email == "it2@blackcapitaltechnology.com":
                raise GoogleCredentialsUnavailable("IT hasn't connected Google.")
            return OnboardingSlotResult(starts_at=dj_tz.now() + dj_tz.timedelta(days=1), duration_minutes=30)

        with patch("apps.onboarding.slot_finder.find_organizer_slot", side_effect=fake_find_slot), \
             patch("apps.planner.google.events.create_checkin_event") as mock_create:
            mock_create.return_value = CreatedEvent(
                google_event_id="evt-2", html_link="http://cal/evt-2",
                start=dj_tz.now(), end=dj_tz.now(),
            )
            result = book_onboarding_calendar_meetings(person)

        self.assertTrue(result.ok)
        self.assertEqual(len(result.booked), 1)
        self.assertEqual(result.booked[0].organizer_email, "mgr2@blackcapitaltechnology.com")
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0].organizer_email, "it2@blackcapitaltechnology.com")
        self.assertIn("connect", result.failed[0].error.lower())

    def test_re_run_only_books_still_pending_steps(self):
        """Simulates the retry button / re-attach path: a step already
        completed must not be re-booked on a second run."""
        person, profile = _make_person_with_profile(legacy_id="ivy")
        flow = _make_flow(
            [{"title": "1:1", "config": {"with_email": "mgr2@blackcapitaltechnology.com", "duration_minutes": 30}}]
        )
        assignment = profile.assignments.create(flow=flow, assigned_by=self.manager)
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)

        from django.utils import timezone as dj_tz

        with patch("apps.onboarding.slot_finder.find_organizer_slot") as mock_slot, \
             patch("apps.planner.google.events.create_checkin_event") as mock_create:
            mock_slot.return_value = OnboardingSlotResult(
                starts_at=dj_tz.now() + dj_tz.timedelta(days=1), duration_minutes=30
            )
            mock_create.return_value = CreatedEvent(
                google_event_id="evt-3", html_link="http://cal/evt-3",
                start=dj_tz.now(), end=dj_tz.now(),
            )
            first = book_onboarding_calendar_meetings(person)
            second = book_onboarding_calendar_meetings(person)

        self.assertEqual(len(first.booked), 1)
        self.assertEqual(len(second.booked), 0)
        self.assertEqual(len(second.failed), 0)
        mock_create.assert_called_once()
