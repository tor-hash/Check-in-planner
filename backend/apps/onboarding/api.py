"""REST API for the onboarding service.

Auth: every endpoint requires header ``X-API-Key: <token>`` validated
against ``settings.ONBOARDING_API_TOKEN``. CSRF is disabled because the
API is consumed by service-to-service callers (ERP, HR tooling), not by
authenticated browser sessions.
"""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, Paginator
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from .auth import require_api_key
from .models import (
    FlowStep,
    OnboardingAssignment,
    OnboardingFlow,
    OnboardingProfile,
    StepProgress,
)
from .schemas import (
    validate_create_employee,
    validate_email_lookup,
    validate_provision_employee,
    validate_step_progress_patch,
)
from .services import (
    create_employee,
    list_profiles_by_email,
    provision_employee_with_default_flow,
    serialize_employee_state,
    serialize_flow,
    serialize_provision_response,
    set_step_progress,
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


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------


@require_api_key
@require_http_methods(["POST"])
def provision_employee(request: HttpRequest):
    """Create a new hire (seeds the default flow *template* if missing).

    Does not attach any flow to the new hire — see the ``services.py``
    module docstring. A manager attaches one afterwards via the UI, which
    is also what sends the welcome email / books meetings / invites them
    to Slack.
    """
    payload, err = _parse_json(request)
    if err is not None:
        return err
    cleaned, err = validate_provision_employee(payload)
    if err is not None:
        return err
    try:
        profile, employee_created, flow_created = provision_employee_with_default_flow(
            data=cleaned
        )
    except ValidationError as exc:
        return _validation_error(exc)
    return JsonResponse(
        serialize_provision_response(
            profile=profile,
            employee_created=employee_created,
            default_flow_created=flow_created,
        ),
        status=201 if employee_created else 200,
    )


@require_api_key
@require_http_methods(["GET", "POST"])
def employees_collection(request: HttpRequest):
    if request.method == "POST":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_create_employee(payload)
        if err is not None:
            return err
        try:
            profile, created = create_employee(data=cleaned)
        except ValidationError as exc:
            return _validation_error(exc)
        return JsonResponse(
            serialize_employee_state(profile), status=201 if created else 200
        )

    page_number = max(1, int(request.GET.get("page", 1) or 1))
    page_size = min(100, max(1, int(request.GET.get("page_size", 25) or 25)))
    qs = OnboardingProfile.objects.select_related("user").order_by("-created_at")
    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_number)
    except EmptyPage:
        page = paginator.page(paginator.num_pages or 1)
    return JsonResponse(
        {
            "count": paginator.count,
            "page": page.number,
            "page_size": page_size,
            "num_pages": paginator.num_pages,
            "results": [serialize_employee_state(p) for p in page.object_list],
        }
    )


@require_api_key
@require_http_methods(["GET", "POST"])
def employees_by_email(request: HttpRequest):
    """Look up onboarding state by the employee's login email address."""
    if request.method == "POST":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        raw_email = payload.get("email") if isinstance(payload, dict) else None
    else:
        raw_email = request.GET.get("email")

    email, err = validate_email_lookup(raw_email)
    if err is not None:
        return err

    profiles = list_profiles_by_email(email=email)
    if not profiles:
        return JsonResponse(
            {"detail": "No onboarding employee found for this email."},
            status=404,
        )

    if len(profiles) == 1:
        return JsonResponse(serialize_employee_state(profiles[0]))

    return JsonResponse(
        {
            "email": email,
            "count": len(profiles),
            "results": [serialize_employee_state(p) for p in profiles],
        }
    )


@require_api_key
@require_http_methods(["GET"])
def employees_detail(request: HttpRequest, erp_id: str):
    profile = (
        OnboardingProfile.objects.select_related("user")
        .filter(erp_employee_id=erp_id)
        .first()
    )
    if profile is None:
        return JsonResponse({"detail": "Employee not found."}, status=404)
    return JsonResponse(serialize_employee_state(profile))


@require_api_key
@require_http_methods(["PATCH"])
def step_progress_detail(request: HttpRequest, erp_id: str, step_id: int):
    profile = OnboardingProfile.objects.filter(erp_employee_id=erp_id).first()
    if profile is None:
        return JsonResponse({"detail": "Employee not found."}, status=404)
    assignment = (
        OnboardingAssignment.objects.filter(profile=profile)
        .order_by("-assigned_at")
        .first()
    )
    if assignment is None:
        return JsonResponse({"detail": "Employee has no flow assignment."}, status=404)
    step = FlowStep.objects.filter(pk=step_id, flow=assignment.flow).first()
    if step is None:
        return JsonResponse(
            {"detail": "Step not found on this employee's flow."}, status=404
        )

    payload, err = _parse_json(request)
    if err is not None:
        return err
    cleaned, err = validate_step_progress_patch(payload)
    if err is not None:
        return err

    try:
        progress = set_step_progress(
            assignment=assignment,
            step=step,
            status=cleaned["status"],
            completion_data=cleaned["completion_data"],
            completed_by=cleaned["completed_by"],
        )
    except ValidationError as exc:
        return _validation_error(exc)
    except StepProgress.DoesNotExist:
        return JsonResponse(
            {"detail": "Progress row missing - flow was edited after assignment."},
            status=409,
        )

    assignment.refresh_from_db()
    return JsonResponse(
        {
            "assignment_status": assignment.status,
            "step": {
                "id": step.id,
                "order": step.order,
                "title": step.title_for(assignment.country),
                "component_type": step.component_type,
                "status": progress.status,
                "completion_data": progress.completion_data,
                "completed_at": (
                    progress.completed_at.isoformat() if progress.completed_at else None
                ),
                "completed_by": progress.completed_by,
            },
        }
    )


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@require_api_key
@require_http_methods(["GET"])
def flows_collection(request: HttpRequest):
    flows = list(OnboardingFlow.objects.all().prefetch_related("steps"))
    return JsonResponse({"results": [serialize_flow(f) for f in flows]})


@require_api_key
@require_http_methods(["GET"])
def flows_detail(request: HttpRequest, slug: str):
    flow = (
        OnboardingFlow.objects.prefetch_related("steps")
        .filter(slug=slug)
        .first()
    )
    if flow is None:
        return JsonResponse({"detail": "Flow not found."}, status=404)
    return JsonResponse(serialize_flow(flow))
