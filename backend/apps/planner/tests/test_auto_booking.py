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

from apps.planner.models import RotationSession
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

        summary = auto_booking.run_auto_bookings(windows_ahead=1, from_date=date(2026, 1, 5))

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

        auto_booking.run_auto_bookings(windows_ahead=1, from_date=date(2026, 1, 5))

        mock_find_slot.assert_called_once()
        _, kwargs = mock_find_slot.call_args
        self.assertEqual(kwargs["buffer_minutes"], 0)
        self.assertEqual(kwargs["max_per_day"], 2)
