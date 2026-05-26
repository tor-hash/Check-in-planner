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


@transaction.atomic
def create_employee_with_flow(*, data: dict[str, Any]) -> tuple[OnboardingAssignment, bool]:
    """Create or upsert an employee and assign them a flow.

    Returns ``(assignment, created)`` where ``created`` is True only when
    a brand-new profile was created (so the caller can return 201 vs 200).
    """
    slug = data.get("flow_slug")
    if slug:
        try:
            flow = get_flow_by_slug(slug)
        except OnboardingFlow.DoesNotExist as exc:
            raise ValidationError(f"Unknown flow_slug '{slug}'.") from exc
    else:
        try:
            flow = get_default_flow()
        except OnboardingFlow.DoesNotExist as exc:
            raise ValidationError(str(exc)) from exc

    profile = OnboardingProfile.objects.filter(erp_employee_id=data["erp_employee_id"]).first()
    if profile is not None:
        # Idempotent replay: reuse existing assignment for the same flow.
        assignment = OnboardingAssignment.objects.filter(profile=profile, flow=flow).first()
        if assignment is None:
            assignment = _create_assignment_with_progress(profile=profile, flow=flow)
        return assignment, False

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
    assignment = _create_assignment_with_progress(profile=profile, flow=flow)
    return assignment, True


@transaction.atomic
def provision_employee_with_default_flow(
    *, data: dict[str, Any]
) -> tuple[OnboardingAssignment, bool, bool]:
    """Ensure default flow exists, then create/upsert employee on that flow.

    Returns ``(assignment, employee_created, default_flow_created)``.
    """
    flow, flow_created = ensure_default_flow()
    payload = {**data, "flow_slug": flow.slug}
    assignment, employee_created = create_employee_with_flow(data=payload)
    return assignment, employee_created, flow_created


def get_profile_by_erp_id(erp_id: str) -> OnboardingProfile:
    return OnboardingProfile.objects.select_related("user").get(erp_employee_id=erp_id)


def get_latest_assignment(profile: OnboardingProfile) -> OnboardingAssignment | None:
    return (
        OnboardingAssignment.objects.select_related("flow")
        .filter(profile=profile)
        .order_by("-assigned_at")
        .first()
    )


def list_assignments_by_email(*, email: str) -> list[OnboardingAssignment]:
    """Return the latest onboarding assignment per profile matching ``email``."""
    profiles = OnboardingProfile.objects.select_related("user").filter(
        user__email__iexact=email
    )
    out: list[OnboardingAssignment] = []
    for profile in profiles:
        assignment = get_latest_assignment(profile)
        if assignment is not None:
            out.append(assignment)
    return out


@transaction.atomic
def update_employee(*, erp_id: str, data: dict[str, Any]) -> OnboardingAssignment:
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

    assignment = None
    if "flow_slug" in data:
        try:
            flow = get_flow_by_slug(data["flow_slug"])
        except OnboardingFlow.DoesNotExist as exc:
            raise ValidationError(f"Unknown flow_slug '{data['flow_slug']}'.") from exc
        assignment = OnboardingAssignment.objects.filter(profile=profile, flow=flow).first()
        if assignment is None:
            assignment = _create_assignment_with_progress(profile=profile, flow=flow)
    else:
        assignment = get_latest_assignment(profile)

    if assignment is None:
        raise ValidationError("Employee has no onboarding flow assignment.")
    return assignment


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


def list_employee_assignments() -> list[OnboardingAssignment]:
    profiles = OnboardingProfile.objects.select_related("user").order_by("-created_at")
    out: list[OnboardingAssignment] = []
    for profile in profiles:
        assignment = get_latest_assignment(profile)
        if assignment is not None:
            out.append(assignment)
    return out


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


def serialize_employee_summary(assignment: OnboardingAssignment) -> dict[str, Any]:
    profile = assignment.profile
    return {
        "erp_employee_id": profile.erp_employee_id,
        "email": profile.user.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "position": profile.position,
        "department": profile.department,
        "start_date": profile.start_date.isoformat() if profile.start_date else None,
    }


def serialize_provision_response(
    *,
    assignment: OnboardingAssignment,
    employee_created: bool,
    default_flow_created: bool,
) -> dict[str, Any]:
    """Structured payload for integrators provisioning a new hire."""
    assignment_body = serialize_assignment(assignment)
    return {
        "created": employee_created,
        "default_flow_created": default_flow_created,
        "default_flow_slug": DEFAULT_FLOW_SLUG,
        "employee": serialize_employee_summary(assignment),
        "assignment": {
            "status": assignment_body["status"],
            "assigned_at": assignment_body["assigned_at"],
            "started_at": assignment_body["started_at"],
            "completed_at": assignment_body["completed_at"],
        },
        "flow": serialize_flow(assignment.flow),
        "steps": assignment_body["steps"],
    }


def serialize_assignment(assignment: OnboardingAssignment) -> dict[str, Any]:
    profile = assignment.profile
    progresses = (
        StepProgress.objects.filter(assignment=assignment)
        .select_related("step")
        .order_by("step__order")
    )
    return {
        "erp_employee_id": profile.erp_employee_id,
        "email": profile.user.email,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "position": profile.position,
        "department": profile.department,
        "start_date": profile.start_date.isoformat() if profile.start_date else None,
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
