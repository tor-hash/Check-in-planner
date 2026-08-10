"""Find the first open slot on a single organizer's Google calendar.

This is deliberately independent from ``apps.planner.services.slot_finder``:
onboarding meetings don't go through team rotation, don't require a
``ManagerProfile`` (the organizer of a ``calendar_meeting`` step can be a
manager, HR, IT, a buddy — anyone with a connected Google account), and
don't need the employee's own calendar to be free/busy-checked (they likely
haven't shared it yet at the point a flow is attached — see
``CalendarMeetingComponent`` / ``welcome_email.py``). Only the organizer's
own calendar matters here.

Product decision: book meetings "no matter how far in the future" — there
is no business-rule search horizon. ``_MAX_SEARCH_DAYS`` below is purely a
technical safety ceiling to guarantee this function terminates.
"""
from __future__ import annotations

import logging
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings
from django.utils import timezone as dj_tz

from apps.planner.google.credentials import credentials_for_user
from apps.planner.google.freebusy import query_freebusy

logger = logging.getLogger(__name__)

_LUNCH_START = time(12, 0)
_LUNCH_END = time(13, 0)
_SLOT_GRANULARITY = timedelta(minutes=15)
_QUERY_CHUNK_DAYS = 90
# Safety ceiling only (~2 years) — not a business rule. Prevents a runaway
# loop if an organizer's calendar is, for whatever reason, always busy.
_MAX_SEARCH_DAYS = 730


@dataclass
class OnboardingSlotResult:
    starts_at: datetime  # tz-aware, UTC
    duration_minutes: int


@dataclass
class _Interval:
    start: datetime
    end: datetime


def _work_hours() -> tuple[time, time, bool, bool]:
    """Return (start, end, exclude_lunch, weekdays_only) from PlannerConfig.

    Reused read-only from the global scheduling settings — not manager- or
    rotation-specific, so this doesn't couple onboarding to the check-in
    system.
    """
    from apps.planner.models import PlannerConfig

    wh = PlannerConfig.singleton().work_hours or {}
    try:
        h_s, m_s = map(int, wh.get("start", "09:00").split(":"))
        h_e, m_e = map(int, wh.get("end", "17:00").split(":"))
        start, end = time(h_s, m_s), time(h_e, m_e)
    except (ValueError, AttributeError):
        start, end = time(9, 0), time(17, 0)
    exclude_lunch = bool(wh.get("excludeLunch", True))
    weekdays_only = bool(wh.get("weekdaysOnly", True))
    return start, end, exclude_lunch, weekdays_only


def _overlaps(
    slot_start: datetime,
    slot_end: datetime,
    busy: list,
    buffer_minutes: int,
) -> bool:
    buf = timedelta(minutes=buffer_minutes)
    for interval in busy:
        if slot_start < interval.end + buf and slot_end > interval.start - buf:
            return True
    return False


def find_organizer_slot(
    *,
    organizer_user,
    organizer_email: str,
    duration_minutes: int = 30,
    tz_name: str | None = None,
    buffer_minutes: int = 30,
    already_booked: list[tuple[datetime, datetime]] | None = None,
    search_from: date | None = None,
) -> OnboardingSlotResult | None:
    """Return the first open slot on ``organizer_user``'s own calendar.

    Raises ``apps.planner.google.credentials.GoogleCredentialsUnavailable``
    if the organizer hasn't connected Google — callers should treat that as
    a hard stop for this step (per product decision: don't book blind, tell
    them to connect their calendar).

    Only the organizer's calendar is queried. The employee's free/busy is
    intentionally not considered — see module docstring.
    """
    tz_name = tz_name or getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
    already_booked = already_booked or []
    work_start, work_end, exclude_lunch, weekdays_only = _work_hours()
    tz = zoneinfo.ZoneInfo(tz_name)

    # Raises GoogleCredentialsUnavailable if not connected -- propagate.
    credentials_for_user(organizer_user)

    start_date = search_from or dj_tz.now().astimezone(tz).date()
    horizon_end = start_date + timedelta(days=_MAX_SEARCH_DAYS)
    dur = timedelta(minutes=duration_minutes)

    extra_busy = [_Interval(s, e) for s, e in already_booked]

    chunk_start = start_date
    while chunk_start <= horizon_end:
        chunk_end = min(chunk_start + timedelta(days=_QUERY_CHUNK_DAYS), horizon_end)

        window_start_utc = datetime(
            chunk_start.year, chunk_start.month, chunk_start.day,
            work_start.hour, work_start.minute, tzinfo=tz,
        ).astimezone(UTC)
        window_end_utc = datetime(
            chunk_end.year, chunk_end.month, chunk_end.day,
            work_end.hour, work_end.minute, tzinfo=tz,
        ).astimezone(UTC)

        busy: list = []
        try:
            busy_by_email, errors_by_email = query_freebusy(
                requesting_user=organizer_user,
                emails=[organizer_email],
                time_min=window_start_utc,
                time_max=window_end_utc,
                timezone=tz_name,
            )
            if errors_by_email:
                logger.warning(
                    "onboarding slot_finder: free/busy error for %s: %s",
                    organizer_email, errors_by_email,
                )
            busy = list(busy_by_email.get(organizer_email, []))
        except Exception:
            logger.exception(
                "onboarding slot_finder: free/busy query failed for %s; "
                "proceeding with no busy data for this chunk",
                organizer_email,
            )

        combined_busy = busy + extra_busy

        current_date = chunk_start
        while current_date <= chunk_end:
            if weekdays_only and current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            slot_local = datetime(
                current_date.year, current_date.month, current_date.day,
                work_start.hour, work_start.minute,
            )
            day_end_local = datetime(
                current_date.year, current_date.month, current_date.day,
                work_end.hour, work_end.minute,
            )

            while slot_local + dur <= day_end_local:
                s_t, e_t = slot_local.time(), (slot_local + dur).time()
                if exclude_lunch and s_t < _LUNCH_END and e_t > _LUNCH_START:
                    slot_local += _SLOT_GRANULARITY
                    continue

                slot_start_utc = datetime(
                    current_date.year, current_date.month, current_date.day,
                    slot_local.hour, slot_local.minute, tzinfo=tz,
                ).astimezone(UTC)
                slot_end_utc = slot_start_utc + dur

                if slot_start_utc >= dj_tz.now() and not _overlaps(
                    slot_start_utc, slot_end_utc, combined_busy, buffer_minutes
                ):
                    logger.info(
                        "onboarding slot_finder: found slot %s (+%d min) for %s",
                        slot_start_utc.isoformat(), duration_minutes, organizer_email,
                    )
                    return OnboardingSlotResult(
                        starts_at=slot_start_utc, duration_minutes=duration_minutes
                    )

                slot_local += _SLOT_GRANULARITY

            current_date += timedelta(days=1)

        chunk_start = chunk_end + timedelta(days=1)

    logger.warning(
        "onboarding slot_finder: no free slot found for %s within %d days",
        organizer_email, _MAX_SEARCH_DAYS,
    )
    return None
