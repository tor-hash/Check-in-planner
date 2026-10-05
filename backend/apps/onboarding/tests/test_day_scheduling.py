"""Day arithmetic for calendar_meeting steps: day_offset + day_unit,
weekends and Danish holidays."""
from __future__ import annotations

import importlib
from datetime import date

from django.test import SimpleTestCase

from apps.onboarding.calendar_booking import scheduled_day_for_step
from apps.onboarding.components import CalendarMeetingComponent, ValidationError
from apps.onboarding.holidays_dk import (
    danish_holidays,
    easter_sunday,
    holidays_for,
    next_working_day,
)

THU = date(2026, 9, 3)  # a Thursday


class HolidayTests(SimpleTestCase):
    def test_easter(self):
        self.assertEqual(easter_sunday(2026), date(2026, 4, 5))
        self.assertEqual(easter_sunday(2027), date(2027, 3, 28))

    def test_2026_holidays(self):
        h = danish_holidays(2026)
        for d in (
            date(2026, 1, 1), date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 5, 14), date(2026, 5, 25), date(2026, 6, 5),
            date(2026, 12, 24), date(2026, 12, 25), date(2026, 12, 31),
        ):
            self.assertIn(d, h, d)
        self.assertNotIn(date(2026, 5, 1), h)

    def test_next_working_day_skips_easter_monday(self):
        # Sat 4 Apr 2026 -> Sun -> Mon 6 Apr is 2. påskedag -> Tue 7 Apr.
        self.assertEqual(next_working_day(date(2026, 4, 4)), date(2026, 4, 7))


class ScheduledDayTests(SimpleTestCase):
    def test_business_days_from_thursday(self):
        expected = [date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 7),
                    date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)]
        got = [scheduled_day_for_step(THU, n, "business") for n in range(6)]
        self.assertEqual(got, expected)

    def test_missing_unit_means_business(self):
        self.assertEqual(scheduled_day_for_step(THU, 2, None), date(2026, 9, 7))

    def test_calendar_days(self):
        # Thu 3 Sep + 30 = Sat 3 Oct -> Mon 5 Oct.
        self.assertEqual(scheduled_day_for_step(THU, 30, "calendar"), date(2026, 10, 5))
        # Thu 3 Sep + 7 = Thu 10 Sep, a working day, unchanged.
        self.assertEqual(scheduled_day_for_step(THU, 7, "calendar"), date(2026, 9, 10))

    def test_calendar_day_on_holiday_rolls_forward(self):
        # Mon 1 Dec 2026 + 24 = Thu 24 Dec (juleaften) -> 25, 26, 27 off -> Mon 28.
        self.assertEqual(
            scheduled_day_for_step(date(2026, 12, 1), 24, "calendar"), date(2026, 12, 28)
        )

    def test_business_days_skip_holidays(self):
        # Wed 1 Apr 2026: +1 skips skærtorsdag, langfredag, weekend, 2. påskedag.
        self.assertEqual(
            scheduled_day_for_step(date(2026, 4, 1), 1, "business"), date(2026, 4, 7)
        )


class DayUnitValidationTests(SimpleTestCase):
    base = {"with_email": "leder", "duration_minutes": 30, "day_offset": 30}

    def test_valid_units(self):
        for unit in ("calendar", "business"):
            CalendarMeetingComponent.validate_config({**self.base, "day_unit": unit})
        CalendarMeetingComponent.validate_config(self.base)

    def test_invalid_unit(self):
        with self.assertRaises(ValidationError):
            CalendarMeetingComponent.validate_config({**self.base, "day_unit": "weeks"})

    def test_default_config_has_no_suggested_window(self):
        self.assertNotIn("suggested_window", CalendarMeetingComponent.default_config())


class MilestoneMigrationRegexTests(SimpleTestCase):
    def test_matches_milestone_titles(self):
        mod = importlib.import_module(
            "apps.onboarding.migrations.0007_calendar_meeting_day_unit"
        )
        m = mod.MILESTONE_RE.match("Milestone · 30 days — 30-day conversation")
        self.assertEqual(m.group(1), "30")
        self.assertIsNone(mod.MILESTONE_RE.match("Week 3 · Fri — Meeting with manager"))


class NorwayTests(SimpleTestCase):
    def test_norwegian_holidays(self):
        h = holidays_for(2026, "NO")
        self.assertIn(date(2026, 5, 17), h)
        self.assertIn(date(2026, 5, 1), h)
        self.assertNotIn(date(2026, 6, 5), h)  # Danish Grundlovsdag

    def test_country_changes_roll_forward(self):
        # Fri 1 May 2026: working day in DK, holiday in NO.
        self.assertEqual(scheduled_day_for_step(date(2026, 5, 1), 0, "calendar", "DK"), date(2026, 5, 1))
        self.assertEqual(scheduled_day_for_step(date(2026, 5, 1), 0, "calendar", "NO"), date(2026, 5, 4))
        # Fri 5 Jun 2026: Grundlovsdag in DK only.
        self.assertEqual(scheduled_day_for_step(date(2026, 6, 5), 0, "calendar", "DK"), date(2026, 6, 8))
        self.assertEqual(scheduled_day_for_step(date(2026, 6, 5), 0, "calendar", "NO"), date(2026, 6, 5))


class TitleScheduleParsingTests(SimpleTestCase):
    def test_parses_flow_titles(self):
        mod = importlib.import_module(
            "apps.onboarding.migrations.0012_calendar_meeting_offsets_from_titles"
        )
        f = mod.schedule_from_title
        self.assertEqual(f("Week 1 · Mon 09:00 — Welcome with manager & buddy"), (0, "09:00"))
        self.assertEqual(f("Week 1 · Fri 10:00 — Wrap-up with manager"), (4, "10:00"))
        self.assertEqual(f("Week 2 · Fri — Short status meeting with manager"), (9, None))
        self.assertEqual(f("Week 3 · Tue–Thu — Independent work on deliverables"), (11, None))
        self.assertEqual(f("Step 5 · Week 4 — Weekly 1:1 with manager"), (15, None))
        self.assertEqual(f("Uge 2 · tirsdag 13.30 — Opfølgning"), (6, "13:30"))
        self.assertIsNone(f("Milestone · 30 days — 30-day conversation"))
        self.assertIsNone(f("Lunch with the team"))
