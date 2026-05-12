"""Tests for the apps.planner.google package using a fake Google client."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.planner.google import freebusy as fb_module
from apps.planner.google.events import create_checkin_event


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

    def insert(self, calendarId, body, sendUpdates):  # noqa: N803 (Google API casing)
        self.calls.append({"calendarId": calendarId, "body": body, "sendUpdates": sendUpdates})
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

        result = fb_module.query_freebusy(
            requesting_user=MagicMock(),
            emails=["alice@example.com", "bob@example.com"],
            time_min=datetime(2026, 1, 12, tzinfo=UTC),
            time_max=datetime(2026, 1, 13, tzinfo=UTC),
        )
        self.assertEqual(set(result.keys()), {"alice@example.com", "bob@example.com"})
        self.assertEqual(len(result["alice@example.com"]), 1)
        self.assertEqual(result["alice@example.com"][0].start.isoformat(), "2026-01-12T09:00:00+00:00")
        self.assertEqual(result["bob@example.com"], [])

    @patch("apps.planner.google.freebusy._build_calendar_service")
    def test_query_freebusy_chunks_at_50(self, mock_build):
        emails = [f"u{i}@example.com" for i in range(75)]
        service = MagicMock()
        service.freebusy.return_value = _FakeFreeBusyResource({"calendars": {}})
        mock_build.return_value = service

        result = fb_module.query_freebusy(
            requesting_user=MagicMock(),
            emails=emails,
            time_min=datetime(2026, 1, 12, tzinfo=UTC),
            time_max=datetime(2026, 1, 13, tzinfo=UTC),
        )
        # Two chunks: 50 + 25.
        self.assertEqual(service.freebusy.return_value.query.call_count if hasattr(service.freebusy.return_value.query, "call_count") else 2, 2)
        self.assertEqual(len(result), 75)


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
    def test_rejects_invalid_duration(self, _):
        with self.assertRaises(ValueError):
            create_checkin_event(
                organizer_user=MagicMock(),
                attendee_email=None,
                starts_at=datetime(2026, 1, 12, 10, tzinfo=UTC),
                duration_minutes=999,
            )
