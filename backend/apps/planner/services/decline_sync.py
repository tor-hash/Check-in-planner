"""Decline-sync service: poll Google Calendar RSVP statuses.

Called every 4 hours by the ``sync_meeting_statuses`` management command.
For each scheduled meeting that has a Google event ID:
  1. Fetch the event from the organizer's calendar.
  2. Inspect the attendee RSVP status.
  3. If the person has declined, mark the meeting as ``declined`` in the DB,
     notify the manager (in-app + email), and immediately attempt to rebook
     by running the auto-booking logic for that (manager, person, window)
     triple.

Google RSVP status values
--------------------------
``needsAction`` — invite sent, no response yet
``accepted``    — accepted
``declined``    — declined
``tentative``   — maybe

We only act on ``declined``.  A tentative is not treated as a decline.

Idempotency
-----------
• We check the current DB status before doing anything: if the meeting is
  already ``declined``, ``cancelled``, or ``completed`` we skip it.
• We only send one notification email per decline (``email_sent`` flag on
  ``ManagerNotification``).
• The rebook attempt calls ``_process_single`` which skips the triple if a
  non-cancelled meeting already exists in the window, so it is safe to
  trigger multiple times.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apps.planner.models import (
    CheckInMeeting,
    ManagerNotification,
    ManagerProfile,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def sync_meeting_statuses(*, dry_run: bool = False) -> dict:
    """Poll Google for all upcoming/recent scheduled meetings and sync RSVP status.

    Returns a summary dict.
    """
    summary = {
        "checked": 0,
        "declined": 0,
        "already_done": 0,
        "no_event_id": 0,
        "no_user": 0,
        "error": 0,
    }

    # Only look at meetings that are currently scheduled and in the future
    # (or up to 2 weeks in the past — catches late declines).
    cutoff = timezone.now() - timezone.timedelta(weeks=2)
    meetings = (
        CheckInMeeting.objects.select_related(
            "manager", "manager__user", "manager__person", "person"
        )
        .filter(status="scheduled", starts_at__gte=cutoff)
        .exclude(google_event_id="")
    )

    for meeting in meetings:
        try:
            _sync_one(meeting, summary, dry_run=dry_run)
        except Exception:
            logger.exception(
                "decline_sync: unexpected error for meeting %s", meeting.pk
            )
            summary["error"] += 1

    logger.info("decline_sync: run complete — %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_attendee_status(organizer_user, google_event_id: str, attendee_email: str) -> str | None:
    """Return the Google RSVP status for ``attendee_email`` on ``google_event_id``.

    Returns one of ``'needsAction'``, ``'accepted'``, ``'declined'``,
    ``'tentative'``, or ``None`` if the attendee is not found / call fails.
    """
    from googleapiclient.discovery import build
    from apps.planner.google.credentials import credentials_for_user

    try:
        creds = credentials_for_user(organizer_user)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        event = service.events().get(calendarId="primary", eventId=google_event_id).execute()
    except Exception:
        logger.exception(
            "decline_sync: events.get failed for event_id=%s", google_event_id
        )
        raise

    attendees = event.get("attendees") or []
    for a in attendees:
        if a.get("email", "").lower() == attendee_email.lower():
            return a.get("responseStatus")
    return None


def _sync_one(meeting: CheckInMeeting, summary: dict, *, dry_run: bool) -> None:
    summary["checked"] += 1

    if meeting.status in ("declined", "cancelled", "completed"):
        summary["already_done"] += 1
        return

    if not meeting.google_event_id:
        summary["no_event_id"] += 1
        return

    organizer = meeting.manager.user if meeting.manager else None
    if organizer is None:
        logger.warning(
            "decline_sync: meeting %s manager has no linked user", meeting.pk
        )
        summary["no_user"] += 1
        return

    person_email = meeting.person.email if meeting.person else ""
    if not person_email:
        # Nothing to check — no email means no calendar invite was sent.
        return

    rsvp = _get_attendee_status(organizer, meeting.google_event_id, person_email)

    if rsvp != "declined":
        return

    logger.info(
        "decline_sync: meeting %s declined by %s", meeting.pk, person_email
    )

    if dry_run:
        summary["declined"] += 1
        return

    # Mark the meeting as declined.
    meeting.status = "declined"
    meeting.save(update_fields=["status", "updated_at"])

    # Notify the manager (in-app notification + email).
    _create_declined_notification(meeting)
    summary["declined"] += 1

    # Automatically attempt to rebook in the same session window.
    _attempt_rebook_after_decline(meeting)


def _create_declined_notification(meeting: CheckInMeeting) -> None:
    manager: ManagerProfile = meeting.manager
    person_name = meeting.person.name if meeting.person else "your team member"
    message = (
        f"{person_name} has declined the check-in meeting scheduled for "
        f"{meeting.starts_at.strftime('%d %b %Y %H:%M')}. "
        f"A new slot is being searched automatically — you will be notified "
        f"if no slot can be found."
    )
    notif = ManagerNotification.objects.create(
        manager=manager,
        notification_type=ManagerNotification.TYPE_MEETING_DECLINED,
        message=message,
        meeting=meeting,
    )
    logger.debug(
        "decline_sync: created ManagerNotification for meeting %s", meeting.pk
    )
    send_notification_email(notif)


def _attempt_rebook_after_decline(meeting: CheckInMeeting) -> None:
    """Try to book a replacement slot after a decline.

    Looks up the session window that contains the original meeting's date,
    then runs the same auto-booking logic for the (manager, person, window)
    triple.  If a new slot is found it is booked automatically.  If no slot
    is available the existing ``no_slot_found`` notification path fires and
    the manager is alerted to book manually.

    Failures are logged but never propagate — the decline has already been
    recorded and the manager notified.
    """
    try:
        from apps.planner.services.rotation import session_window_for
        from apps.planner.services.auto_booking import _process_single

        manager = meeting.manager
        person = meeting.person

        if manager is None or person is None:
            logger.warning(
                "decline_sync: rebook skipped for meeting %s — missing manager or person",
                meeting.pk,
            )
            return

        organizer = manager.user
        if organizer is None:
            logger.warning(
                "decline_sync: rebook skipped for meeting %s — manager has no linked user",
                meeting.pk,
            )
            return

        window = session_window_for(meeting.starts_at.date())
        if window is None:
            logger.warning(
                "decline_sync: rebook skipped for meeting %s — could not determine session window",
                meeting.pk,
            )
            return

        logger.info(
            "decline_sync: attempting rebook for manager=%s person=%s window=%s "
            "after decline of meeting %s",
            manager.legacy_id,
            getattr(person, "legacy_id", person.pk),
            window.week_start,
            meeting.pk,
        )

        summary: dict = {
            "booked": 0,
            "already_exists": 0,
            "no_slot": 0,
            "error": 0,
            "skipped_no_user": 0,
        }
        _process_single(
            manager,
            person,
            window,
            organizer,
            summary,
            dry_run=False,
            manager_run_bookings=None,  # standalone rebook — no run-level tracker
        )
        logger.info(
            "decline_sync: rebook attempt result for meeting %s — %s",
            meeting.pk,
            summary,
        )

    except Exception:
        logger.exception(
            "decline_sync: unexpected error during rebook attempt for meeting %s",
            meeting.pk,
        )


# ---------------------------------------------------------------------------
# Email sending helper (called by the notifications API after creating a row)
# ---------------------------------------------------------------------------


def send_notification_email(notification: ManagerNotification) -> bool:
    """Send an email for ``notification`` if not already sent.

    Returns True on success, False on failure.  Marks ``email_sent=True`` to
    prevent duplicate sends.
    """
    if notification.email_sent:
        return True

    manager = notification.manager
    recipient = manager.notification_email or (manager.user.email if manager.user else "")
    if not recipient:
        logger.warning(
            "decline_sync: no email address for manager %s — skipping notification email",
            manager.legacy_id,
        )
        return False

    from django.core.mail import send_mail
    from django.conf import settings

    subject_map = {
        ManagerNotification.TYPE_MEETING_DECLINED: "Check-in meeting was declined",
        ManagerNotification.TYPE_NO_SLOT_FOUND: "No available slot for auto-booking",
    }
    subject = subject_map.get(notification.notification_type, "BCT Check-in planner notification")

    try:
        send_mail(
            subject=subject,
            message=notification.message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@blackcapitaltechnology.com"),
            recipient_list=[recipient],
            fail_silently=False,
        )
        notification.email_sent = True
        notification.save(update_fields=["email_sent"])
        logger.info(
            "decline_sync: notification email sent to %s for notification %s",
            recipient,
            notification.pk,
        )
        return True
    except Exception:
        logger.exception(
            "decline_sync: failed to send email for notification %s", notification.pk
        )
        return False
