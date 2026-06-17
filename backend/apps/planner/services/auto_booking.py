"""Auto-booking service: book check-ins for all active managers.

Called once per month (via the ``run_auto_bookings`` management command).
For each manager with ``auto_booking_enabled=True``:
  • Find the next 2 upcoming session windows.
  • For each window, find team members who don't already have a scheduled
    check-in with this manager in that window.
  • For each such person, call the slot-finder to locate the first free slot,
    then create a booking.
  • If no slot is found for a person, create a ``ManagerNotification`` row so
    the manager can handle it manually.

Design decisions
----------------
• We skip a (manager, person, window) triple if a non-cancelled meeting
  already exists in that window to avoid double-booking.
• Google credentials are taken from the manager's linked user account.
  Managers without a linked user, or without Google credentials, are skipped
  with a warning.
• Every booking is independently atomic — one failure does not block the rest.
"""
from __future__ import annotations

import logging
from datetime import date

from apps.planner.models import (
    BookingRunLog,
    CheckInMeeting,
    ManagerNotification,
    ManagerProfile,
    Person,
    TeamMembership,
)
from apps.planner.services.rotation import (
    TEAM_KEYS,
    SessionWindow,
    _team_for_person,
    get_or_create_session,
    upcoming_session_windows,
)
from apps.planner.services.slot_finder import find_available_slot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_auto_bookings(
    *,
    windows_ahead: int = 2,
    dry_run: bool = False,
    from_date: date | None = None,
    triggered_by: str = BookingRunLog.TRIGGER_CRON,
) -> dict:
    """Book check-ins for all eligible manager/person/window combinations.

    Returns a summary dict with counts of booked / skipped / failed bookings.
    Pass ``dry_run=True`` to compute the plan without creating any rows.
    """
    from django.utils import timezone

    summary = {"booked": 0, "already_exists": 0, "no_slot": 0, "error": 0, "skipped_no_user": 0}

    # Create a run-log entry (skip for dry runs so they don't pollute history)
    run_log = None
    if not dry_run:
        run_log = BookingRunLog.objects.create(triggered_by=triggered_by)

    try:
        windows = upcoming_session_windows(windows_ahead, from_date=from_date)
        if not windows:
            logger.warning("auto_booking: no upcoming session windows found")
            return summary

        managers = ManagerProfile.objects.select_related("user", "person").filter(
            auto_booking_enabled=True
        )
        if not managers.exists():
            logger.info("auto_booking: no managers with auto_booking_enabled=True")
            return summary

        for manager in managers:
            for window in windows:
                _process_manager_window(manager, window, summary, dry_run=dry_run)

    except Exception as exc:
        logger.exception("auto_booking: unexpected error during run")
        if run_log is not None:
            run_log.errors_count += 1
            run_log.error_detail = str(exc)
            run_log.finished_at = timezone.now()
            run_log.save(update_fields=["errors_count", "error_detail", "finished_at"])
        raise

    if run_log is not None:
        run_log.meetings_created = summary["booked"]
        run_log.meetings_skipped = summary["already_exists"] + summary["no_slot"] + summary["skipped_no_user"]
        run_log.errors_count = summary["error"]
        run_log.finished_at = timezone.now()
        run_log.save(update_fields=["meetings_created", "meetings_skipped", "errors_count", "finished_at"])

    logger.info("auto_booking: run complete — %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _organizer_user(manager: ManagerProfile):
    """Return the Django User to use as the Google Calendar organizer."""
    return manager.user


def _people_for_manager_in_window(
    manager: ManagerProfile, window: SessionWindow
) -> list[Person]:
    """People on the team assigned to this manager for this session window."""
    people: list[Person] = []
    for team in TEAM_KEYS:
        session = get_or_create_session(
            cycle_start=window.cycle_start,
            session_index=window.session_index,
            team=team,
        )
        if session and session.manager_id == manager.id:
            memberships = TeamMembership.objects.select_related("person").filter(team=team)
            for m in memberships:
                if m.person.email:  # only people with a calendar we can check
                    people.append(m.person)
    return people


def _meeting_exists_in_window(
    manager: ManagerProfile,
    person: Person,
    window: SessionWindow,
) -> bool:
    """Return True if a non-cancelled meeting already exists for this triple."""
    from django.utils.timezone import make_aware
    from datetime import datetime, time
    import zoneinfo
    from django.conf import settings

    tz_name = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
    tz = zoneinfo.ZoneInfo(tz_name)

    window_start = datetime.combine(window.week_start, time.min).replace(tzinfo=tz)
    window_end = datetime.combine(window.week_end, time(23, 59, 59)).replace(tzinfo=tz)

    return CheckInMeeting.objects.filter(
        manager=manager,
        person=person,
        starts_at__gte=window_start,
        starts_at__lte=window_end,
    ).exclude(status="cancelled").exists()


def _create_notification(
    manager: ManagerProfile,
    person: Person,
    window: SessionWindow,
    notification_type: str,
    meeting: CheckInMeeting | None = None,
) -> ManagerNotification | None:
    if notification_type == ManagerNotification.TYPE_NO_SLOT_FOUND:
        message = (
            f"No available slot could be found for a check-in with {person.name} "
            f"in the session window {window.week_start} – {window.week_end}. "
            f"Please book this meeting manually."
        )
    else:
        message = f"Notification for {person.name} in window {window.week_start}–{window.week_end}."

    return ManagerNotification.objects.create(
        manager=manager,
        notification_type=notification_type,
        message=message,
        meeting=meeting,
    )


def _process_manager_window(
    manager: ManagerProfile,
    window: SessionWindow,
    summary: dict,
    *,
    dry_run: bool,
) -> None:
    organizer = _organizer_user(manager)
    if organizer is None:
        logger.warning(
            "auto_booking: manager %s has no linked user — skipping window %s",
            manager.legacy_id,
            window.week_start,
        )
        summary["skipped_no_user"] += 1
        return

    people = _people_for_manager_in_window(manager, window)
    if not people:
        logger.debug(
            "auto_booking: manager %s has no team members in window %s",
            manager.legacy_id,
            window.week_start,
        )
        return

    for person in people:
        try:
            _process_single(manager, person, window, organizer, summary, dry_run=dry_run)
        except Exception:
            logger.exception(
                "auto_booking: unexpected error for manager=%s person=%s window=%s",
                manager.legacy_id,
                getattr(person, "legacy_id", person.pk),
                window.week_start,
            )
            summary["error"] += 1


def _process_single(
    manager: ManagerProfile,
    person: Person,
    window: SessionWindow,
    organizer_user,
    summary: dict,
    *,
    dry_run: bool,
) -> None:
    from django.conf import settings
    from apps.planner.services.bookings import (
        BookingError,
        BookingRequest,
        GoogleBookingError,
        create_booking,
    )

    # Skip if already booked for this window.
    if _meeting_exists_in_window(manager, person, window):
        logger.debug(
            "auto_booking: meeting already exists for manager=%s person=%s window=%s",
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            window.week_start,
        )
        summary["already_exists"] += 1
        return

    # Find a free slot.
    slot = find_available_slot(
        manager=manager,
        person=person,
        window=window,
        organizer_user=organizer_user,
    )

    if slot is None:
        logger.info(
            "auto_booking: no slot for manager=%s person=%s window=%s — creating notification",
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            window.week_start,
        )
        summary["no_slot"] += 1
        if not dry_run:
            notif = _create_notification(
                manager, person, window, ManagerNotification.TYPE_NO_SLOT_FOUND
            )
            if notif is not None:
                from apps.planner.services.decline_sync import send_notification_email
                send_notification_email(notif)
        return

    if dry_run:
        logger.info(
            "auto_booking: [dry-run] would book manager=%s person=%s at %s (+%d min)",
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            slot.starts_at.isoformat(),
            slot.duration_minutes,
        )
        summary["booked"] += 1
        return

    tz_name = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
    req = BookingRequest(
        manager=manager,
        person=person,
        organizer_user=organizer_user,
        starts_at=slot.starts_at,
        duration_minutes=slot.duration_minutes,
        title="Check-in samtale",
        agenda="",
        timezone=tz_name,
    )

    try:
        meeting = create_booking(req)
        logger.info(
            "auto_booking: booked meeting %s for manager=%s person=%s at %s",
            meeting.pk,
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            slot.starts_at.isoformat(),
        )
        summary["booked"] += 1
    except BookingError as exc:
        logger.warning(
            "auto_booking: BookingError for manager=%s person=%s: %s",
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            exc,
        )
        summary["error"] += 1
    except GoogleBookingError as exc:
        logger.error(
            "auto_booking: Google error for manager=%s person=%s: %s",
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            exc,
        )
        summary["error"] += 1
