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
from django.test import TestCase, override_settings

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

    def test_leder_sentinel_resolves_to_snapshotted_leder_email(self):
        leder_user = User.objects.create_user(username="leder-u", email="leder@blackcapitaltechnology.com")
        person, profile = _make_person_with_profile(legacy_id="jack")
        flow = _make_flow(
            [{"title": "1:1 with leder", "config": {"with_email": CalendarMeetingComponent.LEDER_SENTINEL}}]
        )
        assignment = profile.assignments.create(
            flow=flow, leder_name="Leder Navn", leder_email="leder@blackcapitaltechnology.com"
        )

        user, email = _resolve_organizer(
            step_config={"with_email": CalendarMeetingComponent.LEDER_SENTINEL}, assignment=assignment
        )
        self.assertEqual(user, leder_user)
        self.assertEqual(email, "leder@blackcapitaltechnology.com")

    def test_blank_with_email_defaults_to_leder(self):
        leder_user = User.objects.create_user(username="leder-u2", email="leder2@blackcapitaltechnology.com")
        person, profile = _make_person_with_profile(legacy_id="karl")
        flow = _make_flow([{"title": "Unspecified role", "config": {"with_email": ""}}])
        assignment = profile.assignments.create(
            flow=flow, leder_name="Leder Two", leder_email="leder2@blackcapitaltechnology.com"
        )

        user, email = _resolve_organizer(step_config={"with_email": ""}, assignment=assignment)
        self.assertEqual(user, leder_user)
        self.assertEqual(email, "leder2@blackcapitaltechnology.com")

    def test_leder_sentinel_without_leder_on_record_raises(self):
        person, profile = _make_person_with_profile(legacy_id="liam")
        flow = _make_flow(
            [{"title": "1:1 with leder", "config": {"with_email": CalendarMeetingComponent.LEDER_SENTINEL}}]
        )
        assignment = profile.assignments.create(flow=flow)  # leder_email left unset

        with self.assertRaises(OrganizerResolutionError):
            _resolve_organizer(
                step_config={"with_email": CalendarMeetingComponent.LEDER_SENTINEL}, assignment=assignment
            )

    def test_buddy_sentinel_resolves_to_snapshotted_buddy_email(self):
        buddy_user = User.objects.create_user(username="buddy-u", email="buddy@blackcapitaltechnology.com")
        person, profile = _make_person_with_profile(legacy_id="mona")
        flow = _make_flow(
            [{"title": "Coffee with buddy", "config": {"with_email": CalendarMeetingComponent.BUDDY_SENTINEL}}]
        )
        assignment = profile.assignments.create(
            flow=flow, buddy_name="Buddy Navn", buddy_email="buddy@blackcapitaltechnology.com"
        )

        user, email = _resolve_organizer(
            step_config={"with_email": CalendarMeetingComponent.BUDDY_SENTINEL}, assignment=assignment
        )
        self.assertEqual(user, buddy_user)
        self.assertEqual(email, "buddy@blackcapitaltechnology.com")

    def test_buddy_sentinel_without_buddy_on_record_raises(self):
        person, profile = _make_person_with_profile(legacy_id="nina")
        flow = _make_flow(
            [{"title": "Coffee with buddy", "config": {"with_email": CalendarMeetingComponent.BUDDY_SENTINEL}}]
        )
        assignment = profile.assignments.create(flow=flow)  # buddy_email left unset

        with self.assertRaises(OrganizerResolutionError):
            _resolve_organizer(
                step_config={"with_email": CalendarMeetingComponent.BUDDY_SENTINEL}, assignment=assignment
            )


@override_settings(ONBOARDING_SCHEDULER_EMAIL="")
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

    def test_day_offset_anchors_search_to_business_day_after_start_date(self):
        """A step with day_offset/time_of_day must anchor the slot search
        to the employee's own start date -- shifted forward by that many
        *business* days -- not to "today", and must pass the parsed
        preferred time through. This is the mechanism behind "Week 1 · Mon
        09:00" sliding to line up with a start date that isn't a Monday.
        """
        import datetime as dt

        person, profile = _make_person_with_profile(legacy_id="ivy2")
        profile.start_date = dt.date(2026, 9, 3)  # a Thursday
        profile.save(update_fields=["start_date"])
        flow = _make_flow(
            [
                {
                    "title": "Week 1 · Tue 10:30 — Role talk",
                    "config": {
                        "with_email": "mgr2@blackcapitaltechnology.com",
                        "duration_minutes": 30,
                        "day_offset": 1,
                        "time_of_day": "10:30",
                    },
                }
            ]
        )
        assignment = profile.assignments.create(flow=flow, assigned_by=self.manager)
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)

        from django.utils import timezone as dj_tz

        with patch("apps.onboarding.slot_finder.find_organizer_slot") as mock_slot,              patch("apps.planner.google.events.create_checkin_event") as mock_create:
            mock_slot.return_value = OnboardingSlotResult(
                starts_at=dj_tz.now() + dj_tz.timedelta(days=1), duration_minutes=30
            )
            mock_create.return_value = CreatedEvent(
                google_event_id="evt-3", html_link="http://cal/evt-3",
                start=dj_tz.now(), end=dj_tz.now(),
            )
            book_onboarding_calendar_meetings(person)

        self.assertEqual(mock_slot.call_count, 1)
        _, kwargs = mock_slot.call_args
        # Start Thursday 2026-09-03, day_offset 1 (the template's Tuesday)
        # -> the next business day, Friday 2026-09-04 (no weekend to skip
        # yet at offset 1).
        self.assertEqual(kwargs["search_from"], dt.date(2026, 9, 4))
        self.assertEqual(kwargs["preferred_time"], dt.time(10, 30))

    def test_step_without_day_offset_starts_on_start_date_not_today(self):
        """Start date is day 0 even for "Send nu": a step with no
        day_offset must be searched from the start date, never from today."""
        import datetime as dt

        from django.utils import timezone as dj_tz

        person, profile = _make_person_with_profile(legacy_id="ivy3")
        profile.start_date = dt.date(2099, 10, 5)  # a Monday
        profile.save(update_fields=["start_date"])
        flow = _make_flow(
            [{"title": "Lunch", "config": {"with_email": "mgr2@blackcapitaltechnology.com", "duration_minutes": 30}}],
            slug="no-offset",
        )
        assignment = profile.assignments.create(flow=flow, assigned_by=self.manager)
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)
        with patch("apps.onboarding.slot_finder.find_organizer_slot") as mock_slot, \
             patch("apps.planner.google.events.create_checkin_event") as mock_create:
            mock_slot.return_value = OnboardingSlotResult(
                starts_at=dj_tz.now() + dj_tz.timedelta(days=1), duration_minutes=30
            )
            mock_create.return_value = CreatedEvent(
                google_event_id="evt-9", html_link="http://cal/evt-9",
                start=dj_tz.now(), end=dj_tz.now(),
            )
            book_onboarding_calendar_meetings(person)
        self.assertEqual(mock_slot.call_args.kwargs["search_from"], dt.date(2099, 10, 5))

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


SCHED = "scheduler@blackcapitaltechnology.com"


@override_settings(ONBOARDING_SCHEDULER_EMAIL=SCHED)
class SchedulerMultiParticipantBookingTests(TestCase):
    """With a scheduler mailbox, it owns the event; every participant is
    busy-checked and invited, and the scheduler's own calendar isn't."""

    def setUp(self):
        self.manager = User.objects.create_user(username="mgr3", email="mgr3@blackcapitaltechnology.com")
        self.scheduler = User.objects.create_user(username="sched", email=SCHED)

    def _assign(self, person, profile, steps, **assignment_fields):
        flow = _make_flow(steps, slug=f"flow-{person.legacy_id}")
        assignment = profile.assignments.create(
            flow=flow, assigned_by=self.manager, **assignment_fields
        )
        for step in flow.steps.all():
            StepProgress.objects.create(assignment=assignment, step=step)
        return assignment

    def _run(self, person):
        from django.utils import timezone as dj_tz

        with patch("apps.onboarding.slot_finder.find_organizer_slot") as mock_slot, \
             patch("apps.planner.google.events.create_checkin_event") as mock_create:
            mock_slot.return_value = OnboardingSlotResult(
                starts_at=dj_tz.now() + dj_tz.timedelta(days=1), duration_minutes=30
            )
            mock_create.return_value = CreatedEvent(
                google_event_id="evt-s", html_link="http://cal/evt-s",
                start=dj_tz.now(), end=dj_tz.now(),
            )
            result = book_onboarding_calendar_meetings(person)
        return result, mock_slot, mock_create

    def test_leder_and_buddy_meeting(self):
        person, profile = _make_person_with_profile(legacy_id="multi1")
        self._assign(
            person, profile,
            [{"title": "Meeting with Buddy and Leader",
              "config": {"participants": ["leder", "buddy"], "duration_minutes": 30}}],
            leder_email="leder@blackcapitaltechnology.com",
            buddy_email="buddy@blackcapitaltechnology.com",
        )
        result, mock_slot, mock_create = self._run(person)

        self.assertEqual(len(result.booked), 1, result.failed)
        slot_kwargs = mock_slot.call_args.kwargs
        self.assertEqual(slot_kwargs["organizer_user"], self.scheduler)
        self.assertEqual(
            slot_kwargs["busy_emails"],
            ["leder@blackcapitaltechnology.com", "buddy@blackcapitaltechnology.com"],
        )
        create_kwargs = mock_create.call_args.kwargs
        self.assertEqual(create_kwargs["organizer_user"], self.scheduler)
        self.assertEqual(
            create_kwargs["attendee_emails"],
            ["leder@blackcapitaltechnology.com", "buddy@blackcapitaltechnology.com",
             "multi1@blackcapitaltechnology.com"],
        )
        self.assertEqual(result.booked[0].organizer_email, SCHED)

    def test_missing_buddy_fails_step(self):
        person, profile = _make_person_with_profile(legacy_id="multi2")
        self._assign(
            person, profile,
            [{"title": "Meeting with Buddy and Leader",
              "config": {"participants": ["leder", "buddy"], "duration_minutes": 30}}],
            leder_email="leder@blackcapitaltechnology.com",
        )
        result, mock_slot, _ = self._run(person)
        self.assertEqual(result.booked, [])
        self.assertIn("buddy", result.failed[0].error)
        mock_slot.assert_not_called()

    def test_legacy_with_email_still_works(self):
        person, profile = _make_person_with_profile(legacy_id="multi3")
        self._assign(
            person, profile,
            [{"title": "1:1", "config": {"with_email": "leder", "duration_minutes": 30}}],
            leder_email="leder@blackcapitaltechnology.com",
        )
        result, mock_slot, _ = self._run(person)
        self.assertEqual(len(result.booked), 1)
        self.assertEqual(mock_slot.call_args.kwargs["busy_emails"], ["leder@blackcapitaltechnology.com"])

    def test_norwegian_assignment_uses_norwegian_title_and_country(self):
        person, profile = _make_person_with_profile(legacy_id="multi5")
        assignment = self._assign(
            person, profile,
            [{"title": "Velkomstmøde", "config": {"participants": ["leder"], "duration_minutes": 30}}],
            leder_email="leder@blackcapitaltechnology.com",
            country="NO",
        )
        FlowStep.objects.filter(flow=assignment.flow).update(
            title_no="Velkomstmøte", description_no="Agenda på norsk"
        )
        result, mock_slot, mock_create = self._run(person)
        self.assertEqual(len(result.booked), 1, result.failed)
        self.assertEqual(mock_slot.call_args.kwargs["country"], "NO")
        self.assertEqual(mock_create.call_args.kwargs["title"], "Onboarding: Velkomstmøte")
        self.assertEqual(mock_create.call_args.kwargs["agenda"], "Agenda på norsk")

    def test_scheduler_not_signed_in_fails_all_steps_clearly(self):
        self.scheduler.delete()
        person, profile = _make_person_with_profile(legacy_id="multi4")
        self._assign(
            person, profile,
            [{"title": "A", "config": {"participants": ["leder"], "duration_minutes": 30}},
             {"title": "B", "config": {"participants": ["leder"], "duration_minutes": 30}}],
            leder_email="leder@blackcapitaltechnology.com",
        )
        result, mock_slot, _ = self._run(person)
        self.assertEqual(len(result.failed), 2)
        self.assertIn("hasn't signed in", result.failed[0].error)
        mock_slot.assert_not_called()


class ParticipantConfigTests(TestCase):
    def test_tokens_prefer_participants_and_dedupe(self):
        tokens = CalendarMeetingComponent.participant_tokens(
            {"participants": ["leder", "buddy", "LEDER"], "with_email": "x@y.dk"}
        )
        self.assertEqual(tokens, ["leder", "buddy"])

    def test_tokens_fall_back_to_with_email_then_leder(self):
        self.assertEqual(
            CalendarMeetingComponent.participant_tokens({"with_email": "it@y.dk"}), ["it@y.dk"]
        )
        self.assertEqual(CalendarMeetingComponent.participant_tokens({}), ["leder"])

    def test_validation(self):
        from django.core.exceptions import ValidationError

        CalendarMeetingComponent.validate_config(
            {"participants": ["leder", "it@blackcapitaltechnology.com"], "duration_minutes": 30}
        )
        for bad in ([], ["nobody"], [""], "leder"):
            with self.assertRaises(ValidationError, msg=bad):
                CalendarMeetingComponent.validate_config(
                    {"participants": bad, "duration_minutes": 30}
                )

    def test_migration_maps_titles(self):
        import importlib

        mod = importlib.import_module("apps.onboarding.migrations.0008_calendar_meeting_participants")
        self.assertEqual(
            mod._participants_for("Week 1 · Mon 09:00 — Welcome with manager & buddy", "leder"),
            ["leder", "buddy"],
        )
        self.assertEqual(
            mod._participants_for("Meeting with Buddy and Leader", ""), ["leder", "buddy"]
        )
        self.assertEqual(mod._participants_for("Sync with buddy", "buddy"), ["buddy"])
        self.assertEqual(
            mod._participants_for(
                "Weekly 1:1 with manager (+ project status & buddy check-in)", "leder"
            ),
            ["leder"],
        )
        self.assertEqual(
            mod._participants_for("Lunch with manager and buddy", "assigning_manager"),
            ["assigning_manager", "leder", "buddy"],
        )



class EventTitleTests(TestCase):
    def test_prefix(self):
        from apps.onboarding.calendar_booking import onboarding_event_title

        self.assertEqual(
            onboarding_event_title("Milestone · 30 days — 30-day conversation"),
            "Onboarding: Milestone · 30 days — 30-day conversation",
        )
        self.assertEqual(onboarding_event_title("Onboarding: Velkomst"), "Onboarding: Velkomst")
        self.assertEqual(onboarding_event_title(""), "Onboarding: Onboarding-møde")
