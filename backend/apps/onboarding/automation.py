"""Runs the onboarding "attach flow" automation: welcome email, calendar
meeting booking, and Slack invite.

Extracted from ``manage_api.assign_flow`` so the exact same automation can
be triggered from two places:

* Immediately, inline in the request/response cycle, when a manager
  attaches a flow with ``scheduled_for`` today or in the past (the
  behaviour this app shipped with).
* Later, headless, by the ``run_scheduled_onboarding`` management command,
  when a manager instead *plans* the flow for a future date — see
  ``OnboardingAssignment.scheduled_for`` / ``scheduled_automation_ran_at``.

Both call sites want the exact same best-effort, per-step-isolated
behaviour and the exact same structured result shape, so it lives here
once rather than being duplicated.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def _send_onboarding_welcome_email(*, person, assignment, requested_by) -> dict:
    """Best-effort: send the combined welcome/calendar-share email.

    Returns a small dict describing the outcome (never raises) so the
    caller can surface it in the response / log it.
    """
    from .welcome_email import send_onboarding_welcome_email

    try:
        send_onboarding_welcome_email(
            person=person, assignment=assignment, requested_by=requested_by
        )
        return {"sent": True}
    except Exception as exc:
        logger.warning(
            "onboarding automation: could not send welcome email for %s: %s",
            person.legacy_id,
            exc,
        )
        return {"sent": False, "error": str(exc)}


def _send_onboarding_slack_invite(*, person, assignment, requested_by) -> dict:
    """Best-effort Slack invite. Returns a plain dict (never raises)."""
    from .slack_invite import send_onboarding_slack_invite

    try:
        result = send_onboarding_slack_invite(
            person=person, assignment=assignment, requested_by=requested_by
        )
        return result.to_dict()
    except Exception as exc:  # defensive — send_onboarding_slack_invite shouldn't raise
        logger.warning(
            "onboarding automation: Slack invite crashed for %s: %s", person.legacy_id, exc
        )
        return {"sent": False, "reason": "error", "error": str(exc)}


def book_onboarding_meetings(person) -> dict:
    """Run the meeting-booking pass and return it as a plain dict."""
    from .calendar_booking import book_onboarding_calendar_meetings

    result = book_onboarding_calendar_meetings(person)
    return result.to_dict()


def run_onboarding_attach_automation(*, person, assignment, requested_by) -> dict:
    """Run the full attach automation for a fresh (or newly-due) assignment.

    Sends the welcome email and Slack invite exactly once — guarded by
    ``assignment.scheduled_automation_ran_at``, which this function sets
    up front so a crashing caller (or an overlapping cron run) can't cause
    a duplicate send. Meeting booking is idempotent on its own (it only
    ever looks at *pending* ``calendar_meeting`` steps), so it isn't
    guarded the same way, and is also always re-attempted for anything
    still unbooked — matching the existing "Book møder" retry behaviour.

    Returns a dict with ``welcomeEmail`` / ``meetings`` / ``slackInvite``
    keys, each a plain outcome dict (never raises).
    """
    from .models import OnboardingAssignment

    automation: dict = {"welcomeEmail": None, "meetings": None, "slackInvite": None}

    already_ran = assignment.scheduled_automation_ran_at is not None
    if not already_ran:
        assignment.scheduled_automation_ran_at = timezone.now()
        assignment.save(update_fields=["scheduled_automation_ran_at", "updated_at"])

        automation["welcomeEmail"] = _send_onboarding_welcome_email(
            person=person, assignment=assignment, requested_by=requested_by
        )
        automation["slackInvite"] = _send_onboarding_slack_invite(
            person=person, assignment=assignment, requested_by=requested_by
        )

    if assignment.status != OnboardingAssignment.STATUS_COMPLETED:
        automation["meetings"] = book_onboarding_meetings(person)

    return automation
