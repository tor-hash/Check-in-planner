"""Tests for the apps.planner.google package using a fake Google client."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.planner.google import freebusy as fb_module
from apps.planner.google.events import add_meet_link_to_event, create_checkin_event


class _FakeFreeBusyResource:
    def __init__(self, payload):
        self._payload = payload

    def query(self, body):  # pylint: disable=unused-argument
        resource = MagicMock()
        resource.execute.return_value = self._payload
        return resource


class _FakeEventsResource:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def insert(self, calendarId, body, sendUpdates, conferenceDataVersion=None):  # noqa: N803 (Google API casing)
        self.calls.append(
            {
                "op": "insert",
                "calendarId": calendarId,
                "body": body,
                "sendUpdates": sendUpdates,
                "conferenceDataVersion": conferenceDataVersion,
            }
        )
        resource = MagicMock()
        resource.execute.return_value = self._response
        return resource

    def patch(self, calendarId, eventId, body, sendUpdates, conferenceDataVersion=None):  # noqa: N803
        self.calls.append(
            {
                "op": "patch",
                "calendarId": calendarId,
                "eventId": eventId,
                "body": body,
                "sendUpdates": sendUpdates,
                "conferenceDataVersion": conferenceDataVersion,
            }
        )
        resource = MagicMock()
        resource.execute.return_value = self._response
        return resource


class FreeBusyTests(TestCase):
    @patch("apps.planner.google.freebusy._build_calendar_service")
    def test_query_freebusy_groups_by_email(self, mock_build):
        payload = {
            "calendars": {
                "alice@example.com": {
                    "busy": [
                        {"start": "2026-01-12T09:00:00Z", "end": "2026-01-12T10:00:00Z"},
                    ]
                },
                "bob@example.com": {"busy": []},
            }
        }
        service = MagicMock()
        service.freebusy.return_value = _FakeFreeBusyResource(payload)
        mock_build.return_value = service

        busy, errors = fb_module.query_freebusy(
            requesting_user=MagicMock(),
            emails=["alice@example.com", "bob@example.com"],
            time_min=datetime(2026, 1, 12, tzinfo=UTC),
            time_max=datetime(2026, 1, 13, tzinfo=UTC),
        )
        self.assertEqual(errors, {})
        self.assertEqual(set(busy.keys()), {"alice@example.com", "bob@example.com"})
        self.assertEqual(len(busy["alice@example.com"]), 1)
        self.assertEqual(busy["alice@example.com"][0].start.isoformat(), "2026-01-12T09:00:00+00:00")
        self.assertEqual(busy["bob@example.com"], [])

    @patch("apps.planner.google.freebusy._build_calendar_service")
    def test_query_freebusy_records_calendar_errors(self, mock_build):
        payload = {
            "calendars": {
                "alice@example.com": {
                    "busy": [],
                    "errors": [{"domain": "calendar", "reason": "notFound"}],
                },
            }
        }
        service = MagicMock()
        service.freebusy.return_value = _FakeFreeBusyResource(payload)
        mock_build.return_value = service

        busy, errors = fb_module.query_freebusy(
            requesting_user=MagicMock(),
            emails=["alice@example.com"],
            time_min=datetime(2026, 1, 12, tzinfo=UTC),
            time_max=datetime(2026, 1, 13, tzinfo=UTC),
        )
        self.assertEqual(busy["alice@example.com"], [])
        self.assertIn("alice@example.com", errors)

    @patch("apps.planner.google.freebusy._build_calendar_service")
    def test_query_freebusy_chunks_at_50(self, mock_build):
        emails = [f"u{i}@example.com" for i in range(75)]
        service = MagicMock()
        service.freebusy.return_value = _FakeFreeBusyResource({"calendars": {}})
        mock_build.return_value = service

        busy, _errors = fb_module.query_freebusy(
            requesting_user=MagicMock(),
            emails=emails,
            time_min=datetime(2026, 1, 12, tzinfo=UTC),
            time_max=datetime(2026, 1, 13, tzinfo=UTC),
        )
        self.assertEqual(len(busy), 75)


class CreateEventTests(TestCase):
    @patch("apps.planner.google.events._build_calendar_service")
    def test_creates_event_with_attendee(self, mock_build):
        events_resource = _FakeEventsResource({"id": "evt-1", "htmlLink": "https://example.com"})
        service = MagicMock()
        service.events.return_value = events_resource
        mock_build.return_value = service

        result = create_checkin_event(
            organizer_user=MagicMock(),
            attendee_email="alice@example.com",
            starts_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
            duration_minutes=30,
            title="1:1",
            agenda="hello",
        )
        self.assertEqual(result.google_event_id, "evt-1")
        self.assertEqual(result.html_link, "https://example.com")
        self.assertEqual(result.end - result.start, timedelta(minutes=30))
        # Verify the request body had the attendee.
        call = events_resource.calls[0]
        self.assertEqual(call["sendUpdates"], "all")
        self.assertEqual(call["body"]["attendees"], [{"email": "alice@example.com"}])

    @patch("apps.planner.google.events._build_calendar_service")
    def test_requests_google_meet_conference_data(self, mock_build):
        """Every check-in event must request a Google Meet link."""
        events_resource = _FakeEventsResource(
            {
                "id": "evt-1",
                "htmlLink": "https://example.com",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
            }
        )
        service = MagicMock()
        service.events.return_value = events_resource
        mock_build.return_value = service

        result = create_checkin_event(
            organizer_user=MagicMock(),
            attendee_email="alice@example.com",
            starts_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
            duration_minutes=30,
        )

        self.assertEqual(result.meet_link, "https://meet.google.com/abc-defg-hij")

        call = events_resource.calls[0]
        self.assertEqual(call["conferenceDataVersion"], 1)
        conf = call["body"]["conferenceData"]["createRequest"]
        self.assertEqual(conf["conferenceSolutionKey"], {"type": "hangoutsMeet"})
        self.assertTrue(conf["requestId"])

    @patch("apps.planner.google.events._build_calendar_service")
    def test_meet_link_defaults_to_empty_when_absent(self, mock_build):
        """If Google doesn't resolve conferenceData, we degrade gracefully."""
        events_resource = _FakeEventsResource({"id": "evt-1", "htmlLink": "https://example.com"})
        service = MagicMock()
        service.events.return_value = events_resource
        mock_build.return_value = service

        result = create_checkin_event(
            organizer_user=MagicMock(),
            attendee_email=None,
            starts_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
            duration_minutes=30,
        )
        self.assertEqual(result.meet_link, "")

    @patch("apps.planner.google.events._build_calendar_service")
    def test_rejects_invalid_duration(self, _):
        with self.assertRaises(ValueError):
            create_checkin_event(
                organizer_user=MagicMock(),
                attendee_email=None,
                starts_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
                duration_minutes=999,
            )



class AddMeetLinkToEventTests(TestCase):
    @patch("apps.planner.google.events._build_calendar_service")
    def test_patches_conference_data_without_notifying_by_default(self, mock_build):
        events_resource = _FakeEventsResource(
            {"id": "evt-1", "hangoutLink": "https://meet.google.com/xyz-abcd-efg"}
        )
        service = MagicMock()
        service.events.return_value = events_resource
        mock_build.return_value = service

        link = add_meet_link_to_event(organizer_user=MagicMock(), google_event_id="evt-1")

        self.assertEqual(link, "https://meet.google.com/xyz-abcd-efg")
        call = events_resource.calls[0]
        self.assertEqual(call["op"], "patch")
        self.assertEqual(call["eventId"], "evt-1")
        self.assertEqual(call["sendUpdates"], "none")
        self.assertEqual(call["conferenceDataVersion"], 1)
        conf = call["body"]["conferenceData"]["createRequest"]
        self.assertEqual(conf["conferenceSolutionKey"], {"type": "hangoutsMeet"})

    @patch("apps.planner.google.events._build_calendar_service")
    def test_can_request_attendee_notification(self, mock_build):
        events_resource = _FakeEventsResource({"id": "evt-1", "hangoutLink": "https://meet.google.com/x"})
        service = MagicMock()
        service.events.return_value = events_resource
        mock_build.return_value = service

        add_meet_link_to_event(
            organizer_user=MagicMock(), google_event_id="evt-1", send_updates="all"
        )
        self.assertEqual(events_resource.calls[0]["sendUpdates"], "all")

    @patch("apps.planner.google.events._build_calendar_service")
    def test_returns_empty_string_when_not_resolved(self, mock_build):
        events_resource = _FakeEventsResource({"id": "evt-1"})
        service = MagicMock()
        service.events.return_value = events_resource
        mock_build.return_value = service

        link = add_meet_link_to_event(organizer_user=MagicMock(), google_event_id="evt-1")
        self.assertEqual(link, "")
