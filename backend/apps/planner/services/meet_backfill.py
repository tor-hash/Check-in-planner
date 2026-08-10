"""Backfill Google Meet links onto check-ins booked before conference data
was requested at event-creation time (see ``google/events.create_checkin_event``).

Idempotent and safe to re-run: only touches ``CheckInMeeting`` rows that are
still ``scheduled``, have a Google Calendar event, and don't already have a
Meet link. Uses ``events.patch`` with ``sendUpdates="none"`` by default so
attendees aren't notified -- only the ``conferenceData`` field changes on the
underlying event, nothing else about the meeting (time, attendees, agenda).
"""
from __future__ import annotations

import logging

from apps.planner.models import CheckInMeeting

logger = logging.getLogger(__name__)


def backfill_meet_links(*, dry_run: bool = False, send_updates: str = "none") -> dict:
    """Add a Meet link to every scheduled check-in that's missing one.

    Returns a summary dict with counts. Each meeting is handled
    independently -- one failure never blocks the rest of the batch.
    """
    summary = {
        "updated": 0,
        "already_has_link": 0,
        "skipped_no_event_id": 0,
        "skipped_no_user": 0,
        "not_resolved": 0,
        "error": 0,
    }

    from apps.planner.google.events import add_meet_link_to_event

    qs = (
        CheckInMeeting.objects.select_related("manager", "manager__user")
        .filter(status="scheduled")
        .order_by("starts_at")
    )

    for meeting in qs:
        if meeting.google_meet_link:
            summary["already_has_link"] += 1
            continue

        if not meeting.google_event_id:
            # Never made it to Google (or was created before we tracked the
            # event id) -- nothing to patch.
            summary["skipped_no_event_id"] += 1
            continue

        organizer = meeting.manager.user if meeting.manager_id else None
        if organizer is None:
            logger.warning(
                "meet_backfill: meeting %s has no linked organizer user -- skipping",
                meeting.pk,
            )
            summary["skipped_no_user"] += 1
            continue

        if dry_run:
            logger.info("meet_backfill: [dry-run] would patch meeting %s", meeting.pk)
            summary["updated"] += 1
            continue

        try:
            meet_link = add_meet_link_to_event(
                organizer_user=organizer,
                google_event_id=meeting.google_event_id,
                send_updates=send_updates,
            )
        except Exception as exc:
            logger.warning("meet_backfill: failed to patch meeting %s: %s", meeting.pk, exc)
            summary["error"] += 1
            continue

        if not meet_link:
            logger.info(
                "meet_backfill: Google did not resolve a Meet link for meeting %s",
                meeting.pk,
            )
            summary["not_resolved"] += 1
            continue

        meeting.google_meet_link = meet_link
        meeting.save(update_fields=["google_meet_link", "updated_at"])
        summary["updated"] += 1

    return summary
