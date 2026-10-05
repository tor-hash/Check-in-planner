"""Tests for the auto-booking service's per-manager limits.

Google Calendar and the slot-finder are mocked -- these tests only verify
that ``run_auto_bookings`` reads each manager's own
``booking_gap_minutes`` / ``max_auto_bookings_per_day`` settings instead of
a hardcoded, org-wide constant.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.planner.google.events import CreatedEvent
from apps.planner.models import CheckInMeeting, RotationSession
from apps.planner.services import auto_booking, rotation
from apps.planner.services.slot_finder import SlotResult
from apps.planner.tests.factories import (
    ManagerFactory,
    PersonFactory,
    TeamMembershipFactory,
    UserFactory,
    ensure_planner_config,
)


class AutoBookingLimitsTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))

        self.mgr_a = ManagerFactory(
            legacy_id="a", max_auto_bookings_per_day=5, booking_gap_minutes=45
        )
        ManagerFactory(legacy_id="b")
        ManagerFactory(legacy_id="c")

        self.user = UserFactory()
        self.mgr_a.user = self.user
        self.mgr_a.save(update_fields=["user"])

        self.person = PersonFactory(legacy_id="alice", email="alice@example.com")
        TeamMembershipFactory(team="team-1", person=self.person)

        rotation.generate_cycle()
        # Force mgr_a to own team-1/session-0 so alice is unambiguously
        # theirs, regardless of how the rotation algorithm assigns the rest.
        RotationSession.objects.filter(
            cycle_start=date(2026, 1, 5), session_index=0, team="team-1"
        ).update(manager=self.mgr_a)

    @patch("apps.planner.services.bookings.create_booking")
    @patch("apps.planner.services.auto_booking.find_available_slot")
    def test_uses_managers_own_gap_and_daily_cap(self, mock_find_slot, mock_create_booking):
        mock_find_slot.return_value = SlotResult(
            starts_at=datetime(2026, 1, 12, 10, 0, tzinfo=UTC), duration_minutes=15
        )
        mock_create_booking.return_value = MagicMock(pk=1)

        summary = auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))

        mock_find_slot.assert_called_once()
        _, kwargs = mock_find_slot.call_args
        self.assertEqual(kwargs["buffer_minutes"], 45)
        self.assertEqual(kwargs["max_per_day"], 5)
        self.assertEqual(summary["booked"], 1)

    @patch("apps.planner.services.bookings.create_booking")
    @patch("apps.planner.services.auto_booking.find_available_slot")
    def test_default_manager_uses_new_defaults(self, mock_find_slot, mock_create_booking):
        """A manager who never touched their settings gets the new
        product defaults: 2 meetings/day, 0-minute gap."""
        # Move alice's team to a fresh manager still on factory defaults.
        default_mgr = ManagerFactory(legacy_id="d")
        default_mgr.user = UserFactory()
        default_mgr.save(update_fields=["user"])
        RotationSession.objects.filter(
            cycle_start=date(2026, 1, 5), session_index=0, team="team-1"
        ).update(manager=default_mgr)

        mock_find_slot.return_value = SlotResult(
            starts_at=datetime(2026, 1, 12, 10, 0, tzinfo=UTC), duration_minutes=15
        )
        mock_create_booking.return_value = MagicMock(pk=1)

        auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))

        mock_find_slot.assert_called_once()
        _, kwargs = mock_find_slot.call_args
        self.assertEqual(kwargs["buffer_minutes"], 30)
        self.assertEqual(kwargs["max_per_day"], 2)

    @patch("apps.planner.services.bookings.create_checkin_event")
    @patch("apps.planner.services.auto_booking.find_available_slot")
    def test_running_twice_does_not_double_book(self, mock_find_slot, mock_create_event):
        """Regression test for the idempotency claim in this module's
        docstring ("running it multiple times in a week is safe"). Unlike
        the tests above, this one does NOT mock create_booking -- it lets
        the real DB path run (only the Google Calendar call is mocked) so a
        real duplicate would actually have to be prevented, not just
        assumed. A manual "Run now" the same week as the scheduled run is
        exactly this scenario."""
        mock_find_slot.return_value = SlotResult(
            starts_at=datetime(2026, 1, 12, 10, 0, tzinfo=UTC), duration_minutes=15
        )
        mock_create_event.return_value = CreatedEvent(
            google_event_id="evt-1",
            html_link="https://calendar.google.com/x",
            start=datetime(2026, 1, 12, 10, 0, tzinfo=UTC),
            end=datetime(2026, 1, 12, 10, 15, tzinfo=UTC),
        )

        first = auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))
        second = auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))

        self.assertEqual(first["booked"], 1)
        self.assertEqual(second["booked"], 0)
        self.assertEqual(second["already_exists"], 1)
        self.assertEqual(CheckInMeeting.objects.count(), 1)
        # The second run's own already-booked check short-circuits before
        # ever asking the slot-finder for a slot again.
        mock_find_slot.assert_called_once()


class AutoBookingPeriodsAheadTests(TestCase):
    """``ManagerProfile.auto_booking_periods_ahead`` replaces the old
    run-level ``windows_ahead`` argument: each manager now decides, on
    their own booking settings, how many upcoming session windows the
    auto-booking job books for them on every run. Default is 2 periods
    (current + 1 ahead) so that, with a weekly cron and a 2-week period,
    a period's meetings are already booked before it starts rather than
    right as it begins."""

    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.mgr_a = ManagerFactory(legacy_id="a", auto_booking_periods_ahead=4)
        self.mgr_b = ManagerFactory(legacy_id="b")  # left on the default (2)
        self.mgr_c = ManagerFactory(legacy_id="c")  # left on the default (2)
        rotation.generate_cycle()

    @patch("apps.planner.services.auto_booking.upcoming_session_windows")
    def test_each_manager_is_looked_up_with_their_own_setting(self, mock_upcoming_windows):
        # Short-circuit before any real booking work -- this test only
        # cares about what run_auto_bookings asks the rotation engine for.
        mock_upcoming_windows.return_value = []

        auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))

        self.assertEqual(mock_upcoming_windows.call_count, 3)
        ns_used = sorted(call.args[0] for call in mock_upcoming_windows.call_args_list)
        # mgr_a's own override (4), plus mgr_b and mgr_c both on the default (2).
        self.assertEqual(ns_used, [2, 2, 4])
        for call in mock_upcoming_windows.call_args_list:
            self.assertEqual(call.kwargs.get("from_date"), date(2026, 1, 5))

    def test_default_is_two_periods_ahead(self):
        self.assertEqual(self.mgr_b.auto_booking_periods_ahead, 2)


class AutoBookingAllowSameDayTests(TestCase):
    """``PlannerConfig.auto_booking_allow_same_day`` (default False) is a
    single global toggle -- not per-manager -- threaded down into every
    ``find_available_slot`` call the job makes."""

    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.mgr_a = ManagerFactory(legacy_id="a")
        ManagerFactory(legacy_id="b")
        ManagerFactory(legacy_id="c")

        self.user = UserFactory()
        self.mgr_a.user = self.user
        self.mgr_a.save(update_fields=["user"])

        self.person = PersonFactory(legacy_id="alice", email="alice@example.com")
        TeamMembershipFactory(team="team-1", person=self.person)

        rotation.generate_cycle()
        RotationSession.objects.filter(
            cycle_start=date(2026, 1, 5), session_index=0, team="team-1"
        ).update(manager=self.mgr_a)

    def test_default_is_false(self):
        from apps.planner.models import PlannerConfig

        self.assertFalse(PlannerConfig.singleton().auto_booking_allow_same_day)

    @patch("apps.planner.services.bookings.create_booking")
    @patch("apps.planner.services.auto_booking.find_available_slot")
    def test_default_forbids_same_day_bookings(self, mock_find_slot, mock_create_booking):
        mock_find_slot.return_value = SlotResult(
            starts_at=datetime(2026, 1, 12, 10, 0, tzinfo=UTC), duration_minutes=15
        )
        mock_create_booking.return_value = MagicMock(pk=1)

        auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))

        mock_find_slot.assert_called_once()
        _, kwargs = mock_find_slot.call_args
        self.assertFalse(kwargs["allow_same_day"])

    @patch("apps.planner.services.bookings.create_booking")
    @patch("apps.planner.services.auto_booking.find_available_slot")
    def test_global_toggle_flows_through_to_slot_finder(self, mock_find_slot, mock_create_booking):
        from apps.planner.models import PlannerConfig

        cfg = PlannerConfig.singleton()
        cfg.auto_booking_allow_same_day = True
        cfg.save(update_fields=["auto_booking_allow_same_day"])

        mock_find_slot.return_value = SlotResult(
            starts_at=datetime(2026, 1, 12, 10, 0, tzinfo=UTC), duration_minutes=15
        )
        mock_create_booking.return_value = MagicMock(pk=1)

        auto_booking.run_auto_bookings(from_date=date(2026, 1, 5))

        mock_find_slot.assert_called_once()
        _, kwargs = mock_find_slot.call_args
        self.assertTrue(kwargs["allow_same_day"])
