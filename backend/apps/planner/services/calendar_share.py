"""Calendar share request workflow for book check-ins."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.planner.google.calendar_share import send_calendar_share_email
from apps.planner.google.credentials import GoogleCredentialsUnavailable
from apps.planner.models import CalendarShareRequest, Person

User = get_user_model()

COOLDOWN_DAYS = 7


def latest_share_request(*, person: Person, requested_by) -> CalendarShareRequest | None:
    return (
        CalendarShareRequest.objects.filter(person=person, requested_by=requested_by)
        .order_by("-sent_at")
        .first()
    )


def can_send_share_request(
    *, person: Person, requested_by, force: bool = False
) -> tuple[bool, str | None]:
    if not person.email:
        return False, "Person has no email address."
    latest = latest_share_request(person=person, requested_by=requested_by)
    if not latest or not latest.success:
        return True, None
    if force:
        return True, None
    if latest.sent_at >= timezone.now() - timedelta(days=COOLDOWN_DAYS):
        return False, (
            f"A share request was already sent on {latest.sent_at.date().isoformat()}. "
            f"Wait {COOLDOWN_DAYS} days or use force=true."
        )
    return True, None


def send_share_request(
    *,
    person: Person,
    requested_by,
    force: bool = False,
) -> CalendarShareRequest:
    allowed, reason = can_send_share_request(
        person=person, requested_by=requested_by, force=force
    )
    if not allowed:
        raise ValidationError(reason or "Cannot send share request.")

    manager_name = (
        requested_by.get_full_name()
        or getattr(requested_by, "email", "")
        or "Your manager"
    )
    record = CalendarShareRequest(
        person=person,
        requested_by=requested_by,
        channel=CalendarShareRequest.CHANNEL_EMAIL,
    )
    try:
        send_calendar_share_email(
            from_user=requested_by,
            to_email=person.email,
            employee_name=person.name,
            manager_name=manager_name,
        )
    except GoogleCredentialsUnavailable as exc:
        record.success = False
        record.error_message = str(exc)
        record.save()
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        record.success = False
        record.error_message = str(exc)[:500]
        record.save()
        raise ValidationError(f"Could not send email: {exc}") from exc

    record.success = True
    record.save()
    return record


def send_share_requests(
    *,
    person_ids: list[str],
    requested_by,
    force: bool = False,
) -> dict:
    """Send share requests for legacy person ids. Returns summary dict."""
    results = []
    sent = skipped = failed = 0
    for legacy_id in person_ids:
        person = Person.objects.filter(legacy_id=legacy_id).first()
        if person is None:
            failed += 1
            results.append(
                {
                    "person_id": legacy_id,
                    "status": "error",
                    "detail": "Person not found.",
                }
            )
            continue
        allowed, reason = can_send_share_request(
            person=person, requested_by=requested_by, force=force
        )
        if not allowed:
            skipped += 1
            results.append(
                {
                    "person_id": legacy_id,
                    "status": "skipped",
                    "detail": reason,
                }
            )
            continue
        try:
            record = send_share_request(
                person=person, requested_by=requested_by, force=force
            )
            sent += 1
            results.append(
                {
                    "person_id": legacy_id,
                    "status": "sent",
                    "sent_at": record.sent_at.isoformat(),
                }
            )
        except ValidationError as exc:
            failed += 1
            results.append(
                {
                    "person_id": legacy_id,
                    "status": "error",
                    "detail": "; ".join(exc.messages),
                }
            )
    return {
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


def serialize_share_status(*, person: Person, requested_by) -> dict:
    latest = latest_share_request(person=person, requested_by=requested_by)
    allowed, reason = can_send_share_request(
        person=person, requested_by=requested_by, force=False
    )
    return {
        "person_id": person.legacy_id,
        "email": person.email,
        "can_send": allowed,
        "cooldown_reason": reason,
        "last_request": (
            {
                "sent_at": latest.sent_at.isoformat(),
                "success": latest.success,
                "error_message": latest.error_message,
            }
            if latest
            else None
        ),
    }
