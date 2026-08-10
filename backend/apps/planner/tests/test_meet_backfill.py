"""Tests for the Google Meet link backfill service + management command."""
from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from apps.planner.services import meet_backfill
from apps.planner.tests.factories import (
    CheckInMeetingFactory,
    ManagerFactory,
    PersonFactory,
    UserFactory,
)


class BackfillMeetLinksServiceTests(TestCase):
    def setUp(self):
        self.manager = ManagerFactory(legacy_id="mgr-x")
        self.user = UserFactory()
        self.manager.user = self.user
        self.manager.save(update_fields=["user"])
        self.person = PersonFactory(legacy_id="alice", email="alice@example.com")

    def _meeting(self, **kwargs):
        defaults = dict(
            manager=self.manager,
            person=self.person,
            starts_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            status="scheduled",
            google_event_id="evt-1",
            google_meet_link="",
        )
        defaults.update(kwargs)
        return CheckInMeetingFactory(**defaults)

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_patches_eligible_meeting(self, mock_add_link):
        mock_add_link.return_value = "https://meet.google.com/abc-defg-hij"
        meeting = self._meeting()

        summary = meet_backfill.backfill_meet_links()

        meeting.refresh_from_db()
        self.assertEqual(meeting.google_meet_link, "https://meet.google.com/abc-defg-hij")
        self.assertEqual(summary["updated"], 1)
        mock_add_link.assert_called_once_with(
            organizer_user=self.user, google_event_id="evt-1", send_updates="none"
        )

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_skips_meeting_that_already_has_a_link(self, mock_add_link):
        self._meeting(google_meet_link="https://meet.google.com/already-there")
        summary = meet_backfill.backfill_meet_links()
        self.assertEqual(summary["already_has_link"], 1)
        self.assertEqual(summary["updated"], 0)
        mock_add_link.assert_not_called()

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_skips_meeting_without_google_event_id(self, mock_add_link):
        self._meeting(google_event_id="")
        summary = meet_backfill.backfill_meet_links()
        self.assertEqual(summary["skipped_no_event_id"], 1)
        mock_add_link.assert_not_called()

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_skips_meeting_whose_manager_has_no_linked_user(self, mock_add_link):
        manager_no_user = ManagerFactory(legacy_id="mgr-no-user")
        self._meeting(manager=manager_no_user)
        summary = meet_backfill.backfill_meet_links()
        self.assertEqual(summary["skipped_no_user"], 1)
        mock_add_link.assert_not_called()

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_ignores_cancelled_meetings(self, mock_add_link):
        self._meeting(status="cancelled")
        summary = meet_backfill.backfill_meet_links()
        self.assertEqual(sum(summary.values()), 0)
        mock_add_link.assert_not_called()

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_dry_run_does_not_call_google_or_write_db(self, mock_add_link):
        meeting = self._meeting()
        summary = meet_backfill.backfill_meet_links(dry_run=True)
        meeting.refresh_from_db()
        self.assertEqual(meeting.google_meet_link, "")
        self.assertEqual(summary["updated"], 1)
        mock_add_link.assert_not_called()

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_records_error_without_blocking_other_meetings(self, mock_add_link):
        mock_add_link.side_effect = RuntimeError("boom")
        meeting = self._meeting()
        summary = meet_backfill.backfill_meet_links()
        meeting.refresh_from_db()
        self.assertEqual(meeting.google_meet_link, "")
        self.assertEqual(summary["error"], 1)

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_records_not_resolved_when_google_returns_no_link(self, mock_add_link):
        mock_add_link.return_value = ""
        meeting = self._meeting()
        summary = meet_backfill.backfill_meet_links()
        meeting.refresh_from_db()
        self.assertEqual(meeting.google_meet_link, "")
        self.assertEqual(summary["not_resolved"], 1)

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_notify_attendees_flag_passed_through(self, mock_add_link):
        mock_add_link.return_value = "https://meet.google.com/x"
        self._meeting()
        meet_backfill.backfill_meet_links(send_updates="all")
        mock_add_link.assert_called_once_with(
            organizer_user=self.user, google_event_id="evt-1", send_updates="all"
        )


class BackfillMeetLinksCommandTests(TestCase):
    def setUp(self):
        self.manager = ManagerFactory(legacy_id="mgr-y")
        self.user = UserFactory()
        self.manager.user = self.user
        self.manager.save(update_fields=["user"])
        self.person = PersonFactory(legacy_id="bob", email="bob@example.com")

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_command_runs_end_to_end(self, mock_add_link):
        mock_add_link.return_value = "https://meet.google.com/z"
        meeting = CheckInMeetingFactory(
            manager=self.manager,
            person=self.person,
            starts_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            status="scheduled",
            google_event_id="evt-9",
            google_meet_link="",
        )
        out = StringIO()
        call_command("backfill_meet_links", stdout=out)
        meeting.refresh_from_db()
        self.assertEqual(meeting.google_meet_link, "https://meet.google.com/z")
        self.assertIn("updated=1", out.getvalue())

    @patch("apps.planner.google.events.add_meet_link_to_event")
    def test_command_dry_run_flag(self, mock_add_link):
        meeting = CheckInMeetingFactory(
            manager=self.manager,
            person=self.person,
            starts_at=datetime(2026, 2, 1, 10, 0, tzinfo=UTC),
            status="scheduled",
            google_event_id="evt-10",
            google_meet_link="",
        )
        out = StringIO()
        call_command("backfill_meet_links", "--dry-run", stdout=out)
        meeting.refresh_from_db()
        self.assertEqual(meeting.google_meet_link, "")
        mock_add_link.assert_not_called()
