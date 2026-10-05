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
* Who a meeting is with comes from ``step.config["participants"]`` — a
  list of literal addresses and/or the role sentinels ``leder``, ``buddy``
  and ``assigning_manager`` (see ``CalendarMeetingComponent``). Older steps
  with a single ``with_email`` are read the same way.
* When ``settings.ONBOARDING_SCHEDULER_EMAIL`` is set, that shared mailbox
  owns (organizes) every onboarding event and all participants plus the
  employee are invited. Otherwise the first participant owns the event in
  their own calendar, as before.
* Slot-finding checks every participant's calendar and picks a time
  they're all free (``apps.onboarding.slot_finder``), not the employee's — the employee may
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
from datetime import date, datetime, timedelta
from typing import Any

from .holidays_dk import is_working_day, next_working_day

logger = logging.getLogger(__name__)


class OrganizerResolutionError(Exception):
    """Raised when a step's organizer can't be determined or looked up."""


DAY_UNIT_CALENDAR = "calendar"
DAY_UNIT_BUSINESS = "business"


def _business_day_offset(start: date, offset: int, country: str = "DK") -> date:
    """Return the date ``offset`` *working days* after ``start``.

    ``start`` itself is working day 0 — unless it's a weekend or a Danish
    holiday, in which case day 0 rolls forward to the next working day
    first. Every subsequent day skips weekends and holidays entirely
    (see ``holidays_dk``), which is what makes a "Week 1 · Mon/Tue/Wed/
    Thu/Fri" template slide cleanly to line up with any real start date:
    start on a Thursday and day_offset 0/1/2/3/4 land on Thu/Fri/Mon/Tue/Wed.
    """
    d = next_working_day(start, country)
    remaining = offset
    while remaining > 0:
        d += timedelta(days=1)
        if is_working_day(d, country):
            remaining -= 1
    return d


def _calendar_day_offset(start: date, offset: int, country: str = "DK") -> date:
    """Return ``start`` + ``offset`` plain calendar days.

    If that lands on a weekend or a Danish holiday it rolls forward to the
    next working day — e.g. "30 days after start" on a Saturday becomes
    the following Monday (or Tuesday, if Monday is 2. påskedag).
    """
    return next_working_day(start + timedelta(days=offset), country)


def scheduled_day_for_step(
    start: date, offset: int, unit: str | None, country: str = "DK"
) -> date:
    """Day a step with ``day_offset``/``day_unit`` should be booked on.

    A missing ``unit`` means working days — that's how every step saved
    before ``day_unit`` existed was meant to be read.
    """
    if unit == DAY_UNIT_CALENDAR:
        return _calendar_day_offset(start, offset, country)
    return _business_day_offset(start, offset, country)


def _parse_time_of_day(value: str | None):
    if not value:
        return None
    try:
        hour_str, minute_str = value.split(":", 1)
        return datetime.strptime(f"{int(hour_str):02d}:{int(minute_str):02d}", "%H:%M").time()
    except (ValueError, TypeError):
        logger.warning("book_onboarding: ignoring unparsable time_of_day=%r", value)
        return None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StepBookingResult:
    step_id: int
    step_order: int
    step_title: str
    organizer_email: str = ""
    participant_emails: list[str] = field(default_factory=list)
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
                "participantEmails": r.participant_emails,
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

    ``with_email`` on the step config is one of: a literal email address, the
    ``assigning_manager`` sentinel (resolves to ``assignment.assigned_by`` —
    whoever attached the flow), the ``leder``/``buddy`` sentinels (resolve to
    the ``leder_email``/``buddy_email`` snapshotted onto the assignment at
    attach time — see ``services.attach_flow``), or blank — which, per
    product rule, defaults to ``leder`` (every employee is required to have
    one chosen before a flow can be attached, so this is always resolvable).

    Raises ``OrganizerResolutionError`` if the organizer can't be
    determined or doesn't correspond to a known user account.

    Only used when no scheduler mailbox is configured: the first
    participant then owns the event, as before.
    """
    from apps.onboarding.components import CalendarMeetingComponent

    token = CalendarMeetingComponent.participant_tokens(step_config)[0]
    if token == CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL:
        assigned_by = assignment.assigned_by
        if assigned_by is None or not assigned_by.email:
            raise OrganizerResolutionError(
                "This step should be booked with whoever assigned the flow, but "
                "no assigning manager is on record for this assignment. "
                "Re-attach the flow to set it."
            )
        return assigned_by, assigned_by.email
    email = _resolve_participant_email(token, assignment)
    return _user_for_email(email), email


def _user_for_email(email: str):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(email__iexact=email).first()
    if user is None:
        raise OrganizerResolutionError(f"No user account found for organizer '{email}'.")
    return user


def _resolve_participant_email(token: str, assignment) -> str:
    """Turn one participant token (role sentinel or address) into an email."""
    from apps.onboarding.components import CalendarMeetingComponent

    token = (token or "").strip()
    if token == CalendarMeetingComponent.ASSIGNING_MANAGER_SENTINEL:
        assigned_by = assignment.assigned_by
        email = (getattr(assigned_by, "email", "") or "").strip()
        if not email:
            raise OrganizerResolutionError(
                "This step should be booked with whoever assigned the flow, but "
                "no assigning manager is on record for this assignment. "
                "Re-attach the flow to set it."
            )
        return email
    if token in ("", CalendarMeetingComponent.LEDER_SENTINEL):
        email = (assignment.leder_email or "").strip()
        if not email:
            raise OrganizerResolutionError(
                "This step should be booked with the employee's leder, but no "
                "leder is on record for this assignment. Re-attach the flow "
                "with a leder selected to set it."
            )
        return email
    if token == CalendarMeetingComponent.BUDDY_SENTINEL:
        email = (assignment.buddy_email or "").strip()
        if not email:
            raise OrganizerResolutionError(
                "This step should be booked with the employee's buddy, but no "
                "buddy is on record for this assignment. Re-attach the flow "
                "with a buddy selected to set it."
            )
        return email
    return token


def _resolve_participants(*, step_config: dict, assignment, employee_email: str) -> list[str]:
    """All participant emails for a step (deduped, employee excluded).

    Raises ``OrganizerResolutionError`` if any participant can't be
    resolved — e.g. a "leder + buddy" meeting for an employee without a
    buddy. Booking it without one of the people it's meant for would be
    worse than failing loudly.
    """
    from apps.onboarding.components import CalendarMeetingComponent

    emails: list[str] = []
    seen = {(employee_email or "").strip().lower()} - {""}
    for token in CalendarMeetingComponent.participant_tokens(step_config):
        email = _resolve_participant_email(token, assignment)
        if email.lower() not in seen:
            seen.add(email.lower())
            emails.append(email)
    if not emails:
        raise OrganizerResolutionError("This meeting has no participants besides the employee.")
    return emails


EVENT_TITLE_PREFIX = "Onboarding: "


def onboarding_event_title(title: str | None) -> str:
    """Calendar title for an onboarding meeting: always "Onboarding: <title>",
    so these meetings are easy to spot in everyone's calendar. Not doubled
    if the step title already starts with it."""
    title = (title or "").strip() or "Onboarding-møde"
    if title.lower().startswith(EVENT_TITLE_PREFIX.strip().lower()):
        return title
    return EVENT_TITLE_PREFIX + title


def scheduler_email() -> str:
    """The system account's email, or '' when there is none.

    Set on Onboarding → Indstillinger (``OnboardingSettings.system_email``).
    Until it's been set there, falls back to ``ONBOARDING_SCHEDULER_EMAIL``.
    """
    from django.conf import settings

    from .models import OnboardingSettings

    configured = (
        OnboardingSettings.objects.filter(singleton_key="default")
        .values_list("system_email", flat=True)
        .first()
    )
    if configured is not None:
        return configured.strip()
    return (getattr(settings, "ONBOARDING_SCHEDULER_EMAIL", "") or "").strip()


def scheduler_user():
    """User for the scheduler mailbox, or None when no scheduler is configured.

    Raises ``OrganizerResolutionError`` when one is configured but that
    account has never signed in to the planner (so there's no user and no
    Google connection to act through).
    """
    email = scheduler_email()
    if not email:
        return None
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(email__iexact=email).first()
    if user is None:
        raise OrganizerResolutionError(
            f"The system account {email} hasn't signed in to the planner yet. "
            "Sign in once with that Google account (or pick another system "
            "account under Onboarding → Indstillinger), then retry."
        )
    return user


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
        op.assignments.select_related("flow", "assigned_by", "profile")
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
    # Denmark/Norway: decides public holidays and the language of the
    # meeting title/agenda (see countries.py).
    country = assignment.country or "DK"

    # Track slots booked in this run per person, so the slot-finder
    # respects the buffer between successive meetings involving the same
    # leder/buddy/etc. Unrelated people's calendars are independent.
    already_booked_by_email: dict[str, list[tuple]] = {}

    # Resolve the shared scheduler mailbox once. If it's configured but
    # unusable, every step fails with the same clear message.
    try:
        scheduler = scheduler_user()
    except OrganizerResolutionError as exc:
        for sp in pending_steps:
            result.failed.append(
                StepBookingResult(
                    step_id=sp.step.id,
                    step_order=sp.step.order,
                    step_title=sp.step.title,
                    organizer_email=scheduler_email(),
                    error=str(exc),
                )
            )
        logger.warning("book_onboarding: %s — %s", person.legacy_id, exc)
        return result

    for sp in pending_steps:
        step = sp.step
        duration_minutes: int = step.config.get("duration_minutes", 30)

        step_result = StepBookingResult(
            step_id=step.id,
            step_order=step.order,
            step_title=step.title,
        )

        # Who the meeting is with, and whose calendar owns the event. With a
        # scheduler mailbox configured, the scheduler owns every event and
        # all participants are invited; otherwise the first participant
        # owns it (the original behavior).
        try:
            participants = _resolve_participants(
                step_config=step.config,
                assignment=assignment,
                employee_email=person.email or "",
            )
            if scheduler is not None:
                organizer_user, organizer_email = scheduler, scheduler.email
            else:
                organizer_user, organizer_email = _resolve_organizer(
                    step_config=step.config, assignment=assignment
                )
        except OrganizerResolutionError as exc:
            step_result.error = str(exc)
            logger.warning(
                "book_onboarding: participant resolution failed for step=%s person=%s: %s",
                step.order, person.legacy_id, exc,
            )
            result.failed.append(step_result)
            continue

        step_result.organizer_email = organizer_email
        step_result.participant_emails = list(participants)

        # Busy-check every participant. The scheduler itself is left out
        # unless it's also a participant -- it owns every onboarding event,
        # so its own calendar would otherwise block everything.
        busy_emails = list(participants)
        if scheduler is None and organizer_email.lower() not in {e.lower() for e in busy_emails}:
            busy_emails.insert(0, organizer_email)
        already_booked = [
            interval
            for e in busy_emails
            for interval in already_booked_by_email.get(e.lower(), [])
        ]

        # The employee's start date is day 0: nothing is ever booked before
        # it, whether the flow was sent now or on the start date. A step
        # with "days after start date" lands that many days in (see
        # scheduled_day_for_step); a step without it starts on the start
        # date itself. Only with no start date on file at all does booking
        # fall back to "first free slot from today".
        search_from = None
        day_offset = step.config.get("day_offset")
        start_date = assignment.profile.start_date
        if start_date is not None:
            search_from = scheduled_day_for_step(
                start_date, day_offset or 0, step.config.get("day_unit"), country
            )
        preferred_time = _parse_time_of_day(step.config.get("time_of_day"))

        who = ", ".join(participants)
        try:
            slot = find_organizer_slot(
                organizer_user=organizer_user,
                organizer_email=organizer_email,
                busy_emails=busy_emails,
                duration_minutes=duration_minutes,
                tz_name=tz_name,
                buffer_minutes=30,
                already_booked=already_booked,
                search_from=search_from,
                preferred_time=preferred_time,
                country=country,
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
            step_result.error = f"Could not check calendars ({who}): {exc}"
            logger.exception(
                "book_onboarding: slot lookup failed for step=%s person=%s organizer=%s",
                step.order, person.legacy_id, organizer_email,
            )
            result.failed.append(step_result)
            continue

        if slot is None:
            step_result.error = f"No time found where everyone is free ({who})."
            logger.info(
                "book_onboarding: no slot for step=%s person=%s participants=%s",
                step.order, person.legacy_id, who,
            )
            result.failed.append(step_result)
            continue

        attendees = [
            e for e in [*participants, person.email or ""]
            if e and e.lower() != organizer_email.lower()
        ]
        try:
            created = create_checkin_event(
                organizer_user=organizer_user,
                attendee_email=None,
                attendee_emails=attendees,
                starts_at=slot.starts_at,
                duration_minutes=slot.duration_minutes,
                title=onboarding_event_title(step.title_for(country)),
                agenda=step.description_for(country) or "",
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

        # Track this slot for buffer enforcement against later steps that
        # share any of these people, in this same run.
        booked_interval = (
            slot.starts_at, slot.starts_at + timedelta(minutes=slot.duration_minutes)
        )
        for e in busy_emails:
            already_booked_by_email.setdefault(e.lower(), []).append(booked_interval)

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
                    "participant_emails": participants,
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
