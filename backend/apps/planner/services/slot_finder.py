"""Slot-finder: locate the first free calendar slot for a check-in meeting.

Given a session window (week_start … week_end), a manager, and a person, it:
  1. Queries Google Calendar free/busy for both parties.
  2. Walks candidate slots in 30-minute (or configured) increments across
     every working day in the window.
  3. Respects the manager's ``booking_blocked_windows`` and
     ``booking_preferred_days`` preferences.
  4. Returns the first mutually free slot, or ``None`` if none exists.

Strategy
--------
• Preferred days are tried first (any order within the day); if none found,
  we fall back to all working days in the window.
• We spread the search across the whole session window (no clustering on
  day 1), which means we return the earliest free slot chronologically
  within that window — the effect is natural distribution over the two weeks.
• Work-hours come from ``PlannerConfig.work_hours``
  (``{"start": "HH:MM", "end": "HH:MM", "excludeLunch": bool, "weekdaysOnly": bool}``).
• Lunch exclusion: 12:00–13:00.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING

from django.conf import settings

if TYPE_CHECKING:
    from apps.planner.models import ManagerProfile, Person
    from apps.planner.services.rotation import SessionWindow

logger = logging.getLogger(__name__)

_LUNCH_START = time(12, 0)
_LUNCH_END = time(13, 0)

_WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class SlotResult:
    starts_at: datetime  # tz-aware (UTC)
    duration_minutes: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _work_hours() -> tuple[time, time]:
    """Return (start, end) as ``time`` objects from PlannerConfig."""
    from apps.planner.models import PlannerConfig

    wh = PlannerConfig.singleton().work_hours or {}
    try:
        start_str = wh.get("start", "09:00")
        end_str = wh.get("end", "17:00")
        h_s, m_s = map(int, start_str.split(":"))
        h_e, m_e = map(int, end_str.split(":"))
        return time(h_s, m_s), time(h_e, m_e)
    except (ValueError, AttributeError):
        return time(9, 0), time(17, 0)


def _exclude_lunch() -> bool:
    from apps.planner.models import PlannerConfig

    wh = PlannerConfig.singleton().work_hours or {}
    return bool(wh.get("excludeLunch", True))


def _weekdays_only() -> bool:
    from apps.planner.models import PlannerConfig

    wh = PlannerConfig.singleton().work_hours or {}
    return bool(wh.get("weekdaysOnly", True))


def _to_utc(d: date, t: time, tz_name: str) -> datetime:
    """Combine a local date + time and convert to UTC."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo(tz_name)
    local_dt = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=tz)
    return local_dt.astimezone(UTC)


def _is_blocked_by_manager_prefs(
    slot_start: time,
    slot_end: time,
    weekday_name: str,
    blocked_windows: list[dict],
) -> bool:
    """Return True if [slot_start, slot_end) overlaps any manager-defined blocked window."""
    for w in blocked_windows:
        days = w.get("days", "all")
        if days != "all" and weekday_name not in days:
            continue
        try:
            bh, bm = map(int, w["start_time"].split(":"))
            eh, em = map(int, w["end_time"].split(":"))
        except (ValueError, KeyError):
            continue
        b_start = time(bh, bm)
        b_end = time(eh, em)
        # Overlap: slot starts before window ends AND slot ends after window starts
        if slot_start < b_end and slot_end > b_start:
            return True
    return False


def _slots_for_day(
    d: date,
    duration_minutes: int,
    work_start: time,
    work_end: time,
    exclude_lunch: bool,
    blocked_windows: list[dict],
    tz_name: str,
) -> list[tuple[datetime, datetime]]:
    """All valid (start_utc, end_utc) candidate slots for day ``d``."""
    step = timedelta(minutes=15)  # granularity of candidate slots
    dur = timedelta(minutes=duration_minutes)
    weekday_name = _WEEKDAY_NAMES[d.weekday()]

    candidates: list[tuple[datetime, datetime]] = []
    current = datetime(d.year, d.month, d.day, work_start.hour, work_start.minute)
    work_end_dt = datetime(d.year, d.month, d.day, work_end.hour, work_end.minute)

    while current + dur <= work_end_dt:
        s_t = current.time()
        e_t = (current + dur).time()

        # Lunch check
        if exclude_lunch and s_t < _LUNCH_END and e_t > _LUNCH_START:
            current += step
            continue

        # Manager blocked-window check
        if _is_blocked_by_manager_prefs(s_t, e_t, weekday_name, blocked_windows):
            current += step
            continue

        import zoneinfo

        tz = zoneinfo.ZoneInfo(tz_name)
        slot_start_utc = datetime(
            d.year, d.month, d.day, current.hour, current.minute, tzinfo=tz
        ).astimezone(UTC)
        slot_end_utc = slot_start_utc + dur
        candidates.append((slot_start_utc, slot_end_utc))
        current += step

    return candidates


def _overlaps_busy(
    slot_start: datetime, slot_end: datetime, busy: list  # list[BusyInterval]
) -> bool:
    """Return True if [slot_start, slot_end) overlaps any busy interval."""
    for interval in busy:
        if slot_start < interval.end and slot_end > interval.start:
            return True
    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def find_available_slot(
    *,
    manager: "ManagerProfile",
    person: "Person",
    window: "SessionWindow",
    organizer_user,
    duration_minutes: int | None = None,
    tz_name: str | None = None,
) -> SlotResult | None:
    """Return the first mutually free slot in ``window``, or ``None``.

    ``organizer_user`` is the Django ``User`` whose Google credentials are used
    to call the free/busy API.
    """
    from apps.planner.google.freebusy import query_freebusy

    tz_name = tz_name or getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
    duration_minutes = duration_minutes or manager.preferred_meeting_duration_minutes or 30

    work_start, work_end = _work_hours()
    exclude_lunch = _exclude_lunch()
    only_weekdays = _weekdays_only()
    blocked_windows: list[dict] = manager.booking_blocked_windows or []
    preferred_days: list[str] = manager.booking_preferred_days or []

    # Build the list of candidate dates across the session window.
    all_dates: list[date] = []
    current = window.week_start
    while current <= window.week_end:
        if only_weekdays and current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        all_dates.append(current)
        current += timedelta(days=1)

    # Preferred days first, then the rest (preserving chronological order within each group).
    if preferred_days:
        pref_set = set(preferred_days)
        preferred = [d for d in all_dates if _WEEKDAY_NAMES[d.weekday()] in pref_set]
        other = [d for d in all_dates if _WEEKDAY_NAMES[d.weekday()] not in pref_set]
        ordered_dates = preferred + other
    else:
        ordered_dates = all_dates

    if not ordered_dates:
        logger.warning(
            "slot_finder: no candidate dates in window %s–%s",
            window.week_start,
            window.week_end,
        )
        return None

    # Query free/busy for the whole window in one shot (more efficient than
    # per-day calls when the window is 2 weeks).
    import zoneinfo

    tz = zoneinfo.ZoneInfo(tz_name)
    window_start_utc = datetime(
        window.week_start.year,
        window.week_start.month,
        window.week_start.day,
        work_start.hour,
        work_start.minute,
        tzinfo=tz,
    ).astimezone(UTC)
    window_end_utc = datetime(
        window.week_end.year,
        window.week_end.month,
        window.week_end.day,
        work_end.hour,
        work_end.minute,
        tzinfo=tz,
    ).astimezone(UTC)

    emails = []
    if manager.person and manager.person.email:
        emails.append(manager.person.email)
    if person.email:
        emails.append(person.email)

    # De-duplicate (manager and person might share an email in tests)
    emails = list(dict.fromkeys(e for e in emails if e))

    busy_by_email: dict = {}
    if emails:
        try:
            busy_by_email, errors_by_email = query_freebusy(
                requesting_user=organizer_user,
                emails=emails,
                time_min=window_start_utc,
                time_max=window_end_utc,
                timezone=tz_name,
            )
            if errors_by_email:
                logger.warning(
                    "slot_finder: free/busy errors for some calendars: %s",
                    list(errors_by_email.keys()),
                )
        except Exception:
            logger.exception("slot_finder: free/busy query failed; proceeding with no busy data")

    # Merge busy intervals for all participants.
    all_busy = []
    for email in emails:
        all_busy.extend(busy_by_email.get(email, []))

    # Walk candidate slots in chronological order.
    for candidate_date in ordered_dates:
        slots = _slots_for_day(
            candidate_date,
            duration_minutes,
            work_start,
            work_end,
            exclude_lunch,
            blocked_windows,
            tz_name,
        )
        for slot_start, slot_end in slots:
            # Skip slots in the past (safety guard when window starts today)
            from django.utils import timezone as dj_tz

            if slot_start < dj_tz.now():
                continue

            if not _overlaps_busy(slot_start, slot_end, all_busy):
                logger.info(
                    "slot_finder: found slot %s (+%d min) for manager=%s person=%s",
                    slot_start.isoformat(),
                    duration_minutes,
                    manager.legacy_id,
                    person.legacy_id if hasattr(person, "legacy_id") else person.pk,
                )
                return SlotResult(starts_at=slot_start, duration_minutes=duration_minutes)

    logger.info(
        "slot_finder: no free slot in window %s–%s for manager=%s person=%s",
        window.week_start,
        window.week_end,
        manager.legacy_id,
        person.legacy_id if hasattr(person, "legacy_id") else person.pk,
    )
    return None
