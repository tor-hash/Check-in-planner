"""Tests for the booking service + API.

Google Calendar is mocked everywhere — these tests must never make an HTTP
call to Google. The real google-api-python-client integration is exercised
in a separate Playwright smoke test against a fake server.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import patch

from django.test import Client, TestCase

from apps.planner.google.events import CreatedEvent
from apps.planner.models import CheckInMeeting
from apps.planner.services import bookings, rotation
from apps.planner.tests.factories import (
    ManagerFactory,
    PersonFactory,
    TeamMembershipFactory,
    UserFactory,
    ensure_planner_config,
)


def _aware(when: datetime) -> datetime:
    return when.replace(tzinfo=UTC)


class BookingServiceTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.mgr_a = ManagerFactory(legacy_id="a")
        self.mgr_b = ManagerFactory(legacy_id="b")
        self.mgr_c = ManagerFactory(legacy_id="c")
        self.person = PersonFactory(legacy_id="alice", email="alice@example.com")
        TeamMembershipFactory(team="team-1", person=self.person)
        rotation.generate_cycle()
        # Look up which manager actually owns team-1 in session 0 so the
        # booking is valid.
        from apps.planner.models import RotationSession

        owner_session = RotationSession.objects.get(
            cycle_start=date(2026, 1, 5), session_index=0, team="team-1"
        )
        self.owner = owner_session.manager
        self.user = UserFactory()

    def _request(self, *, manager=None, person=None, starts_at=None) -> bookings.BookingRequest:
        return bookings.BookingRequest(
            manager=manager or self.owner,
            person=person or self.person,
            organizer_user=self.user,
            starts_at=starts_at or _aware(datetime(2026, 1, 12, 10, 0)),
            duration_minutes=30,
            title="1:1",
            agenda="checkin",
        )

    @patch("apps.planner.services.bookings.create_checkin_event")
    def test_create_booking_happy_path(self, mock_create):
        mock_create.return_value = CreatedEvent(
            google_event_id="evt-1",
            html_link="https://calendar.google.com/x",
            start=_aware(datetime(2026, 1, 12, 10, 0)),
            end=_aware(datetime(2026, 1, 12, 10, 30)),
        )
        meeting = bookings.create_booking(self._request(), audit_user=self.user)
        self.assertEqual(meeting.status, "scheduled")
        self.assertEqual(meeting.google_event_id, "evt-1")
        self.assertEqual(meeting.google_html_link, "https://calendar.google.com/x")
        mock_create.assert_called_once()

    @patch("apps.planner.services.bookings.create_checkin_event")
    def test_rotation_violation_raises_before_google(self, mock_create):
        wrong_manager = next(
            m for m in (self.mgr_a, self.mgr_b, self.mgr_c) if m.id != self.owner.id
        )
        with self.assertRaises(bookings.BookingError):
            bookings.create_booking(self._request(manager=wrong_manager))
        mock_create.assert_not_called()
        self.assertEqual(CheckInMeeting.objects.count(), 0)

    @patch("apps.planner.services.bookings.create_checkin_event")
    def test_google_failure_rolls_back_db(self, mock_create):
        mock_create.side_effect = RuntimeError("boom")
        with self.assertRaises(bookings.GoogleBookingError):
            bookings.create_booking(self._request())
        self.assertEqual(CheckInMeeting.objects.count(), 0)


class BookingApiTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.mgr_a = ManagerFactory(legacy_id="a")
        self.mgr_b = ManagerFactory(legacy_id="b")
        self.mgr_c = ManagerFactory(legacy_id="c")
        self.person = PersonFactory(legacy_id="alice", email="alice@example.com")
        TeamMembershipFactory(team="team-1", person=self.person)
        rotation.generate_cycle()
        from apps.planner.models import RotationSession

        self.owner = RotationSession.objects.get(
            cycle_start=date(2026, 1, 5), session_index=0, team="team-1"
        ).manager
        self.user = UserFactory(manager_role=True)
        self.client = Client()
        self.client.force_login(self.user)

    @patch("apps.planner.services.bookings.create_checkin_event")
    def test_post_bookings_creates_meeting(self, mock_create):
        mock_create.return_value = CreatedEvent(
            google_event_id="evt-1",
            html_link="https://example.com",
            start=_aware(datetime(2026, 1, 12, 10, 0)),
            end=_aware(datetime(2026, 1, 12, 10, 30)),
        )
        payload = {
            "managerId": self.owner.legacy_id,
            "personId": "alice",
            "startsAt": "2026-01-12T10:00:00Z",
            "durationMinutes": 30,
            "title": "1:1",
            "agenda": "ok",
        }
        response = self.client.post(
            "/api/bookings",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["status"], "scheduled")
        self.assertEqual(body["googleEventId"], "evt-1")

    @patch("apps.planner.services.bookings.create_checkin_event")
    def test_rotation_violation_returns_409(self, _):
        wrong_manager = next(
            m for m in (self.mgr_a, self.mgr_b, self.mgr_c) if m.id != self.owner.id
        )
        payload = {
            "managerId": wrong_manager.legacy_id,
            "personId": "alice",
            "startsAt": "2026-01-12T10:00:00Z",
            "durationMinutes": 30,
        }
        response = self.client.post(
            "/api/bookings",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_list_bookings(self):
        from apps.planner.tests.factories import CheckInMeetingFactory

        CheckInMeetingFactory(
            manager=self.owner,
            person=self.person,
            starts_at=_aware(datetime(2026, 1, 12, 10, 0)),
        )
        response = self.client.get("/api/bookings?managerId=" + self.owner.legacy_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["bookings"]), 1)


class FreeBusyApiTests(TestCase):
    def setUp(self):
        self.user = UserFactory(manager_role=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_freebusy_requires_window(self):
        response = self.client.get("/api/freebusy")
        self.assertEqual(response.status_code, 400)

    def test_freebusy_returns_empty_when_no_emails(self):
        response = self.client.get(
            "/api/freebusy?from=2026-01-12T00:00:00Z&to=2026-01-13T00:00:00Z"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["calendars"], {})

    def test_freebusy_with_unknown_team_returns_no_emails(self):
        response = self.client.get(
            "/api/freebusy?from=2026-01-12T00:00:00Z&to=2026-01-13T00:00:00Z&team=team-1"
        )
        self.assertEqual(response.status_code, 200)
        # No team members exist, so calendars stays empty.
        self.assertEqual(response.json().get("calendars", {}), {})


class RotationApiTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        ManagerFactory(legacy_id="a")
        ManagerFactory(legacy_id="b")
        ManagerFactory(legacy_id="c")
        self.user = UserFactory(manager_role=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_get_rotation_returns_upcoming(self):
        response = self.client.get("/api/rotation?upcoming=2")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["sessions"]), 2)
        for session in body["sessions"]:
            self.assertEqual(len(session["teams"]), 3)
