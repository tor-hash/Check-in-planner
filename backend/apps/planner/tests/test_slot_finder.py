"""Tests for the slot-finder's date-candidate logic, in particular the
``allow_same_day`` toggle backing ``PlannerConfig.auto_booking_allow_same_day``
(see services.auto_booking module docstring)."""
from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from django.test import TestCase

from apps.planner.google.freebusy import BusyInterval
from apps.planner.services.rotation import SessionWindow
from apps.planner.services.slot_finder import _ordered_candidate_dates, find_available_slot
from apps.planner.tests.factories import ManagerFactory, PersonFactory, ensure_planner_config

_TZ = zoneinfo.ZoneInfo("Europe/Copenhagen")

# Monday 2026-01-05 .. Sunday 2026-01-18 (a 2-week session window).
_WINDOW = SessionWindow(
    cycle_start=date(2026, 1, 5),
    session_index=0,
    week_start=date(2026, 1, 5),
    week_end=date(2026, 1, 18),
)


class OrderedCandidateDatesTests(TestCase):
    """Pure unit tests of the date-list builder -- no DB/Google calls."""

    def test_weekdays_only_excludes_weekends(self):
        dates = _ordered_candidate_dates(
            _WINDOW,
            only_weekdays=True,
            preferred_days=[],
            allow_same_day=True,
            today_local=date(2020, 1, 1),  # far outside the window -- irrelevant
        )
        self.assertEqual(len(dates), 10)  # 2 x Mon-Fri
        self.assertNotIn(date(2026, 1, 10), dates)  # a Saturday
        self.assertNotIn(date(2026, 1, 11), dates)  # a Sunday

    def test_allow_same_day_false_excludes_today_only(self):
        dates = _ordered_candidate_dates(
            _WINDOW,
            only_weekdays=True,
            preferred_days=[],
            allow_same_day=False,
            today_local=date(2026, 1, 12),  # a Monday inside the window
        )
        self.assertNotIn(date(2026, 1, 12), dates)
        self.assertEqual(len(dates), 9)
        # Chronological order is otherwise preserved.
        self.assertEqual(dates[0], date(2026, 1, 5))

    def test_allow_same_day_true_keeps_today(self):
        dates = _ordered_candidate_dates(
            _WINDOW,
            only_weekdays=True,
            preferred_days=[],
            allow_same_day=True,
            today_local=date(2026, 1, 12),
        )
        self.assertIn(date(2026, 1, 12), dates)
        self.assertEqual(len(dates), 10)

    def test_preferred_days_come_first_in_chronological_order(self):
        dates = _ordered_candidate_dates(
            _WINDOW,
            only_weekdays=True,
            preferred_days=["wednesday"],
            allow_same_day=True,
            today_local=date(2020, 1, 1),
        )
        # The two Wednesdays in the window, in order, then everything else.
        self.assertEqual(dates[0], date(2026, 1, 7))
        self.assertEqual(dates[1], date(2026, 1, 14))
        self.assertNotIn(date(2026, 1, 7), dates[2:])


class FindAvailableSlotSameDayTests(TestCase):
    """End-to-end (mocked free/busy) checks that ``allow_same_day`` actually
    changes what ``find_available_slot`` returns."""

    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.manager = ManagerFactory(legacy_id="m")
        self.person = PersonFactory(legacy_id="p")

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_allow_same_day_false_books_tomorrow_not_today(self, mock_now, mock_freebusy):
        mock_freebusy.return_value = ({}, {})
        # A Monday-morning cron run, 08:00 local -- before the 09:00 work start.
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)

        slot = find_available_slot(
            manager=self.manager,
            person=self.person,
            window=_WINDOW,
            organizer_user=None,
            allow_same_day=False,
        )
        self.assertIsNotNone(slot)
        self.assertEqual(slot.starts_at.astimezone(_TZ).date(), date(2026, 1, 6))

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_allow_same_day_true_can_book_the_same_day(self, mock_now, mock_freebusy):
        mock_freebusy.return_value = ({}, {})
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)

        slot = find_available_slot(
            manager=self.manager,
            person=self.person,
            window=_WINDOW,
            organizer_user=None,
            allow_same_day=True,
        )
        self.assertIsNotNone(slot)
        self.assertEqual(slot.starts_at.astimezone(_TZ).date(), date(2026, 1, 5))


class FindAvailableSlotBufferTests(TestCase):
    """The manager's buffer (``booking_gap_minutes``) must be kept free before
    AND after a new check-in, against every event in the manager's calendar
    -- not just other check-ins -- while the employee's calendar only needs
    to be free for the slot itself."""

    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.manager = ManagerFactory(legacy_id="m", preferred_meeting_duration_minutes=30)
        self.person = PersonFactory(legacy_id="p")
        self.mgr_email = self.manager.person.email
        self.person_email = self.person.email

    def _local(self, h, m=0, day=6):
        return datetime(2026, 1, day, h, m, tzinfo=_TZ)

    def _find(self, mock_freebusy, busy_by_email, **kwargs):
        mock_freebusy.return_value = (busy_by_email, {})
        return find_available_slot(
            manager=self.manager,
            person=self.person,
            window=_WINDOW,
            organizer_user=None,
            allow_same_day=False,
            **kwargs,
        )

    def _block(self, start, end):
        return BusyInterval(start=start.astimezone(UTC), end=end.astimezone(UTC))

    def test_default_buffer_is_30_minutes(self):
        from apps.planner.models import ManagerProfile

        self.assertEqual(ManagerProfile._meta.get_field("booking_gap_minutes").default, 30)
        self.assertEqual(ManagerProfile.objects.get(pk=self.manager.pk).booking_gap_minutes, 30)

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_buffer_after_non_checkin_event_in_manager_calendar(self, mock_now, mock_freebusy):
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)
        # Manager has an ordinary (non-check-in) meeting 09:00-10:00 on Tue.
        busy = {self.mgr_email: [self._block(self._local(9), self._local(10))]}
        slot = self._find(mock_freebusy, busy, buffer_minutes=30)
        self.assertEqual(slot.starts_at.astimezone(_TZ), self._local(10, 30))

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_buffer_before_non_checkin_event_in_manager_calendar(self, mock_now, mock_freebusy):
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)
        # Manager is busy 09:00-10:00 and 11:15-17:00 on Tuesday. After the
        # buffer following the first block, 10:30-11:00 is the only candidate,
        # but it leaves just 15 min before 11:15 -> rejected by the buffer.
        busy = {
            self.mgr_email: [
                self._block(self._local(9), self._local(10)),
                self._block(self._local(11, 15), self._local(17)),
            ]
        }
        slot = self._find(mock_freebusy, busy, buffer_minutes=30)
        # Tuesday is fully blocked by the buffer -> Wednesday 09:00.
        self.assertEqual(slot.starts_at.astimezone(_TZ), self._local(9, 0, day=7))

        # Without a buffer, 10:00 on Tuesday is fine.
        slot = self._find(mock_freebusy, busy, buffer_minutes=0)
        self.assertEqual(slot.starts_at.astimezone(_TZ), self._local(10))

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_buffer_does_not_apply_to_employee_calendar(self, mock_now, mock_freebusy):
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)
        # The *employee* is busy 09:00-10:00: the slot may start right at 10:00.
        busy = {self.person_email: [self._block(self._local(9), self._local(10))]}
        slot = self._find(mock_freebusy, busy, buffer_minutes=30)
        self.assertEqual(slot.starts_at.astimezone(_TZ), self._local(10))

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_buffer_applies_to_checkins_booked_earlier_in_run(self, mock_now, mock_freebusy):
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)
        earlier = (self._local(9).astimezone(UTC), self._local(9, 30).astimezone(UTC))
        slot = self._find(mock_freebusy, {}, buffer_minutes=30, already_booked=[earlier])
        self.assertEqual(slot.starts_at.astimezone(_TZ), self._local(10))

    @patch("apps.planner.google.freebusy.query_freebusy")
    @patch("django.utils.timezone.now")
    def test_freebusy_window_widened_by_buffer(self, mock_now, mock_freebusy):
        mock_now.return_value = datetime(2026, 1, 5, 8, 0, tzinfo=_TZ)
        self._find(mock_freebusy, {}, buffer_minutes=30)
        _, kwargs = mock_freebusy.call_args
        self.assertEqual(kwargs["time_min"], datetime(2026, 1, 5, 8, 30, tzinfo=_TZ).astimezone(UTC))
        self.assertEqual(kwargs["time_max"], datetime(2026, 1, 18, 17, 30, tzinfo=_TZ).astimezone(UTC))
        self.assertEqual(kwargs["time_max"] - kwargs["time_min"], timedelta(days=13, hours=9))
