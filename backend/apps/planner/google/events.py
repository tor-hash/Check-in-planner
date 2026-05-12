"""Google Calendar events.insert wrapper.

Creates a check-in event on the manager's primary calendar with the developer
as an invited attendee. Sends the calendar invitation email via
``sendUpdates=all``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .credentials import credentials_for_user

logger = logging.getLogger(__name__)


@dataclass
class CreatedEvent:
    google_event_id: str
    html_link: str
    start: datetime
    end: datetime


def _build_calendar_service(user):
    from googleapiclient.discovery import build

    creds = credentials_for_user(user)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def create_checkin_event(
    *,
    organizer_user,
    attendee_email: str | None,
    starts_at: datetime,
    duration_minutes: int = 30,
    title: str = "Check-in samtale",
    agenda: str = "",
    timezone: str = "Europe/Copenhagen",
) -> CreatedEvent:
    """Create the event in ``organizer_user``'s primary calendar.

    Returns a :class:`CreatedEvent` containing the Google event id and a
    sharable HTML link. Raises if Google rejects the request — caller should
    catch and roll back any DB changes.
    """
    if duration_minutes < 5 or duration_minutes > 240:
        raise ValueError("duration_minutes must be between 5 and 240.")
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=UTC)
    ends_at = starts_at + timedelta(minutes=duration_minutes)

    body: dict = {
        "summary": title or "Check-in samtale",
        "description": agenda or "",
        "start": {"dateTime": starts_at.isoformat(), "timeZone": timezone},
        "end": {"dateTime": ends_at.isoformat(), "timeZone": timezone},
    }
    if attendee_email:
        body["attendees"] = [{"email": attendee_email}]

    service = _build_calendar_service(organizer_user)
    try:
        created = (
            service.events()
            .insert(calendarId="primary", body=body, sendUpdates="all")
            .execute()
        )
    except Exception:
        logger.exception(
            "Calendar events.insert failed for organizer=%s attendee=%s starts_at=%s",
            getattr(organizer_user, "email", "?"),
            attendee_email,
            starts_at.isoformat(),
        )
        raise

    return CreatedEvent(
        google_event_id=created.get("id") or "",
        html_link=created.get("htmlLink") or "",
        start=starts_at,
        end=ends_at,
    )


def cancel_checkin_event(*, organizer_user, google_event_id: str) -> None:
    """Best-effort: delete the event from the organizer's calendar."""
    if not google_event_id:
        return
    service = _build_calendar_service(organizer_user)
    try:
        service.events().delete(
            calendarId="primary", eventId=google_event_id, sendUpdates="all"
        ).execute()
    except Exception:
        logger.exception(
            "Calendar events.delete failed for organizer=%s event_id=%s",
            getattr(organizer_user, "email", "?"),
            google_event_id,
        )
        raise
