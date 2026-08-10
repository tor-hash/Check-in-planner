"""Book Google Calendar meetings for onboarding ``calendar_meeting`` flow steps.

Called automatically right after a flow is attached to an employee, and
again (for whatever is still unbooked) whenever a manager re-attaches the
same flow or clicks the manual "Book møder" retry button — both paths go
through the same entry point below.

Entry point
-----------
``book_onboarding_calendar_meetings(person)``
    For every pending ``calendar_meeting`` StepProgress row on the person's
    active onboarding assignment, resolve that step's organizer, find an
    open slot on the *organizer's own* calendar, and create the event.
    After each successful booking the StepProgress row is marked completed
    with the booking details.

Design notes
------------
* The organizer for a step comes from ``step.config["with_email"]`` — a
  literal address (HR, IT, a buddy, ...) or the sentinel
  ``CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL``, which resolves to
  whoever attached the flow (``OnboardingAssignment.assigned_by``). This
  intentionally has nothing to do with team rotation — unlike the check-in
  planner's auto-booking, onboarding meetings don't require the employee to
  be on a team.
* Slot-finding only looks at the organizer's own calendar
  (``apps.onboarding.slot_finder``), not the employee's — the employee may
  not have shared their calendar yet, and per product decision that's fine;
  it is not a precondition for booking.
* If an organizer hasn't connected Google (or doesn't exist as a user at
  all), that is treated as a hard stop *for that step only* — we don't
  guess or book blind. Other steps (possibly with other organizers) still
  get attempted, and the welcome/calendar-share email to the employee is
  unaffected either way (sent separately, before this runs).
* Meetings are created directly via the Calendar API
  (``apps.planner.google.events.create_checkin_event``) and are not
  reflected as ``CheckInMeeting`` rows — onboarding meetings don't need to
  appear in the planner's regular meeting views. The booking details live
  on the ``StepProgress.completion_data`` for that step.
* Failures on individual steps are isolated: one failed step does not
  prevent subsequent steps (even for a different organizer) from being
  attempted.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)


class OrganizerResolutionError(Exception):
    """Raised when a step's organizer can't be determined or looked up."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StepBookingResult:
    step_id: int
    step_order: int
    step_title: str
    organizer_email: str = ""
    success: bool = False
    google_event_id: str = ""
    google_html_link: str = ""
    scheduled_at: str = ""
    error: str = ""


@dataclass
class BookingRunResult:
    booked: list[StepBookingResult] = field(default_factory=list)
    failed: list[StepBookingResult] = field(default_factory=list)
    error: str = ""  # top-level error (e.g. no assignment at all)

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, Any]:
        def _step(r: StepBookingResult) -> dict:
            d: dict[str, Any] = {
                "stepId": r.step_id,
                "stepOrder": r.step_order,
                "stepTitle": r.step_title,
                "organizerEmail": r.organizer_email,
                "success": r.success,
            }
            if r.google_html_link:
                d["googleHtmlLink"] = r.google_html_link
            if r.scheduled_at:
                d["scheduledAt"] = r.scheduled_at
            if r.error:
                d["error"] = r.error
            return d

        return {
            "ok": self.ok,
            "error": self.error,
            "booked": [_step(r) for r in self.booked],
            "failed": [_step(r) for r in self.failed],
        }


# ---------------------------------------------------------------------------
# Organizer resolution
# ---------------------------------------------------------------------------


def _resolve_organizer(*, step_config: dict, assignment) -> tuple[Any, str]:
    """Return (organizer_user, organizer_email) for a calendar_meeting step.

    Raises ``OrganizerResolutionError`` if the organizer can't be
    determined or doesn't correspond to a known user account.
    """
    from django.contrib.auth import get_user_model

    from apps.onboarding.components import CalendarMeetingComponent

    with_email = (step_config or {}).get("with_email", "")

    if with_email == CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL:
        assigned_by = assignment.assigned_by
        if assigned_by is None or not assigned_by.email:
            raise OrganizerResolutionError(
                "This step should be booked with whoever assigned the flow, but "
                "no assigning manager is on record for this assignment. "
                "Re-attach the flow to set it."
            )
        return assigned_by, assigned_by.email

    email = (with_email or "").strip()
    if not email:
        raise OrganizerResolutionError("Step has no organizer email configured.")

    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise OrganizerResolutionError(
            f"No user account found for organizer '{email}'."
        )
    return user, email


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
        Structured result with per-step outcomes. ``result.error`` is only
        set when there's no onboarding profile or no active assignment at
        all — anything organizer-specific (missing Google connection,
        unknown user, no free slot) is reported per-step instead.
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
        op.assignments.select_related("flow", "assigned_by")
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

    # ── 3. Book each pending step against its own organizer ─────────────────
    from django.conf import settings

    from apps.onboarding.services import set_step_progress
    from apps.onboarding.slot_finder import find_organizer_slot
    from apps.planner.google.credentials import GoogleCredentialsUnavailable
    from apps.planner.google.events import create_checkin_event

    tz_name = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")

    # Track slots booked in this run per organizer, so the slot-finder
    # respects the buffer between successive steps for the *same* organizer.
    # Different organizers' calendars are independent.
    already_booked_by_organizer: dict[str, list[tuple]] = {}

    for sp in pending_steps:
        step = sp.step
        duration_minutes: int = step.config.get("duration_minutes", 30)

        step_result = StepBookingResult(
            step_id=step.id,
            step_order=step.order,
            step_title=step.title,
        )

        try:
            organizer_user, organizer_email = _resolve_organizer(
                step_config=step.config, assignment=assignment
            )
        except OrganizerResolutionError as exc:
            step_result.error = str(exc)
            logger.warning(
                "book_onboarding: organizer resolution failed for step=%s person=%s: %s",
                step.order, person.legacy_id, exc,
            )
            result.failed.append(step_result)
            continue

        step_result.organizer_email = organizer_email

        try:
            slot = find_organizer_slot(
                organizer_user=organizer_user,
                organizer_email=organizer_email,
                duration_minutes=duration_minutes,
                tz_name=tz_name,
                buffer_minutes=30,
                already_booked=already_booked_by_organizer.get(organizer_email, []),
            )
        except GoogleCredentialsUnavailable as exc:
            step_result.error = (
                f"{organizer_email} hasn't connected Google Calendar yet. "
                f"Ask them to sign in once, then retry booking this step. ({exc})"
            )
            logger.warning(
                "book_onboarding: no Google credentials for organizer=%s "
                "(step=%s person=%s): %s",
                organizer_email, step.order, person.legacy_id, exc,
            )
            result.failed.append(step_result)
            continue
        except Exception as exc:
            step_result.error = f"Could not check {organizer_email}'s calendar: {exc}"
            logger.exception(
                "book_onboarding: slot lookup failed for step=%s person=%s organizer=%s",
                step.order, person.legacy_id, organizer_email,
            )
            result.failed.append(step_result)
            continue

        if slot is None:
            step_result.error = f"No available slot found on {organizer_email}'s calendar."
            logger.info(
                "book_onboarding: no slot for step=%s person=%s organizer=%s",
                step.order, person.legacy_id, organizer_email,
            )
            result.failed.append(step_result)
            continue

        try:
            created = create_checkin_event(
                organizer_user=organizer_user,
                attendee_email=person.email or None,
                starts_at=slot.starts_at,
                duration_minutes=slot.duration_minutes,
                title=step.title or "Onboarding-møde",
                agenda=step.description or "",
                timezone=tz_name,
            )
        except Exception as exc:
            step_result.error = f"Google rejected the event: {exc}"
            logger.exception(
                "book_onboarding: event creation failed for step=%s person=%s organizer=%s",
                step.order, person.legacy_id, organizer_email,
            )
            result.failed.append(step_result)
            continue

        # Track this slot for buffer enforcement against later steps with
        # the same organizer, in this same run.
        already_booked_by_organizer.setdefault(organizer_email, []).append(
            (slot.starts_at, slot.starts_at + timedelta(minutes=slot.duration_minutes))
        )

        # Mark the StepProgress as completed.
        try:
            set_step_progress(
                assignment=assignment,
                step=step,
                status=StepProgress.STATUS_COMPLETED,
                completion_data={
                    "scheduled_at": slot.starts_at.isoformat(),
                    "google_event_id": created.google_event_id,
                    "html_link": created.html_link,
                    "organizer_email": organizer_email,
                },
                completed_by="system:onboarding_calendar_booking",
            )
        except Exception as exc:
            # The Google event already exists — just log so it isn't lost.
            logger.error(
                "book_onboarding: failed to mark StepProgress complete for step=%s "
                "person=%s event=%s: %s",
                step.order, person.legacy_id, created.google_event_id, exc,
            )

        step_result.success = True
        step_result.google_event_id = created.google_event_id
        step_result.google_html_link = created.html_link
        step_result.scheduled_at = slot.starts_at.isoformat()
        result.booked.append(step_result)

        logger.info(
            "book_onboarding: booked step=%s event=%s for person=%s with %s at %s",
            step.order, created.google_event_id, person.legacy_id,
            organizer_email, slot.starts_at.isoformat(),
        )

    return result
