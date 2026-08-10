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
    validate_buddy_fields,
    validate_create_employee,
    validate_flow_payload,
    validate_reorder_payload,
    validate_step_payload,
    validate_update_employee,
    validate_welcome_email_preview,
    validate_welcome_email_template,
)
from .services import (
    StepInUseError,
    attach_flow,
    create_employee,
    create_flow,
    create_step,
    delete_employee,
    delete_flow,
    delete_step,
    delete_welcome_email_template,
    get_flow_by_slug,
    get_profile_by_erp_id,
    list_employee_profiles,
    reorder_steps,
    save_welcome_email_template,
    serialize_employee_state,
    serialize_flow,
    serialize_welcome_email_template_for_flow,
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


def _parse_json_optional(request: HttpRequest):
    """Like ``_parse_json``, but an empty body is valid — returns ``{}``."""
    if not request.body:
        return {}, None
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


@require_manager_api
@require_http_methods(["GET", "POST"])
def employees_collection(request: HttpRequest):
    """Create/list employee profiles. Creating never attaches a flow.

    A flow is attached separately and deliberately via ``assign_flow``
    below — that's also the only place the welcome email, calendar
    booking, and Slack invite automation runs. See ``services.py`` module
    docstring.
    """
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

    profiles = list_employee_profiles()
    return JsonResponse({"results": [serialize_employee_state(p) for p in profiles]})


@require_manager_api
@require_http_methods(["GET", "PATCH", "DELETE"])
def employees_detail(request: HttpRequest, erp_id: str):
    if request.method == "GET":
        try:
            profile = get_profile_by_erp_id(erp_id)
        except OnboardingProfile.DoesNotExist:
            return _employee_not_found()
        return JsonResponse(serialize_employee_state(profile))

    if request.method == "PATCH":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_update_employee(payload)
        if err is not None:
            return err
        try:
            profile = update_employee(erp_id=erp_id, data=cleaned)
        except OnboardingProfile.DoesNotExist:
            return _employee_not_found()
        except ValidationError as exc:
            return _validation_error(exc)
        return JsonResponse(serialize_employee_state(profile))

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


def _employee_missing_email_error() -> JsonResponse:
    return JsonResponse(
        {
            "detail": (
                "This person has no email address on file. Add one on the "
                "planner Person record before attaching a flow — the "
                "welcome email and calendar invite both need it."
            )
        },
        status=400,
    )


def _manager_google_not_connected_error(user) -> JsonResponse:
    return JsonResponse(
        {
            "detail": (
                f"{getattr(user, 'email', None) or 'You'} haven't connected Google "
                "Calendar yet. Sign in with Google once (top nav) before attaching "
                "a flow — the welcome email and any 'assigning_manager' meetings "
                "are sent/booked from your account."
            )
        },
        status=400,
    )


@require_manager_api
@require_http_methods(["POST", "DELETE"])
def assign_flow(request: HttpRequest, erp_id: str):
    """Assign (POST) or cancel (DELETE) the onboarding flow for a person.

    POST /api/onboarding/manage/employees/<erp_id>/assign-flow/
    Body: {"flow_slug": "some-slug", "buddy_name": "...", "buddy_email": "..."}
    ``buddy_name``/``buddy_email`` are optional and only recorded the first
    time (see ``services.attach_flow``) — they're available as the
    ``{{ buddy_name }}``/``{{ buddy_email }}`` merge tags in the welcome
    email (``welcome_email.py``).

    This is the one deliberate "attach a flow" action in the system —
    creating an employee never does this as a side effect (see
    ``services.py`` module docstring). Before attaching anything, two
    pre-flight checks can block the request outright (400, nothing
    created):

      1. The employee (planner ``Person``) must have an email address.
      2. The acting manager (``request.user``) must have a connected
         Google account.

    Both are hard requirements for what happens next, so we check them
    before creating the assignment rather than creating it and reporting a
    partial failure afterwards.

    On a brand-new assignment this then:
      1. Records the acting manager as ``assigned_by`` (used as the welcome
         email sender and to resolve "assigning_manager" meeting organizers).
      2. Sends the combined welcome + calendar-share-request email once
         (best-effort from here on — failure is reported back but doesn't
         fail the request; the assignment still exists either way).
      3. Attempts to book every ``calendar_meeting`` step in the flow
         (best-effort, per-step isolated — see ``calendar_booking.py``).
      4. Attempts to invite the employee to Slack (best-effort — see
         ``slack_invite.py``; no-ops with a clear "not_configured" outcome
         until ``SLACK_BOT_TOKEN`` is set).

    Re-attaching an already-assigned flow (idempotent replay) skips steps
    2 and 4 — already done — but re-runs step 3 for whatever is still
    unbooked. This is the same action the "Book møder" retry button
    triggers explicitly (see ``book_calendar_meetings`` below).

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

        buddy, err = validate_buddy_fields(payload or {})
        if err is not None:
            return err

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

        # ---- pre-flight checks: block the attach outright, create nothing ----
        if not (person.email or "").strip():
            return _employee_missing_email_error()

        from apps.planner.google.credentials import has_google_credentials

        if not has_google_credentials(request.user):
            return _manager_google_not_connected_error(request.user)
        # ------------------------------------------------------------------

        assignment, is_new = attach_flow(
            profile=op,
            flow=flow,
            requested_by=request.user,
            buddy_name=buddy["buddy_name"],
            buddy_email=buddy["buddy_email"],
        )

        automation: dict = {"welcomeEmail": None, "meetings": None, "slackInvite": None}

        if is_new:
            automation["welcomeEmail"] = _send_onboarding_welcome_email(
                person=person, assignment=assignment, requested_by=request.user
            )
            automation["slackInvite"] = _send_onboarding_slack_invite(
                person=person, assignment=assignment, requested_by=request.user
            )

        if assignment.status != OnboardingAssignment.STATUS_COMPLETED:
            automation["meetings"] = _book_onboarding_meetings(person)

        body = serialize_employee_state(op)
        body["automation"] = automation
        return JsonResponse(body, status=201 if is_new else 200)

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


def _send_onboarding_welcome_email(*, person, assignment, requested_by) -> dict:
    """Best-effort: send the combined welcome/calendar-share email.

    Returns a small dict describing the outcome (never raises) so the
    caller can surface it in the response.
    """
    import logging as _logging

    from .welcome_email import send_onboarding_welcome_email

    _log = _logging.getLogger(__name__)
    try:
        send_onboarding_welcome_email(
            person=person, assignment=assignment, requested_by=requested_by
        )
        return {"sent": True}
    except Exception as exc:
        _log.warning(
            "assign_flow: could not send welcome email for %s: %s",
            person.legacy_id,
            exc,
        )
        return {"sent": False, "error": str(exc)}


def _send_onboarding_slack_invite(*, person, assignment, requested_by) -> dict:
    """Best-effort Slack invite. Returns a plain dict (never raises)."""
    import logging as _logging

    from .slack_invite import send_onboarding_slack_invite

    _log = _logging.getLogger(__name__)
    try:
        result = send_onboarding_slack_invite(
            person=person, assignment=assignment, requested_by=requested_by
        )
        return result.to_dict()
    except Exception as exc:  # defensive — send_onboarding_slack_invite shouldn't raise
        _log.warning(
            "assign_flow: Slack invite crashed for %s: %s", person.legacy_id, exc
        )
        return {"sent": False, "reason": "error", "error": str(exc)}


def _book_onboarding_meetings(person) -> dict:
    """Run the meeting-booking pass and return it as a plain dict."""
    from .calendar_booking import book_onboarding_calendar_meetings

    result = book_onboarding_calendar_meetings(person)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Book calendar meetings for an employee's onboarding flow steps
# ---------------------------------------------------------------------------


@require_manager_api
@require_http_methods(["POST"])
def book_calendar_meetings(request: HttpRequest, erp_id: str):
    """Book Google Calendar meetings for all pending calendar_meeting steps.

    POST /api/onboarding/manage/employees/<erp_id>/book-calendar-meetings/

    This is the manual retry action — it does exactly what ``assign_flow``
    already does automatically for unbooked steps (same underlying
    ``book_onboarding_calendar_meetings`` call), for when a manager wants
    to retry after fixing something (e.g. an organizer just connected
    Google Calendar).

    Returns 200 with per-step outcomes even when some steps fail (partial
    success). Returns 400/404 when there's no onboarding profile/assignment
    at all.
    """
    from apps.planner.models import Person

    try:
        person = Person.objects.select_related("onboarding_profile").get(legacy_id=erp_id)
    except Person.DoesNotExist:
        return JsonResponse({"detail": "Person not found."}, status=404)

    from .calendar_booking import book_onboarding_calendar_meetings

    result = book_onboarding_calendar_meetings(person)

    if not result.ok:
        # Top-level failure (missing profile/assignment).
        return JsonResponse({"detail": result.error}, status=400)

    return JsonResponse(result.to_dict(), status=200)


# ---------------------------------------------------------------------------
# Welcome email template ("Velkomstmail" tab)
# ---------------------------------------------------------------------------


@require_manager_api
@require_http_methods(["GET", "PUT", "DELETE"])
def flow_welcome_email(request: HttpRequest, slug: str):
    """Read, save, or revert this flow's welcome-email template.

    GET /api/onboarding/manage/flows/<slug>/welcome-email
    Returns the *effective* template for this flow, whether or not it has
    one of its own — see ``services.serialize_welcome_email_template_for_flow``
    and ``welcome_email.resolve_welcome_email_template`` for the resolution
    order (own → whichever flow is marked default-fallback → the hardcoded
    starter content). ``source`` in the response tells you which.

    PUT /api/onboarding/manage/flows/<slug>/welcome-email
    Body: {"subject": "...", "html_body": "...", "is_default_fallback": bool}
    Creates or overwrites this flow's own template. Rejects bad
    ``{% %}``/``{{ }}`` syntax with 400 before saving anything.

    DELETE /api/onboarding/manage/flows/<slug>/welcome-email
    Deletes this flow's own template (404 if it doesn't have one). The flow
    then falls back to whatever ``resolve_welcome_email_template`` resolves
    to next — this does not touch other flows' templates.
    """
    flow = _get_flow(slug)
    if flow is None:
        return _flow_not_found()

    if request.method == "GET":
        return JsonResponse(serialize_welcome_email_template_for_flow(flow))

    if request.method == "PUT":
        payload, err = _parse_json(request)
        if err is not None:
            return err
        cleaned, err = validate_welcome_email_template(payload)
        if err is not None:
            return err

        from .welcome_email import validate_template_syntax

        try:
            validate_template_syntax(subject=cleaned["subject"], html_body=cleaned["html_body"])
        except ValidationError as exc:
            return _validation_error(exc)

        save_welcome_email_template(flow, data=cleaned, updated_by=request.user)
        return JsonResponse(serialize_welcome_email_template_for_flow(flow))

    # DELETE
    existed = delete_welcome_email_template(flow)
    if not existed:
        return JsonResponse(
            {"detail": f"Flow '{slug}' has no welcome email template of its own."}, status=404
        )
    return JsonResponse(serialize_welcome_email_template_for_flow(flow))


@require_manager_api
@require_http_methods(["POST"])
def flow_welcome_email_preview(request: HttpRequest, slug: str):
    """Render a welcome email without sending it.

    POST /api/onboarding/manage/flows/<slug>/welcome-email/preview
    Body (all optional): {
      "subject": "...", "html_body": "...",   # preview unsaved draft content
      "erp_id": "E1234",                       # render with a real employee
      "buddy_name": "...", "buddy_email": "..."
    }

    With no body, previews this flow's currently *saved* effective
    template against placeholder sample data — this is what the "Tildel
    flow" dialog calls (with ``erp_id``/``buddy_name``/``buddy_email`` set)
    before a manager confirms the attach. With ``subject``/``html_body``
    given, previews that unsaved draft instead — this is what the
    "Velkomstmail" editor calls on every edit, so the preview always
    matches what's in the textarea, not what's on disk.

    Returns {"subject": "...", "html": "...", "plain": "...", "source": "..."}.
    ``source`` is omitted when previewing draft content (there's nothing to
    resolve — it's exactly what was sent).
    """
    flow = _get_flow(slug)
    if flow is None:
        return _flow_not_found()

    payload, err = _parse_json_optional(request)
    if err is not None:
        return err
    cleaned, err = validate_welcome_email_preview(payload)
    if err is not None:
        return err

    from apps.planner.models import Person

    person = None
    profile = None
    if cleaned["erp_id"]:
        person = Person.objects.select_related("onboarding_profile").filter(
            legacy_id=cleaned["erp_id"]
        ).first()
        if person is None:
            return JsonResponse({"detail": "Person not found."}, status=404)
        profile = getattr(person, "onboarding_profile", None)

    from .welcome_email import (
        build_merge_context,
        html_to_plain,
        render_merge_tags,
        resolve_welcome_email_template,
    )

    class _SamplePerson:
        name = "Anna Andersen"
        email = "anna.andersen@example.com"

    context = build_merge_context(
        person=person or _SamplePerson(),
        flow=flow,
        requested_by=request.user,
        buddy_name=cleaned["buddy_name"],
        buddy_email=cleaned["buddy_email"],
        profile=profile,
    )

    if "subject" in cleaned:
        subject_template, html_template, source = cleaned["subject"], cleaned["html_body"], None
    else:
        template, source, _fallback_slug = resolve_welcome_email_template(flow)
        subject_template, html_template = template.subject, template.html_body

    try:
        subject = render_merge_tags(subject_template, context)
        html = render_merge_tags(html_template, context)
    except Exception as exc:
        return JsonResponse({"detail": f"Could not render template: {exc}"}, status=400)

    body = {"subject": subject, "html": html, "plain": html_to_plain(html)}
    if source is not None:
        body["source"] = source
    return JsonResponse(body)
