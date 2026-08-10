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
    """Link an existing planner ``Person`` to this profile, if one matches.

    Employees are often added to the check-in planner (``Person``) before
    they're ever provisioned into onboarding. When that happens, the
    ``erp_employee_id`` used to provision them is, by convention, the
    person's ``legacy_id`` (see ``manage_api.assign_flow`` and the
    "+ Ny medarbejder" flow in ``employees-editor.js``, which pre-fills and
    locks the ERP id from ``person.legacy_id``). If such a ``Person`` exists
    and isn't already linked to a different profile, link it here so the
    Employees tab picks it up immediately instead of showing an orphaned
    profile forever.

    No-op (and never raises) when there's no matching ``Person``, the match
    is already linked, or the planner app isn't installed.
    """
    try:
        from apps.planner.models import Person
    except Exception:  # pragma: no cover - planner app always installed in practice
        return
    Person.objects.filter(
        legacy_id=profile.erp_employee_id, onboarding_profile__isnull=True
    ).update(onboarding_profile=profile)


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
    buddy_name: str = "",
    buddy_email: str = "",
) -> tuple[OnboardingAssignment, bool]:
    """Attach ``flow`` to ``profile`` — the one deliberate "attach" action.

    Idempotent on ``(profile, flow)``: replaying returns the existing
    assignment unchanged. ``requested_by`` is recorded as ``assigned_by``
    the first time (backfilled on replay if it was never set, e.g. the
    assignment originated some other way) since it drives the welcome-email
    sender and "assigning_manager" meeting organizer resolution. ``buddy_name``
    / ``buddy_email`` are likewise only set the first time — they're locked
    in alongside the welcome email, which only ever sends once.

    This function only creates the assignment + step-progress rows. It does
    **not** run the attach automation (welcome email / calendar booking /
    Slack invite) or the pre-flight checks that can block an attach — those
    live in ``manage_api.assign_flow``, which is the only caller. Keeping
    them there (rather than here) keeps this function usable from tests and
    any future caller without dragging in Google/Slack side effects.

    Returns ``(assignment, is_new)``.
    """
    assignment = OnboardingAssignment.objects.filter(profile=profile, flow=flow).first()
    is_new = assignment is None
    if is_new:
        assignment = _create_assignment_with_progress(profile=profile, flow=flow)
        assignment.buddy_name = buddy_name
        assignment.buddy_email = buddy_email
        assignment.save(update_fields=["buddy_name", "buddy_email", "updated_at"])

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

    profile.save()
    user.save()
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


def serialize_step_progress(progress: StepProgress) -> dict[str, Any]:
    step = progress.step
    return {
        "id": step.id,
        "order": step.order,
        "component_type": step.component_type,
        "title": step.title,
        "description": step.description,
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
        "steps": [serialize_step_progress(p) for p in progresses],
        "buddy_name": assignment.buddy_name or None,
        "buddy_email": assignment.buddy_email or None,
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


def serialize_welcome_email_template_for_flow(flow: OnboardingFlow) -> dict[str, Any]:
    from .welcome_email import resolve_welcome_email_template

    template, source, fallback_flow_slug = resolve_welcome_email_template(flow)
    is_own = source == "own"
    return {
        "flow_slug": flow.slug,
        "source": source,
        "has_own_template": is_own,
        "is_default_fallback": bool(template.is_default_fallback) if is_own else False,
        "fallback_flow_slug": fallback_flow_slug,
        "subject": template.subject,
        "html_body": template.html_body,
        "updated_at": template.updated_at.isoformat() if is_own else None,
        "updated_by": getattr(template.updated_by, "email", None) if is_own and template.updated_by_id else None,
    }


@transaction.atomic
def save_welcome_email_template(
    flow: OnboardingFlow, *, data: dict[str, Any], updated_by
) -> WelcomeEmailTemplate:
    template, _created = WelcomeEmailTemplate.objects.update_or_create(
        flow=flow,
        defaults={
            "subject": data["subject"],
            "html_body": data["html_body"],
            "is_default_fallback": data.get("is_default_fallback", False),
            "updated_by": updated_by,
        },
    )
    return template


@transaction.atomic
def delete_welcome_email_template(flow: OnboardingFlow) -> bool:
    """Delete this flow's own template, if any. Returns whether one existed."""
    deleted, _ = WelcomeEmailTemplate.objects.filter(flow=flow).delete()
    return deleted > 0
