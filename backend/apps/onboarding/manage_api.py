"""Manager-facing REST API for onboarding flow templates (session + CSRF)."""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .components import COMPONENTS
from .manager_auth import require_manager_api
from .models import FlowStep, OnboardingAssignment, OnboardingFlow, OnboardingProfile
from .schemas import (
    validate_create_employee_manage,
    validate_flow_payload,
    validate_reorder_payload,
    validate_step_payload,
    validate_update_employee,
)
from .services import (
    StepInUseError,
    create_employee_with_flow,
    create_flow,
    create_step,
    delete_employee,
    delete_flow,
    delete_step,
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
