"""Book Google Calendar meetings for onboarding ``calendar_meeting`` flow steps.

Called manually from the manage API once a manager decides the new hire is
ready to have their onboarding meetings booked.

Entry point
-----------
``book_onboarding_calendar_meetings(person)``
    For every pending ``calendar_meeting`` StepProgress row on the person's
    active onboarding assignment, find an available slot in the next session
    window and book a CheckInMeeting.  After each successful booking the
    StepProgress row is marked completed with the booking details.

Design notes
------------
* The meeting organiser is the manager currently assigned to the person's
  team for the upcoming session window — exactly the same logic as auto-booking.
* We use ``find_available_slot`` + ``create_booking`` from the planner services
  so all rotation validation, buffer enforcement, and Google Calendar
  integration is reused verbatim.
* Failures on individual steps are isolated: one failed step does not prevent
  subsequent steps from being attempted.
* Returns a structured result dict so the API layer can report per-step outcomes
  to the caller.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StepBookingResult:
    step_id: int
    step_order: int
    step_title: str
    success: bool
    meeting_id: int | None = None
    google_event_id: str = ""
    google_html_link: str = ""
    error: str = ""


@dataclass
class BookingRunResult:
    booked: list[StepBookingResult] = field(default_factory=list)
    skipped: list[StepBookingResult] = field(default_factory=list)  # already completed
    failed: list[StepBookingResult] = field(default_factory=list)
    error: str = ""  # top-level error (e.g. no assignment, no manager)

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        def _step(r: StepBookingResult) -> dict:
            d: dict[str, Any] = {
                "stepId": r.step_id,
                "stepOrder": r.step_order,
                "stepTitle": r.step_title,
                "success": r.success,
            }
            if r.meeting_id is not None:
                d["meetingId"] = r.meeting_id
            if r.google_html_link:
                d["googleHtmlLink"] = r.google_html_link
            if r.error:
                d["error"] = r.error
            return d

        return {
            "ok": self.ok,
            "error": self.error,
            "booked": [_step(r) for r in self.booked],
            "skipped": [_step(r) for r in self.skipped],
            "failed": [_step(r) for r in self.failed],
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def book_onboarding_calendar_meetings(person) -> BookingRunResult:
    """Book all pending ``calendar_meeting`` steps for *person*'s active assignment.

    Parameters
    ----------
    person : apps.planner.models.Person
        The employee whose onboarding calendar meetings should be booked.

    Returns
    -------
    BookingRunResult
        Structured result with per-step outcomes.  ``result.error`` is set
        (and the booking loop is skipped) when a prerequisite is missing:
        no OnboardingProfile, no active assignment, no team membership, or
        no manager user with Google credentials.
    """
    result = BookingRunResult()

    # ── 1. Resolve OnboardingProfile + active assignment ────────────────────
    op = getattr(person, "onboarding_profile", None)
    if op is None:
        result.error = "Person has no linked OnboardingProfile."
        logger.warning("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    from apps.onboarding.models import OnboardingAssignment, StepProgress

    assignment = (
        op.assignments.select_related("flow")
        .exclude(status=OnboardingAssignment.STATUS_COMPLETED)
        .order_by("-assigned_at")
        .first()
    )
    if assignment is None:
        result.error = "No active (pending/in_progress) onboarding assignment found."
        logger.warning("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    # ── 2. Find all pending calendar_meeting StepProgress rows ──────────────
    pending_steps = list(
        StepProgress.objects.select_related("step")
        .filter(
            assignment=assignment,
            step__component_type="calendar_meeting",
            status=StepProgress.STATUS_PENDING,
        )
        .order_by("step__order")
    )

    if not pending_steps:
        logger.info(
            "book_onboarding: %s — no pending calendar_meeting steps",
            person.legacy_id,
        )
        return result  # nothing to do, all steps already completed or skipped

    # ── 3. Find person's team + manager via rotation ─────────────────────────
    from apps.planner.services.rotation import (
        _team_for_person,
        get_or_create_session,
        upcoming_session_windows,
    )

    team = _team_for_person(person)
    if team is None:
        result.error = "Person is not assigned to any team (excluding pool)."
        logger.warning("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    windows = upcoming_session_windows(1)
    if not windows:
        result.error = "No upcoming session windows found."
        logger.warning("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    window = windows[0]
    session = get_or_create_session(
        cycle_start=window.cycle_start,
        session_index=window.session_index,
        team=team,
    )
    if session is None:
        result.error = f"No rotation session for team '{team}' in upcoming window."
        logger.warning("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    from apps.planner.models import ManagerProfile

    try:
        manager = ManagerProfile.objects.select_related("user", "person").get(pk=session.manager_id)
    except ManagerProfile.DoesNotExist:
        result.error = f"Manager (pk={session.manager_id}) not found."
        logger.error("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    organizer_user = manager.user
    if organizer_user is None:
        result.error = f"Manager '{manager.legacy_id}' has no linked user account."
        logger.warning("book_onboarding: %s — %s", person.legacy_id, result.error)
        return result

    # ── 4. Book each pending step ────────────────────────────────────────────
    from django.conf import settings

    from apps.planner.services.bookings import (
        BookingError,
        BookingRequest,
        GoogleBookingError,
        create_booking,
    )
    from apps.planner.services.slot_finder import find_available_slot
    from apps.onboarding.services import set_step_progress

    tz_name = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")

    # Track slots booked in this run so the slot-finder respects the buffer
    # even between successive steps (same manager, same window).
    already_booked: list[tuple] = []

    for sp in pending_steps:
        step = sp.step
        duration_minutes: int = step.config.get("duration_minutes", 30)

        step_result = StepBookingResult(
            step_id=step.id,
            step_order=step.order,
            step_title=step.title,
            success=False,
        )

        slot = find_available_slot(
            manager=manager,
            person=person,
            window=window,
            organizer_user=organizer_user,
            duration_minutes=duration_minutes,
            tz_name=tz_name,
            buffer_minutes=30,
            max_per_day=3,
            already_booked=already_booked,
        )

        if slot is None:
            step_result.error = (
                f"No available slot found in window "
                f"{window.week_start} – {window.week_end}."
            )
            logger.info(
                "book_onboarding: no slot for step=%s person=%s window=%s",
                step.order,
                person.legacy_id,
                window.week_start,
            )
            result.failed.append(step_result)
            continue

        req = BookingRequest(
            manager=manager,
            person=person,
            organizer_user=organizer_user,
            starts_at=slot.starts_at,
            duration_minutes=slot.duration_minutes,
            title=step.title or "Check-in samtale",
            agenda=step.description or "",
            timezone=tz_name,
        )

        try:
            meeting = create_booking(req)
        except (BookingError, GoogleBookingError) as exc:
            step_result.error = str(exc)
            logger.warning(
                "book_onboarding: booking failed for step=%s person=%s: %s",
                step.order,
                person.legacy_id,
                exc,
            )
            result.failed.append(step_result)
            continue
        except Exception as exc:
            step_result.error = f"Unexpected error: {exc}"
            logger.exception(
                "book_onboarding: unexpected error for step=%s person=%s",
                step.order,
                person.legacy_id,
            )
            result.failed.append(step_result)
            continue

        # Track this slot for buffer enforcement in subsequent steps.
        from datetime import timedelta

        already_booked.append(
            (slot.starts_at, slot.starts_at + timedelta(minutes=slot.duration_minutes))
        )

        # Mark the StepProgress as completed.
        try:
            set_step_progress(
                assignment=assignment,
                step=step,
                status=StepProgress.STATUS_COMPLETED,
                completion_data={
                    "scheduled_at": meeting.starts_at.isoformat(),
                    "google_event_id": meeting.google_event_id,
                    "html_link": meeting.google_html_link,
                },
                completed_by="system:onboarding_calendar_booking",
            )
        except Exception as exc:
            # Booking is already created — just log so the meeting isn't lost.
            logger.error(
                "book_onboarding: failed to mark StepProgress complete for step=%s "
                "person=%s meeting=%s: %s",
                step.order,
                person.legacy_id,
                meeting.pk,
                exc,
            )

        step_result.success = True
        step_result.meeting_id = meeting.pk
        step_result.google_event_id = meeting.google_event_id
        step_result.google_html_link = meeting.google_html_link
        result.booked.append(step_result)

        logger.info(
            "book_onboarding: booked step=%s meeting=%s for person=%s at %s",
            step.order,
            meeting.pk,
            person.legacy_id,
            slot.starts_at.isoformat(),
        )

    return result
