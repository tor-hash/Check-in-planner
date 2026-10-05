"""Business logic for the onboarding app.

All write paths are wrapped in atomic transactions. Functions raise
``django.core.exceptions.ValidationError`` for caller mistakes (the API
layer turns those into 400/404) and ``DoesNotExist`` for missing rows.
"""
from __future__ import annotations

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .components import get_component
from .countries import DEFAULT_COUNTRY
from .seed_baseline import DEFAULT_FLOW_SLUG, ensure_default_flow
from .models import (
    FlowStep,
    OnboardingAssignment,
    OnboardingFlow,
    OnboardingProfile,
    StepProgress,
    WelcomeEmailTemplate,
)

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_default_flow() -> OnboardingFlow:
    """Return the active default flow.

    Falls back to the only active flow when ``is_default`` isn't set on
    any row (helps when there's just one flow in v1).
    """
    flow = OnboardingFlow.objects.filter(is_default=True, is_active=True).first()
    if flow is not None:
        return flow
    active = list(OnboardingFlow.objects.filter(is_active=True)[:2])
    if len(active) == 1:
        return active[0]
    raise OnboardingFlow.DoesNotExist(
        "No default onboarding flow configured. Mark one OnboardingFlow as is_default."
    )


def get_flow_by_slug(slug: str) -> OnboardingFlow:
    return OnboardingFlow.objects.get(slug=slug, is_active=True)


def get_flow_by_slug_any(slug: str) -> OnboardingFlow:
    return OnboardingFlow.objects.get(slug=slug)


class StepInUseError(ValidationError):
    """Raised when a step cannot be deleted because assignments reference it."""


# ---------------------------------------------------------------------------
# Flow template management (manager UI)
# ---------------------------------------------------------------------------


def _validate_step_config(component_type: str, config: dict[str, Any]) -> None:
    get_component(component_type).validate_config(config)


@transaction.atomic
def create_flow(*, data: dict[str, Any]) -> OnboardingFlow:
    slug = data["slug"]
    if OnboardingFlow.objects.filter(slug=slug).exists():
        raise ValidationError(f"A flow with slug '{slug}' already exists.")
    flow = OnboardingFlow.objects.create(
        slug=slug,
        name=data["name"],
        description=data.get("description") or "",
        is_default=data.get("is_default", False),
        is_active=data.get("is_active", True),
    )
    return flow


@transaction.atomic
def update_flow(flow: OnboardingFlow, *, data: dict[str, Any]) -> OnboardingFlow:
    if "name" in data:
        flow.name = data["name"]
    if "description" in data:
        flow.description = data["description"]
    if "is_default" in data:
        flow.is_default = data["is_default"]
    if "is_active" in data:
        flow.is_active = data["is_active"]
    flow.save()
    return flow


@transaction.atomic
def delete_flow(flow: OnboardingFlow) -> dict[str, Any]:
    """Soft-delete when assignments exist; hard-delete otherwise."""
    has_assignments = OnboardingAssignment.objects.filter(flow=flow).exists()
    if has_assignments:
        flow.is_active = False
        flow.save(update_fields=["is_active", "updated_at"])
        return {"deleted": False, "deactivated": True, "slug": flow.slug}
    flow.delete()
    return {"deleted": True, "deactivated": False, "slug": flow.slug}


@transaction.atomic
def create_step(flow: OnboardingFlow, *, data: dict[str, Any]) -> FlowStep:
    _validate_step_config(data["component_type"], data["config"])
    if FlowStep.objects.filter(flow=flow, order=data["order"]).exists():
        raise ValidationError(f"Step order {data['order']} is already used in this flow.")
    return FlowStep.objects.create(
        flow=flow,
        order=data["order"],
        component_type=data["component_type"],
        title=data["title"],
        description=data.get("description") or "",
        title_no=data.get("title_no") or "",
        description_no=data.get("description_no") or "",
        config=data["config"],
        is_required=data["is_required"],
    )


@transaction.atomic
def update_step(flow: OnboardingFlow, step_id: int, *, data: dict[str, Any]) -> FlowStep:
    step = FlowStep.objects.get(pk=step_id, flow=flow)
    new_order = data["order"]
    if new_order != step.order:
        conflict = FlowStep.objects.filter(flow=flow, order=new_order).exclude(pk=step.pk).first()
        if conflict is not None:
            raise ValidationError(f"Step order {new_order} is already used in this flow.")
    _validate_step_config(data["component_type"], data["config"])
    step.order = new_order
    step.component_type = data["component_type"]
    step.title = data["title"]
    step.description = data.get("description") or ""
    if "title_no" in data:
        step.title_no = data["title_no"] or ""
    if "description_no" in data:
        step.description_no = data["description_no"] or ""
    step.config = data["config"]
    step.is_required = data["is_required"]
    step.save()
    return step


@transaction.atomic
def delete_step(flow: OnboardingFlow, step_id: int) -> None:
    step = FlowStep.objects.get(pk=step_id, flow=flow)
    if StepProgress.objects.filter(step=step).exists():
        raise StepInUseError(
            "This step cannot be deleted because employees are already assigned to it. "
            "Edit the step instead, or wait until no in-flight onboardings reference it."
        )
    step.delete()


@transaction.atomic
def reorder_steps(flow: OnboardingFlow, ordered_step_ids: list[int]) -> OnboardingFlow:
    steps = list(FlowStep.objects.filter(flow=flow).order_by("order"))
    existing_ids = {s.id for s in steps}
    if set(ordered_step_ids) != existing_ids:
        raise ValidationError("step_ids must list every step in this flow exactly once.")
    id_to_step = {s.id: s for s in steps}
    # Two-phase update avoids unique (flow, order) collisions while swapping.
    for idx, step_id in enumerate(ordered_step_ids, start=1):
        step = id_to_step[step_id]
        step.order = idx + 10_000
        step.save(update_fields=["order", "updated_at"])
    for idx, step_id in enumerate(ordered_step_ids, start=1):
        step = id_to_step[step_id]
        step.order = idx
        step.save(update_fields=["order", "updated_at"])
    return flow


# ---------------------------------------------------------------------------
# Employee creation
# ---------------------------------------------------------------------------
#
# Creating an employee/profile is deliberately decoupled from attaching an
# onboarding flow. Attaching a flow (``attach_flow`` below) is the one
# action that should trigger the flow-attach automation (welcome email,
# calendar booking, Slack invite) — it always requires an identified acting
# user (``assigned_by``), which a bare employee-creation call doesn't have.
# See ``manage_api.assign_flow`` for the only place that automation runs.


def _ensure_user(*, email: str, erp_id: str, first_name: str, last_name: str):
    """Create-or-reuse the Django user for this onboardee.

    The user is created ``is_active=False`` with an unusable password so
    they can never authenticate. If a user with this email already exists
    (e.g. the email is recycled, or this row was created manually), we
    reuse them rather than blowing up.
    """
    User = get_user_model()
    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        return user

    username = erp_id
    if User.objects.filter(username=username).exists():
        username = f"{erp_id}-{secrets.token_hex(4)}"
    user = User.objects.create_user(
        username=username,
        email=email,
        password=None,
        first_name=first_name,
        last_name=last_name,
    )
    user.set_unusable_password()
    user.is_active = False
    user.save(update_fields=["password", "is_active"])
    return user


def _link_person_if_unlinked(profile: OnboardingProfile) -> None:
    """Link this profile to its matching planner ``Person`` — creating one if needed.

    Employees are often added to the check-in planner (``Person``) before
    they're ever provisioned into onboarding. When that happens, the
    ``erp_employee_id`` used to provision them is, by convention, the
    person's ``legacy_id`` (see ``manage_api.assign_flow`` and the
    "+ Ny medarbejder" flow in ``employees-editor.js``, which pre-fills and
    locks the ERP id from ``person.legacy_id`` whenever one already
    exists). In that case we just link the existing, unlinked record.

    But "+ Ny medarbejder" also allows creating an employee with *no* prior
    planner roster entry at all — in that case there's no ``Person`` to
    link, so we create one from the profile's own fields instead of
    leaving the profile permanently orphaned. Without this, such an
    employee would never appear in any ``Person``-backed view (the
    Employees tab list itself, the main planner roster, leder/buddy
    dropdowns elsewhere) — and setting their leder/buddy right after
    creation, from the employee editor, would 404 with "Person not found"
    (see ``manage_api.person_roles``) since there'd be no ``Person`` row
    yet to update.

    A ``Person`` already linked to a *different* profile is left alone.
    Never raises when the planner app isn't installed.
    """
    try:
        from apps.planner.models import Person
    except Exception:  # pragma: no cover - planner app always installed in practice
        return

    relinked = Person.objects.filter(
        legacy_id=profile.erp_employee_id, onboarding_profile__isnull=True
    ).update(onboarding_profile=profile)
    if relinked:
        return
    if Person.objects.filter(legacy_id=profile.erp_employee_id).exists():
        return  # already linked to a different profile — leave it alone

    name = f"{profile.first_name} {profile.last_name}".strip() or profile.erp_employee_id
    Person.objects.create(
        legacy_id=profile.erp_employee_id,
        name=name,
        title=profile.position or "",
        email=profile.user.email or "",
        onboarding_profile=profile,
    )


@transaction.atomic
def create_employee(*, data: dict[str, Any]) -> tuple[OnboardingProfile, bool]:
    """Create or upsert an employee's ``OnboardingProfile``. No flow attached.

    Returns ``(profile, created)`` where ``created`` is True only when a
    brand-new profile was created (so the caller can return 201 vs 200).
    Idempotent on ``erp_employee_id`` — a replay returns the existing
    profile untouched.
    """
    profile = OnboardingProfile.objects.filter(erp_employee_id=data["erp_employee_id"]).first()
    if profile is not None:
        # Idempotent replay of a profile created before _link_person_if_unlinked
        # existed (or before it created rather than just linked) would
        # otherwise stay orphaned forever — this call is itself idempotent,
        # so it's safe (and necessary) to repeat here.
        _link_person_if_unlinked(profile)
        return profile, False

    user = _ensure_user(
        email=data["email"],
        erp_id=data["erp_employee_id"],
        first_name=data.get("first_name") or "",
        last_name=data.get("last_name") or "",
    )
    profile = OnboardingProfile.objects.create(
        user=user,
        erp_employee_id=data["erp_employee_id"],
        first_name=data.get("first_name") or "",
        last_name=data.get("last_name") or "",
        position=data.get("position") or "",
        department=data.get("department") or "",
        start_date=data.get("start_date"),
        country=data.get("country") or DEFAULT_COUNTRY,
    )
    _link_person_if_unlinked(profile)
    return profile, True


@transaction.atomic
def provision_employee_with_default_flow(
    *, data: dict[str, Any]
) -> tuple[OnboardingProfile, bool, bool]:
    """Ensure the default flow *template* exists, then create/upsert the employee.

    Does **not** attach the default flow to the employee — attaching is a
    separate, deliberate action (see ``attach_flow``). This only guarantees
    there's at least one flow template available for a manager to pick from
    afterwards. Returns ``(profile, employee_created, default_flow_created)``.
    """
    flow, flow_created = ensure_default_flow()
    profile, employee_created = create_employee(data=data)
    return profile, employee_created, flow_created


@transaction.atomic
def attach_flow(
    *,
    profile: OnboardingProfile,
    flow: OnboardingFlow,
    requested_by,
    leder=None,
    buddy=None,
    scheduled_for=None,
    country: str | None = None,
    welcome_email_template=None,
) -> tuple[OnboardingAssignment, bool]:
    """Attach (or schedule) ``flow`` to ``profile`` — the one deliberate

    "attach" action. Idempotent on ``(profile, flow)``: replaying returns
    the existing assignment unchanged — except while it's still only
    *planned* (``scheduled_automation_ran_at`` unset), where the new
    leder/buddy/date/country/template replace the old ones. ``requested_by`` is recorded as
    ``assigned_by`` the first time (backfilled on replay if it was never
    set, e.g. the assignment originated some other way) since it drives the
    welcome-email sender and "assigning_manager" meeting organizer
    resolution.

    ``leder`` / ``buddy`` (planner ``Person`` instances, or ``None``) are
    snapshotted onto ``leder_name``/``leder_email``/``buddy_name``/
    ``buddy_email`` the first time only — locked in alongside the welcome
    email, which only ever sends once. ``scheduled_for`` (a ``date``,
    defaults to today when omitted) is likewise only set the first time,
    as are ``country`` (defaults to the profile's) and
    ``welcome_email_template`` (``None`` = default for that language);
    see the ``OnboardingAssignment.scheduled_for`` field docstring for what
    it drives.

    This function only creates the assignment + step-progress rows. It does
    **not** run the attach automation (welcome email / calendar booking /
    Slack invite) or the pre-flight checks that can block an attach — those
    live in ``manage_api.assign_flow`` / ``automation.run_onboarding_attach_automation``.
    Keeping them out of here keeps this function usable from tests and any
    future caller without dragging in Google/Slack side effects.

    Returns ``(assignment, is_new)``.
    """
    assignment = OnboardingAssignment.objects.filter(profile=profile, flow=flow).first()
    is_new = assignment is None
    if is_new:
        assignment = _create_assignment_with_progress(profile=profile, flow=flow)
        assignment.buddy_name = buddy.name if buddy else ""
        assignment.buddy_email = buddy.email if buddy else ""
        assignment.leder_name = leder.name if leder else ""
        assignment.leder_email = leder.email if leder else ""
        assignment.scheduled_for = scheduled_for or timezone.localdate()
        assignment.country = country or profile.country or DEFAULT_COUNTRY
        assignment.welcome_email_template = welcome_email_template
        assignment.save(
            update_fields=[
                "buddy_name",
                "buddy_email",
                "leder_name",
                "leder_email",
                "scheduled_for",
                "country",
                "welcome_email_template",
                "updated_at",
            ]
        )

    elif assignment.scheduled_automation_ran_at is None:
        # Planned but not started yet (nothing sent, nothing booked): the
        # manager is re-planning it, so take the dialog's latest values —
        # e.g. switching from "on the start date" to "send now".
        if buddy is not None:
            assignment.buddy_name, assignment.buddy_email = buddy.name, buddy.email
        if leder is not None:
            assignment.leder_name, assignment.leder_email = leder.name, leder.email
        if scheduled_for is not None:
            assignment.scheduled_for = scheduled_for
        if country:
            assignment.country = country
        assignment.welcome_email_template = welcome_email_template
        assignment.save(
            update_fields=[
                "buddy_name",
                "buddy_email",
                "leder_name",
                "leder_email",
                "scheduled_for",
                "country",
                "welcome_email_template",
                "updated_at",
            ]
        )

    if assignment.assigned_by_id is None:
        assignment.assigned_by = requested_by
        assignment.save(update_fields=["assigned_by", "updated_at"])

    return assignment, is_new


def get_profile_by_erp_id(erp_id: str) -> OnboardingProfile:
    return OnboardingProfile.objects.select_related("user").get(erp_employee_id=erp_id)


def get_latest_assignment(profile: OnboardingProfile) -> OnboardingAssignment | None:
    return (
        OnboardingAssignment.objects.select_related("flow")
        .filter(profile=profile)
        .order_by("-assigned_at")
        .first()
    )


def list_profiles_by_email(*, email: str) -> list[OnboardingProfile]:
    """Return every onboarding profile whose Django user has ``email``.

    Matches by login email, not the (sometimes empty/stale) planner
    ``Person.email`` — same as before. Includes profiles with no flow
    attached yet; use ``serialize_employee_state`` to render each.
    """
    return list(
        OnboardingProfile.objects.select_related("user").filter(user__email__iexact=email)
    )


def _sync_linked_person_identity(profile: OnboardingProfile) -> None:
    """Keep an already-linked planner ``Person``'s identity fields in sync
    with the employee's current ``OnboardingProfile``/``User`` data.

    ``_link_person_if_unlinked`` only ever *creates* a ``Person`` from these
    fields the first time a profile gets linked — by design, it never
    touches an already-linked ``Person`` again (see its docstring: "A
    Person already linked to a different profile is left alone"). That's
    correct for a Person that predates onboarding, but it means editing
    this employee's e-mail/name/position from the employee editor *after*
    the initial link silently stopped updating the Person record — while
    welcome-email sending and calendar-meeting booking both read the
    recipient/attendee address straight off ``Person.email``, not off the
    profile or user (see ``welcome_email.send_onboarding_welcome_email``
    and ``calendar_booking.book_onboarding_calendar_meetings``). Editing
    "E-mail" on this form looked like it updated the employee's contact
    info everywhere, but the address automation actually used could stay
    stale indefinitely. This keeps them in sync so there's one answer to
    "what's this employee's email" across the product, not two.
    """
    person = getattr(profile, "planner_person", None)
    if person is None:
        return

    name = f"{profile.first_name} {profile.last_name}".strip() or profile.erp_employee_id
    email = profile.user.email or ""
    title = profile.position or ""

    changed = []
    if person.email != email:
        person.email = email
        changed.append("email")
    if person.name != name:
        person.name = name
        changed.append("name")
    if person.title != title:
        person.title = title
        changed.append("title")
    if changed:
        person.save(update_fields=[*changed, "updated_at"])


@transaction.atomic
def update_employee(*, erp_id: str, data: dict[str, Any]) -> OnboardingProfile:
    """Update employee identity fields. Does not touch flow attachment.

    Changing or attaching a flow goes exclusively through ``attach_flow`` /
    the assign-flow and remove-flow endpoints now — see the module docstring
    above. ``data`` must not contain ``flow_slug``; callers validate that
    before reaching here (see ``schemas.validate_update_employee``).
    """
    profile = get_profile_by_erp_id(erp_id)
    user = profile.user

    if "email" in data:
        new_email = data["email"]
        User = get_user_model()
        if User.objects.filter(email__iexact=new_email).exclude(pk=user.pk).exists():
            raise ValidationError("email is already in use by another account.")
        user.email = new_email

    for field in ("first_name", "last_name", "position", "department"):
        if field in data:
            setattr(profile, field, data[field])
            if field in ("first_name", "last_name"):
                setattr(user, field, data[field])

    if "start_date" in data:
        profile.start_date = data["start_date"]
    if "country" in data:
        profile.country = data["country"]

    profile.save()
    user.save()
    _link_person_if_unlinked(profile)
    _sync_linked_person_identity(profile)
    return profile


@transaction.atomic
def delete_employee(*, erp_id: str) -> None:
    profile = get_profile_by_erp_id(erp_id)
    user = profile.user
    if user.is_active:
        raise ValidationError(
            "Cannot delete this record because the linked user account is active."
        )
    profile.delete()
    user.delete()


def list_employee_profiles() -> list[OnboardingProfile]:
    """All onboarding profiles, newest first — with or without a flow attached."""
    return list(OnboardingProfile.objects.select_related("user").order_by("-created_at"))


def _create_assignment_with_progress(
    *, profile: OnboardingProfile, flow: OnboardingFlow
) -> OnboardingAssignment:
    assignment = OnboardingAssignment.objects.create(profile=profile, flow=flow)
    steps = list(flow.steps.all())
    StepProgress.objects.bulk_create(
        [StepProgress(assignment=assignment, step=step) for step in steps]
    )
    return assignment


# ---------------------------------------------------------------------------
# Progress updates
# ---------------------------------------------------------------------------


@transaction.atomic
def set_step_progress(
    *,
    assignment: OnboardingAssignment,
    step: FlowStep,
    status: str,
    completion_data: dict[str, Any],
    completed_by: str,
) -> StepProgress:
    progress = StepProgress.objects.select_for_update().get(assignment=assignment, step=step)

    if status == StepProgress.STATUS_COMPLETED:
        get_component(step.component_type).validate_completion(completion_data)
        progress.status = status
        progress.completion_data = completion_data
        progress.completed_at = timezone.now()
        progress.completed_by = completed_by
    elif status == StepProgress.STATUS_SKIPPED:
        progress.status = status
        progress.completion_data = completion_data or {}
        progress.completed_at = timezone.now()
        progress.completed_by = completed_by
    else:  # pending — re-open
        progress.status = StepProgress.STATUS_PENDING
        progress.completion_data = {}
        progress.completed_at = None
        progress.completed_by = ""

    progress.save()
    _recompute_assignment_status(assignment)
    return progress


def _recompute_assignment_status(assignment: OnboardingAssignment) -> None:
    progresses = list(
        StepProgress.objects.filter(assignment=assignment).select_related("step")
    )

    finished_statuses = {StepProgress.STATUS_COMPLETED, StepProgress.STATUS_SKIPPED}
    any_finished = any(p.status in finished_statuses for p in progresses)

    required_unfinished = [
        p for p in progresses if p.step.is_required and p.status not in finished_statuses
    ]
    all_required_done = not required_unfinished and any_finished

    new_status = OnboardingAssignment.STATUS_PENDING
    if all_required_done:
        new_status = OnboardingAssignment.STATUS_COMPLETED
    elif any_finished:
        new_status = OnboardingAssignment.STATUS_IN_PROGRESS

    fields = ["status"]
    assignment.status = new_status
    if new_status == OnboardingAssignment.STATUS_IN_PROGRESS and assignment.started_at is None:
        assignment.started_at = timezone.now()
        fields.append("started_at")
    if new_status == OnboardingAssignment.STATUS_COMPLETED:
        if assignment.started_at is None:
            assignment.started_at = timezone.now()
            fields.append("started_at")
        if assignment.completed_at is None:
            assignment.completed_at = timezone.now()
            fields.append("completed_at")
    if new_status == OnboardingAssignment.STATUS_PENDING:
        # If a previously-completed step was re-opened, clear timestamps.
        if assignment.completed_at is not None:
            assignment.completed_at = None
            fields.append("completed_at")
    assignment.save(update_fields=fields)


# ---------------------------------------------------------------------------
# Serialisers (kept in services to share between API + admin debug views)
# ---------------------------------------------------------------------------


def serialize_step_progress(progress: StepProgress, country: str | None = None) -> dict[str, Any]:
    """``title``/``description`` are in the assignment's language (``country``)."""
    step = progress.step
    country = country or progress.assignment.country
    return {
        "id": step.id,
        "order": step.order,
        "component_type": step.component_type,
        "title": step.title_for(country),
        "description": step.description_for(country),
        "config": step.config,
        "is_required": step.is_required,
        "status": progress.status,
        "completion_data": progress.completion_data,
        "completed_at": progress.completed_at.isoformat() if progress.completed_at else None,
        "completed_by": progress.completed_by,
    }


def serialize_employee_summary(profile: OnboardingProfile) -> dict[str, Any]:
    """Employee identity fields, with planner-``Person`` fallbacks.

    Falls back to the linked planner ``Person`` when ``OnboardingProfile``
    fields are empty (common for people added directly in the check-in
    planner and only later provisioned into onboarding).
    """
    person = getattr(profile, "planner_person", None)

    def _first(*vals: str) -> str:
        for v in vals:
            if v:
                return v
        return ""

    if person and person.name:
        parts = person.name.split(None, 1)  # split on first whitespace only
        fallback_first = parts[0]
        fallback_last = parts[1] if len(parts) > 1 else ""
    else:
        fallback_first = fallback_last = ""

    return {
        "erp_employee_id": profile.erp_employee_id,
        "email": profile.user.email,
        "first_name": _first(profile.first_name, fallback_first),
        "last_name": _first(profile.last_name, fallback_last),
        "position": _first(profile.position, person.title if person else ""),
        "department": _first(profile.department, person.function_name if person else ""),
        "start_date": profile.start_date.isoformat() if profile.start_date else None,
        "country": profile.country,
    }


def serialize_provision_response(
    *,
    profile: OnboardingProfile,
    employee_created: bool,
    default_flow_created: bool,
) -> dict[str, Any]:
    """Structured payload for integrators provisioning a new hire.

    No flow/assignment/steps in this response — provisioning only creates
    the employee record now. A manager attaches a flow afterwards via the
    UI ("Tildel flow"), which is also what triggers the welcome email,
    calendar booking, and Slack invite.
    """
    return {
        "created": employee_created,
        "default_flow_created": default_flow_created,
        "default_flow_slug": DEFAULT_FLOW_SLUG,
        "employee": serialize_employee_summary(profile),
    }


def serialize_employee_state(profile: OnboardingProfile) -> dict[str, Any]:
    """Serialise a profile's current onboarding state, flow attached or not.

    Delegates to ``serialize_assignment`` when there's a latest assignment;
    otherwise returns the same shape with ``flow: None`` / ``status:
    "no_flow"`` / empty ``steps``. Callers (both the manage and service API)
    use this instead of assuming an assignment always exists — it doesn't,
    now that employee creation no longer auto-attaches a flow.
    """
    assignment = get_latest_assignment(profile)
    if assignment is not None:
        return serialize_assignment(assignment)
    return {
        **serialize_employee_summary(profile),
        "status": "no_flow",
        "assigned_at": None,
        "started_at": None,
        "completed_at": None,
        "flow": None,
        "steps": [],
        "buddy_name": None,
        "buddy_email": None,
        "leder_name": None,
        "leder_email": None,
        "scheduled_for": None,
        "scheduled_automation_ran_at": None,
        "assignment_country": None,
        "welcome_email_template_id": None,
    }


def serialize_assignment(assignment: OnboardingAssignment) -> dict[str, Any]:
    progresses = (
        StepProgress.objects.filter(assignment=assignment)
        .select_related("step")
        .order_by("step__order")
    )
    return {
        **serialize_employee_summary(assignment.profile),
        "status": assignment.status,
        "assigned_at": assignment.assigned_at.isoformat(),
        "started_at": assignment.started_at.isoformat() if assignment.started_at else None,
        "completed_at": assignment.completed_at.isoformat() if assignment.completed_at else None,
        "flow": {
            "slug": assignment.flow.slug,
            "name": assignment.flow.name,
            "description": assignment.flow.description,
        },
        "steps": [serialize_step_progress(p, assignment.country) for p in progresses],
        "assignment_country": assignment.country,
        "welcome_email_template_id": assignment.welcome_email_template_id,
        "buddy_name": assignment.buddy_name or None,
        "buddy_email": assignment.buddy_email or None,
        "leder_name": assignment.leder_name or None,
        "leder_email": assignment.leder_email or None,
        "scheduled_for": assignment.scheduled_for.isoformat() if assignment.scheduled_for else None,
        "scheduled_automation_ran_at": (
            assignment.scheduled_automation_ran_at.isoformat()
            if assignment.scheduled_automation_ran_at
            else None
        ),
    }


def serialize_flow(flow: OnboardingFlow) -> dict[str, Any]:
    return {
        "slug": flow.slug,
        "name": flow.name,
        "description": flow.description,
        "is_default": flow.is_default,
        "is_active": flow.is_active,
        "steps": [
            {
                "id": step.id,
                "order": step.order,
                "component_type": step.component_type,
                "title": step.title,
                "description": step.description,
                "title_no": step.title_no,
                "description_no": step.description_no,
                "config": step.config,
                "is_required": step.is_required,
            }
            for step in flow.steps.all().order_by("order")
        ],
    }


# ---------------------------------------------------------------------------
# Welcome email templates ("Velkomstmail" tab) — CRUD on WelcomeEmailTemplate
# itself. Rendering/merge-tags/resolution-order lives in welcome_email.py;
# import it lazily below to avoid a module-level circular import (that
# module doesn't need anything from here, but keeping the import local
# mirrors how manage_api.py already lazily imports sibling modules).
# ---------------------------------------------------------------------------


def serialize_welcome_email_template(template) -> dict[str, Any]:
    return {
        "id": template.pk,
        "name": template.name,
        "language": template.language,
        "is_default": bool(template.is_default),
        "subject": template.subject,
        "html_body": template.html_body,
        "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        "updated_by": (
            getattr(template.updated_by, "email", None) if template.updated_by_id else None
        ),
    }


def list_welcome_email_templates() -> dict[str, Any]:
    from .welcome_email import starter_template

    starter = starter_template()
    return {
        "results": [
            serialize_welcome_email_template(t)
            for t in WelcomeEmailTemplate.objects.select_related("updated_by")
        ],
        "starter": {"subject": starter.subject, "html_body": starter.html_body},
    }


@transaction.atomic
def save_welcome_email_template(
    template: WelcomeEmailTemplate | None, *, data: dict[str, Any], updated_by
) -> WelcomeEmailTemplate:
    """Create (``template=None``) or overwrite a library template."""
    template = template or WelcomeEmailTemplate()
    template.name = data["name"]
    template.language = data["language"]
    template.subject = data["subject"]
    template.html_body = data["html_body"]
    template.is_default = data.get("is_default", False)
    template.updated_by = updated_by
    template.save()
    return template
