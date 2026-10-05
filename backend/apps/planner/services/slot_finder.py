"""Slot-finder: locate the first free calendar slot for a check-in meeting.

Given a session window (week_start … week_end), a manager, and a person, it:
  1. Queries Google Calendar free/busy for both parties.
  2. Walks candidate slots in 30-minute (or configured) increments across
     every working day in the window.
  3. Respects the manager's ``booking_blocked_windows`` and
     ``booking_preferred_days`` preferences.
  4. Enforces the manager's buffer (``ManagerProfile.booking_gap_minutes``,
     default 30 min) both *before and after* the new check-in against
     **every** busy block in the manager's calendar -- other check-ins and
     any other meeting/event alike -- plus check-ins booked earlier in the
     same run. The employee's calendar only has to be free for the slot
     itself (the buffer is the manager's setting, not the employee's).
     Also enforces a maximum number of auto-booked check-ins per manager per
     calendar day (default 3).
  5. Returns the first mutually free slot, or ``None`` if none exists.

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
• ``already_booked`` is a list of ``(start_utc, end_utc)`` tuples representing
  meetings booked earlier in the same auto-booking run that are not yet
  reflected in the free/busy snapshot (which is queried once per call).
• ``allow_same_day`` (default True) controls whether "today" (in
  ``tz_name``) is itself a candidate day. The auto-booking job passes its
  own value, driven by ``PlannerConfig.auto_booking_allow_same_day``
  (default False), so a same-day cron run doesn't produce a same-day
  meeting; callers that represent an explicit human choice (e.g.
  rescheduling) leave it at the default.
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
# Internal interval helper (for already_booked entries)
# ---------------------------------------------------------------------------


@dataclass
class _SimpleInterval:
    """Minimal interval object compatible with _overlaps_busy."""
    start: datetime
    end: datetime


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
    slot_start: datetime,
    slot_end: datetime,
    busy: list,  # list of objects with .start and .end (datetime, UTC)
    buffer_minutes: int = 0,
) -> bool:
    """Return True if [slot_start, slot_end) is too close to any busy interval.

    With ``buffer_minutes > 0`` a slot is rejected if there is less than
    ``buffer_minutes`` of free time between it and any existing event.  This
    ensures meetings are never back-to-back without a breathing gap.
    """
    buf = timedelta(minutes=buffer_minutes)
    for interval in busy:
        # The slot is blocked if it starts before the interval ends (+ buffer)
        # AND it ends after the interval starts (- buffer).
        if slot_start < interval.end + buf and slot_end > interval.start - buf:
            return True
    return False


def _count_checkins_for_manager_on_day(
    manager: "ManagerProfile",
    d: date,
    tz_name: str,
) -> int:
    """Count existing non-cancelled/declined check-in meetings for *manager* on day *d*.

    Used to enforce the per-manager daily meeting cap.
    """
    import zoneinfo
    from apps.planner.models import CheckInMeeting

    tz = zoneinfo.ZoneInfo(tz_name)
    day_start = datetime(d.year, d.month, d.day, 0, 0, tzinfo=tz)
    day_end = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=tz)

    return (
        CheckInMeeting.objects
        .filter(manager=manager, starts_at__gte=day_start, starts_at__lte=day_end)
        .exclude(status__in=["cancelled", "declined"])
        .count()
    )


def _is_on_day(dt_utc: datetime, d: date, tz_name: str) -> bool:
    """Return True if *dt_utc* falls on calendar day *d* in the local timezone."""
    import zoneinfo

    tz = zoneinfo.ZoneInfo(tz_name)
    return dt_utc.astimezone(tz).date() == d


def _today_local(tz_name: str) -> date:
    """Return today's date in *tz_name*, based on the real current time."""
    import zoneinfo

    from django.utils import timezone as dj_tz

    tz = zoneinfo.ZoneInfo(tz_name)
    return dj_tz.now().astimezone(tz).date()


def _ordered_candidate_dates(
    window: "SessionWindow",
    *,
    only_weekdays: bool,
    preferred_days: list[str],
    allow_same_day: bool,
    today_local: date,
) -> list[date]:
    """Build the chronologically-ordered list of candidate dates within
    ``window``: applies the weekdays-only filter and, when
    ``allow_same_day`` is False, excludes ``today_local``; then reorders so
    preferred days come first (chronological order preserved within each
    group).
    """
    all_dates: list[date] = []
    current = window.week_start
    while current <= window.week_end:
        if only_weekdays and current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        if not allow_same_day and current == today_local:
            current += timedelta(days=1)
            continue
        all_dates.append(current)
        current += timedelta(days=1)

    if preferred_days:
        pref_set = set(preferred_days)
        preferred = [d for d in all_dates if _WEEKDAY_NAMES[d.weekday()] in pref_set]
        other = [d for d in all_dates if _WEEKDAY_NAMES[d.weekday()] not in pref_set]
        return preferred + other
    return all_dates


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
    buffer_minutes: int = 30,
    max_per_day: int = 3,
    already_booked: list[tuple[datetime, datetime]] | None = None,
    allow_same_day: bool = True,
) -> SlotResult | None:
    """Return the first mutually free slot in ``window``, or ``None``.

    Parameters
    ----------
    organizer_user:
        The Django ``User`` whose Google credentials are used to call the
        free/busy API.
    buffer_minutes:
        Minimum free time (in minutes) required before *and* after the new
        check-in, measured against every busy block in the manager's calendar
        (other check-ins and all other events) and against ``already_booked``.
        The employee's busy blocks are only checked for direct overlap.
        Defaults to 30.  Pass 0 to disable.
    max_per_day:
        Maximum number of auto-booked check-in meetings a manager may have on
        any single calendar day.  Defaults to 3.  Pass 0 to disable.
    already_booked:
        List of ``(start_utc, end_utc)`` tuples for meetings booked earlier in
        the same auto-booking run.  These are not yet visible in the free/busy
        snapshot (which is queried once per call) and must be checked manually.
    allow_same_day:
        When False, today (in ``tz_name``) is excluded from the candidate
        dates entirely -- the earliest possible slot is tomorrow. Defaults
        to True. The auto-booking job passes its own setting here; other
        callers (e.g. an explicit reschedule) leave the default.
    """
    from apps.planner.google.freebusy import query_freebusy

    tz_name = tz_name or getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
    duration_minutes = duration_minutes or manager.preferred_meeting_duration_minutes or 30
    already_booked = already_booked or []

    work_start, work_end = _work_hours()
    exclude_lunch = _exclude_lunch()
    only_weekdays = _weekdays_only()
    blocked_windows: list[dict] = manager.booking_blocked_windows or []
    preferred_days: list[str] = manager.booking_preferred_days or []

    ordered_dates = _ordered_candidate_dates(
        window,
        only_weekdays=only_weekdays,
        preferred_days=preferred_days,
        allow_same_day=allow_same_day,
        today_local=_today_local(tz_name),
    )

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
    buffer_delta = timedelta(minutes=max(buffer_minutes, 0))
    window_start_utc = datetime(
        window.week_start.year,
        window.week_start.month,
        window.week_start.day,
        work_start.hour,
        work_start.minute,
        tzinfo=tz,
    ).astimezone(UTC) - buffer_delta
    window_end_utc = datetime(
        window.week_end.year,
        window.week_end.month,
        window.week_end.day,
        work_end.hour,
        work_end.minute,
        tzinfo=tz,
    ).astimezone(UTC) + buffer_delta
    # ^ Both ends are widened by the buffer so an event that ends just before
    #   work-start on the first day (or starts just after work-end on the last
    #   day) is still visible and the buffer around it is respected.

    emails = []
    if manager.person and manager.person.email:
        emails.append(manager.person.email)
    if person.email:
        emails.append(person.email)

    # De-duplicate (manager and person might share an email in tests)
    emails = list(dict.fromkeys(e for e in emails if e))

    busy_by_email: dict = {}
    manager_email = manager.person.email if manager.person else None

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

    # Split busy intervals by whose calendar they come from:
    #   • manager_busy -- every event in the manager's calendar (check-ins AND
    #     any other meeting) plus check-ins booked earlier in this run that
    #     are not yet in the free/busy snapshot. The manager's buffer applies
    #     to these, both before and after the candidate slot.
    #   • other_busy   -- the employee's calendar. Only a direct overlap
    #     disqualifies a slot; the buffer is the manager's preference.
    manager_busy: list = []
    other_busy: list = []
    for email in emails:
        target = manager_busy if email == manager_email else other_busy
        target.extend(busy_by_email.get(email, []))

    # Convert already_booked tuples to interval objects so _overlaps_busy can
    # treat them the same as Google free/busy intervals.
    manager_busy.extend(_SimpleInterval(start=s, end=e) for s, e in already_booked)

    # Walk candidate slots in chronological order.
    for candidate_date in ordered_dates:
        # ── Daily cap check ──────────────────────────────────────────────────
        # db_count  = meetings already committed to the DB (includes this run's
        #             bookings, which are committed immediately by create_booking).
        # run_count = meetings booked so far THIS run (from already_booked).
        #             This overlaps with db_count for same-run bookings, so we
        #             MUST NOT add them together — that double-counts.  Instead
        #             we check each source independently: if either says we've
        #             hit the cap, skip this day.
        if max_per_day > 0:
            db_count = _count_checkins_for_manager_on_day(manager, candidate_date, tz_name)
            run_count = sum(
                1 for (s, _e) in already_booked
                if _is_on_day(s, candidate_date, tz_name)
            )
            if db_count >= max_per_day or run_count >= max_per_day:
                logger.info(
                    "slot_finder: daily cap (%d) reached for manager=%s on %s "
                    "(db=%d, run=%d) — skipping day",
                    max_per_day,
                    manager.legacy_id,
                    candidate_date,
                    db_count,
                    run_count,
                )
                continue

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

            if _overlaps_busy(slot_start, slot_end, manager_busy, buffer_minutes):
                continue
            if not _overlaps_busy(slot_start, slot_end, other_busy, 0):
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
