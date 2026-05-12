"""Booking service: rotation validation + Google Calendar event creation.

Public entry points:
    - :func:`create_booking` — validate, create the DB row, then call Google.
      Rolls back the DB row if Google rejects the event.
    - :func:`cancel_booking` — mark cancelled + delete the Google event.
    - :func:`serialize_booking` — render to JSON for the API.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.db import transaction

from apps.planner.google.events import (
    CreatedEvent,
    cancel_checkin_event,
    create_checkin_event,
)
from apps.planner.models import (
    CheckInMeeting,
    ManagerProfile,
    Person,
)
from apps.planner.services.rotation import validate_booking

logger = logging.getLogger(__name__)


class BookingError(ValueError):
    """Raised for caller-facing booking failures (rotation violation, etc)."""


class GoogleBookingError(RuntimeError):
    """Raised when Google rejects the event after DB validation passed."""


@dataclass
class BookingRequest:
    manager: ManagerProfile
    person: Person
    organizer_user: Any
    starts_at: datetime
    duration_minutes: int = 30
    title: str = "Check-in samtale"
    agenda: str = ""
    timezone: str = "Europe/Copenhagen"


def serialize_booking(meeting: CheckInMeeting) -> dict[str, Any]:
    return {
        "id": meeting.id,
        "managerId": meeting.manager.legacy_id if meeting.manager_id else None,
        "personId": meeting.person.legacy_id if meeting.person_id else None,
        "startsAt": meeting.starts_at.isoformat(),
        "durationMinutes": meeting.duration_minutes,
        "title": meeting.title,
        "agenda": meeting.agenda,
        "googleEventId": meeting.google_event_id,
        "googleHtmlLink": meeting.google_html_link,
        "status": meeting.status,
        "sessionId": meeting.session_id,
        "journalEntryId": meeting.journal_entry.entry_id if meeting.journal_entry_id else None,
        "createdAt": int(meeting.created_at.timestamp() * 1000),
        "updatedAt": int(meeting.updated_at.timestamp() * 1000),
    }


def create_booking(req: BookingRequest, *, audit_user=None) -> CheckInMeeting:
    """Create a CheckInMeeting + Google event atomically.

    Steps:
      1. Validate the rotation (raises BookingError on violation).
      2. Open a DB transaction; insert the CheckInMeeting row.
      3. Call Google Calendar inside the transaction so we still hold the row
         when Google replies.
      4. If Google succeeds, populate ``google_event_id``/``google_html_link``
         and commit. If Google fails, the transaction rolls back the row.
    """
    outcome = validate_booking(
        manager=req.manager, person=req.person, when=req.starts_at
    )
    if not outcome.ok:
        logger.info(
            "Booking rejected by rotation: manager=%s person=%s reason=%s",
            req.manager.legacy_id, req.person.legacy_id, outcome.reason,
        )
        raise BookingError(outcome.reason)

    audit = audit_user or (req.organizer_user if getattr(req.organizer_user, "is_authenticated", False) else None)

    started = time.monotonic()
    try:
        with transaction.atomic():
            meeting = CheckInMeeting.objects.create(
                manager=req.manager,
                person=req.person,
                session=outcome.session,
                starts_at=req.starts_at,
                duration_minutes=req.duration_minutes,
                title=req.title or "Check-in samtale",
                agenda=req.agenda or "",
                status="scheduled",
                created_by=audit,
                updated_by=audit,
            )
            try:
                created: CreatedEvent = create_checkin_event(
                    organizer_user=req.organizer_user,
                    attendee_email=req.person.email or None,
                    starts_at=req.starts_at,
                    duration_minutes=req.duration_minutes,
                    title=meeting.title,
                    agenda=meeting.agenda,
                    timezone=req.timezone,
                )
            except Exception as exc:
                # Re-raise to trigger the atomic rollback.
                raise GoogleBookingError(str(exc)) from exc

            meeting.google_event_id = created.google_event_id
            meeting.google_html_link = created.html_link
            meeting.save(update_fields=["google_event_id", "google_html_link", "updated_at"])
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "booking.create",
            extra={
                "event": "booking.create",
                "manager_id": req.manager.legacy_id,
                "person_id": req.person.legacy_id,
                "starts_at": req.starts_at.isoformat(),
                "duration_minutes": req.duration_minutes,
                "latency_ms": latency_ms,
                "google_event_id": getattr(meeting, "google_event_id", "") if "meeting" in locals() else "",
            },
        )

    return meeting


def cancel_booking(meeting: CheckInMeeting, *, organizer_user, audit_user=None) -> CheckInMeeting:
    """Mark the meeting as cancelled and best-effort delete the Google event."""
    if meeting.status == "cancelled":
        return meeting
    if meeting.google_event_id:
        try:
            cancel_checkin_event(
                organizer_user=organizer_user,
                google_event_id=meeting.google_event_id,
            )
        except Exception:
            # We still mark the DB row as cancelled even if Google deletion
            # fails — the manager can clean up Google manually.
            logger.exception("Could not delete Google event for meeting %s", meeting.pk)
    meeting.status = "cancelled"
    if audit_user is not None:
        meeting.updated_by = audit_user
    meeting.save(update_fields=["status", "updated_by", "updated_at"])
    return meeting
