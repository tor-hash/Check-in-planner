"""Manager-facing REST API for onboarding flow templates (session + CSRF)."""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .components import COMPONENTS
from .manager_auth import require_manager_api
from .models import FlowStep, OnboardingAssignment, OnboardingFlow, OnboardingProfile, StepProgress
from .schemas import (
    validate_create_employee_manage,
    validate_flow_payload,
    validate_reorder_payload,
    validate_step_payload,
    validate_update_employee,
)
from .services import (
    StepInUseError,
    _create_assignment_with_progress,
    create_employee_with_flow,
    create_flow,
    create_step,
    delete_employee,
    delete_flow,
    delete_step,
    get_flow_by_slug,
    get_latest_assignment,
    get_profile_by_erp_id,
    list_employee_assignments,
    reorder_steps,
    serialize_assignment,
    serialize_flow,
    update_employee,
    update_flow,
    update_step,
)


def _parse_json(request: HttpRequest):
    if not request.body:
        return None, JsonResponse({"detail": "Body must be JSON."}, status=400)
    try:
        return json.loads(request.body), None
    except json.JSONDecodeError:
        return None, JsonResponse({"detail": "Body is not valid JSON."}, status=400)


def _validation_error(exc: ValidationError) -> JsonResponse:
    return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)


def _step_in_use_error(exc: StepInUseError) -> JsonResponse:
    return JsonResponse({"detail": "; ".join(exc.messages)}, status=409)


def _flow_not_found() -> JsonResponse:
    return JsonResponse({"detail": "Flow not found."}, status=404)


def _get_flow(slug: str) -> OnboardingFlow | None:
    return OnboardingFlow.objects.filter(slug=slug).prefetch_related("steps").first()


@require_manager_api
@require_http_methods(["GET"])
def component_types(request: HttpRequest):
    results = [
        {
            "type_id": cls.type_id,
            "label": cls.label,
            "default_config": cls.default_config(),
        }
        for cls in COMPONENTS.values()
    ]
    return JsonResponse({"results": results})


@require_manager_api
@require_http_methods(["GET", "POST"])
def flows_collection(request: HttpRequest):
    if request.method == "POST":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_flow_payload(payload, require_slug=True)
        if err is not None:
            return err
        if "name" not in cleaned:
            return JsonResponse({"detail": "name is required."}, status=400)
        try:
            flow = create_flow(data=cleaned)
        except ValidationError as exc:
            return _validation_error(exc)
        return JsonResponse(serialize_flow(flow), status=201)

    flows = OnboardingFlow.objects.prefetch_related("steps").order_by("name")
    return JsonResponse(
        {
            "results": [
                {
                    **serialize_flow(f),
                    "assignment_count": OnboardingAssignment.objects.filter(flow=f).count(),
                }
                for f in flows
            ]
        }
    )


@require_manager_api
@require_http_methods(["GET", "PATCH", "DELETE"])
def flows_detail(request: HttpRequest, slug: str):
    flow = _get_flow(slug)
    if flow is None:
        return _flow_not_found()

    if request.method == "GET":
        return JsonResponse(serialize_flow(flow))

    if request.method == "PATCH":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_flow_payload(payload, require_slug=False)
        if err is not None:
            return err
        if not cleaned:
            return JsonResponse({"detail": "No fields to update."}, status=400)
        try:
            flow = update_flow(flow, data=cleaned)
        except ValidationError as exc:
            return _validation_error(exc)
        flow = _get_flow(slug)
        return JsonResponse(serialize_flow(flow))

    try:
        result = delete_flow(flow)
    except ValidationError as exc:
        return _validation_error(exc)
    return JsonResponse(result)


@require_manager_api
@require_http_methods(["POST"])
def steps_collection(request: HttpRequest, slug: str):
    flow = _get_flow(slug)
    if flow is None:
        return _flow_not_found()
    payload, err = _parse_json(request)
    if err is not None:
        return err
    cleaned, err = validate_step_payload(payload)
    if err is not None:
        return err
    try:
        step = create_step(flow, data=cleaned)
    except ValidationError as exc:
        return _validation_error(exc)
    flow = _get_flow(slug)
    return JsonResponse(serialize_flow(flow), status=201)


@require_manager_api
@require_http_methods(["PATCH", "DELETE"])
def steps_detail(request: HttpRequest, slug: str, step_id: int):
    flow = _get_flow(slug)
    if flow is None:
        return _flow_not_found()

    if request.method == "PATCH":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_step_payload(payload)
        if err is not None:
            return err
        try:
            update_step(flow, step_id, data=cleaned)
        except FlowStep.DoesNotExist:
            return JsonResponse({"detail": "Step not found."}, status=404)
        except ValidationError as exc:
            return _validation_error(exc)
        flow = _get_flow(slug)
        return JsonResponse(serialize_flow(flow))

    try:
        delete_step(flow, step_id)
    except FlowStep.DoesNotExist:
        return JsonResponse({"detail": "Step not found."}, status=404)
    except StepInUseError as exc:
        return _step_in_use_error(exc)
    except ValidationError as exc:
        return _validation_error(exc)
    flow = _get_flow(slug)
    return JsonResponse(serialize_flow(flow))


@require_manager_api
@require_http_methods(["PUT"])
def steps_reorder(request: HttpRequest, slug: str):
    flow = _get_flow(slug)
    if flow is None:
        return _flow_not_found()
    payload, err = _parse_json(request)
    if err is not None:
        return err
    step_ids, err = validate_reorder_payload(payload)
    if err is not None:
        return err
    try:
        reorder_steps(flow, step_ids)
    except ValidationError as exc:
        return _validation_error(exc)
    flow = _get_flow(slug)
    return JsonResponse(serialize_flow(flow))


# ---------------------------------------------------------------------------
# Employees (onboardees + flow assignment)
# ---------------------------------------------------------------------------


def _employee_not_found() -> JsonResponse:
    return JsonResponse({"detail": "Employee not found."}, status=404)


def _get_assignment_for_erp(erp_id: str) -> OnboardingAssignment | None:
    try:
        profile = get_profile_by_erp_id(erp_id)
    except OnboardingProfile.DoesNotExist:
        return None
    return get_latest_assignment(profile)


@require_manager_api
@require_http_methods(["GET", "POST"])
def employees_collection(request: HttpRequest):
    if request.method == "POST":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_create_employee_manage(payload, require_flow=True)
        if err is not None:
            return err
        try:
            assignment, created = create_employee_with_flow(data=cleaned)
        except ValidationError as exc:
            return _validation_error(exc)
        return JsonResponse(
            serialize_assignment(assignment), status=201 if created else 200
        )

    assignments = list_employee_assignments()
    return JsonResponse({"results": [serialize_assignment(a) for a in assignments]})


@require_manager_api
@require_http_methods(["GET", "PATCH", "DELETE"])
def employees_detail(request: HttpRequest, erp_id: str):
    if request.method == "GET":
        assignment = _get_assignment_for_erp(erp_id)
        if assignment is None:
            return _employee_not_found()
        return JsonResponse(serialize_assignment(assignment))

    if request.method == "PATCH":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_update_employee(payload)
        if err is not None:
            return err
        try:
            get_profile_by_erp_id(erp_id)
        except OnboardingProfile.DoesNotExist:
            return _employee_not_found()
        try:
            assignment = update_employee(erp_id=erp_id, data=cleaned)
        except ValidationError as exc:
            return _validation_error(exc)
        return JsonResponse(serialize_assignment(assignment))

    try:
        delete_employee(erp_id=erp_id)
    except OnboardingProfile.DoesNotExist:
        return _employee_not_found()
    except ValidationError as exc:
        return _validation_error(exc)
    return JsonResponse({"deleted": True, "erp_employee_id": erp_id})


# ---------------------------------------------------------------------------
# People list — all Person records with team + onboarding status
# ---------------------------------------------------------------------------


def _serialize_person_for_employees_tab(person) -> dict:
    """Serialise a planner Person for the Employees tab."""
    from apps.planner.services.onboarding_status import onboarding_is_complete

    # Team: first non-pool membership, if any.
    membership = (
        person.team_memberships.exclude(team="pool").order_by("team").first()
    )
    team = membership.team if membership else None

    # Onboarding status from linked profile/assignment.
    op = getattr(person, "onboarding_profile", None)
    if op is None:
        onboarding_status = None  # legacy / no profile
        flow_slug = None
        onboarding_assignment_status = None
    else:
        assignment = op.assignments.order_by("-assigned_at").first()
        if assignment is None:
            onboarding_status = "no_flow"
            flow_slug = None
            onboarding_assignment_status = None
        else:
            onboarding_status = "complete" if onboarding_is_complete(person) else "in_progress"
            flow_slug = assignment.flow.slug
            onboarding_assignment_status = assignment.status

    return {
        "legacy_id": person.legacy_id,
        "name": person.name,
        "email": person.email,
        "title": person.title,
        "team": team,
        "has_team": team is not None,
        "onboarding_status": onboarding_status,
        "flow_slug": flow_slug,
        "assignment_status": onboarding_assignment_status,
    }


@require_manager_api
@require_http_methods(["GET"])
def people_list(request: HttpRequest):
    """Return all Person records with team + onboarding status.

    GET /api/onboarding/manage/people
    """
    from apps.planner.models import Person

    people = (
        Person.objects.prefetch_related(
            "team_memberships",
            "onboarding_profile__assignments__flow",
        )
        .order_by("name")
    )
    return JsonResponse(
        {"results": [_serialize_person_for_employees_tab(p) for p in people]}
    )


# ---------------------------------------------------------------------------
# Assign / remove a flow for a person
# ---------------------------------------------------------------------------


@require_manager_api
@require_http_methods(["POST", "DELETE"])
def assign_flow(request: HttpRequest, erp_id: str):
    """Assign (POST) or cancel (DELETE) the onboarding flow for a person.

    POST /api/onboarding/manage/employees/<erp_id>/assign-flow/
    Body: {"flow_slug": "some-slug"}

    On success creates an OnboardingAssignment and sends a CalendarShareRequest
    email so the employee knows to share their Google Calendar.

    DELETE /api/onboarding/manage/employees/<erp_id>/assign-flow/
    Removes the most recent pending or in_progress assignment (and its
    StepProgress rows). Refuses to delete a completed assignment.
    """
    # Resolve Person via legacy_id (erp_id == person.legacy_id).
    from apps.planner.models import Person

    try:
        person = (
            Person.objects.select_related("onboarding_profile")
            .prefetch_related("onboarding_profile__assignments")
            .get(legacy_id=erp_id)
        )
    except Person.DoesNotExist:
        return JsonResponse({"detail": "Person not found."}, status=404)

    if request.method == "POST":
        payload, err = _parse_json(request)
        if err is not None:
            return err

        flow_slug = (payload or {}).get("flow_slug", "")
        if not flow_slug:
            return JsonResponse({"detail": "flow_slug is required."}, status=400)

        try:
            flow = get_flow_by_slug(flow_slug)
        except OnboardingFlow.DoesNotExist:
            return JsonResponse({"detail": f"Flow '{flow_slug}' not found or inactive."}, status=404)

        op = getattr(person, "onboarding_profile", None)
        if op is None:
            return JsonResponse(
                {
                    "detail": (
                        "This person has no onboarding profile. "
                        "Provision them via the onboarding API first."
                    )
                },
                status=400,
            )

        # Idempotent: return existing assignment if already on this flow.
        existing = OnboardingAssignment.objects.filter(profile=op, flow=flow).first()
        if existing is not None:
            # Send another calendar share request if not yet complete.
            if existing.status != OnboardingAssignment.STATUS_COMPLETED:
                _send_calendar_share(person, request.user)
            return JsonResponse(serialize_assignment(existing), status=200)

        assignment = _create_assignment_with_progress(profile=op, flow=flow)
        _send_calendar_share(person, request.user)
        return JsonResponse(serialize_assignment(assignment), status=201)

    # DELETE
    op = getattr(person, "onboarding_profile", None)
    if op is None:
        return JsonResponse({"detail": "Person has no onboarding profile."}, status=404)

    assignment = op.assignments.order_by("-assigned_at").first()
    if assignment is None:
        return JsonResponse({"detail": "No assignment found."}, status=404)

    if assignment.status == OnboardingAssignment.STATUS_COMPLETED:
        return JsonResponse(
            {"detail": "Cannot delete a completed assignment."}, status=409
        )

    # Delete StepProgress rows then assignment.
    StepProgress.objects.filter(assignment=assignment).delete()
    assignment.delete()
    return JsonResponse({"deleted": True, "erp_employee_id": erp_id})


def _send_calendar_share(person, requesting_user) -> None:
    """Best-effort: send calendar-share request email. Logs on failure."""
    import logging as _logging

    _log = _logging.getLogger(__name__)
    try:
        from apps.planner.services.calendar_share import send_share_request

        send_share_request(person=person, requested_by=requesting_user)
    except Exception as exc:
        _log.warning(
            "assign_flow: could not send calendar share request for %s: %s",
            person.legacy_id,
            exc,
        )


# ---------------------------------------------------------------------------
# Book calendar meetings for an employee's onboarding flow steps
# ---------------------------------------------------------------------------


@require_manager_api
@require_http_methods(["POST"])
def book_calendar_meetings(request: HttpRequest, erp_id: str):
    """Book Google Calendar meetings for all pending calendar_meeting steps.

    POST /api/onboarding/manage/employees/<erp_id>/book-calendar-meetings/

    Guards:
    - Person must have an active (pending/in_progress) OnboardingAssignment.
    - Person must be assigned to a non-pool team.

    Returns 200 with per-step outcomes even when some steps fail (partial
    success).  Returns 400/404 when a prerequisite is entirely missing.
    """
    from apps.planner.models import Person

    try:
        person = Person.objects.select_related("onboarding_profile").get(legacy_id=erp_id)
    except Person.DoesNotExist:
        return JsonResponse({"detail": "Person not found."}, status=404)

    from apps.planner.services.onboarding_status import has_team_assignment

    if not has_team_assignment(person):
        return JsonResponse(
            {"detail": "Person must be assigned to a team before booking meetings."},
            status=400,
        )

    from .calendar_booking import book_onboarding_calendar_meetings

    result = book_onboarding_calendar_meetings(person)

    if not result.ok:
        # Top-level failure (missing profile/assignment/manager).
        return JsonResponse({"detail": result.error}, status=400)

    return JsonResponse(result.to_dict(), status=200)
