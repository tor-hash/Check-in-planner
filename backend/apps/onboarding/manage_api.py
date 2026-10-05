"""Manager-facing REST API for onboarding flow templates (session + CSRF)."""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .automation import run_onboarding_attach_automation
from .components import COMPONENTS
from .manager_auth import require_manager_api
from .models import (
    FlowStep,
    OnboardingAssignment,
    OnboardingFlow,
    OnboardingProfile,
    StepProgress,
    WelcomeEmailTemplate,
)
from .schemas import (
    validate_create_employee,
    validate_flow_payload,
    validate_reorder_payload,
    validate_schedule_flow_fields,
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
    get_flow_by_slug,
    get_profile_by_erp_id,
    list_employee_profiles,
    list_welcome_email_templates,
    reorder_steps,
    save_welcome_email_template,
    serialize_employee_state,
    serialize_flow,
    serialize_welcome_email_template,
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
    scheduled_for = None
    scheduled_automation_ran_at = None
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
            scheduled_for = assignment.scheduled_for.isoformat() if assignment.scheduled_for else None
            scheduled_automation_ran_at = (
                assignment.scheduled_automation_ran_at.isoformat()
                if assignment.scheduled_automation_ran_at
                else None
            )

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
        "scheduled_for": scheduled_for,
        "scheduled_automation_ran_at": scheduled_automation_ran_at,
        "leder_id": person.leder.legacy_id if person.leder_id else None,
        "leder_name": person.leder.name if person.leder_id else None,
        "buddy_id": person.buddy.legacy_id if person.buddy_id else None,
        "buddy_name": person.buddy.name if person.buddy_id else None,
        "country": op.country if op is not None else "DK",
        "start_date": op.start_date.isoformat() if op is not None and op.start_date else None,
    }


@require_manager_api
@require_http_methods(["GET"])
def people_list(request: HttpRequest):
    """Return all Person records with team + onboarding status.

    GET /api/onboarding/manage/people
    """
    from apps.planner.models import Person

    people = (
        Person.objects.select_related("leder", "buddy")
        .prefetch_related(
            "team_memberships",
            "onboarding_profile__assignments__flow",
        )
        .order_by("name")
    )
    return JsonResponse(
        {"results": [_serialize_person_for_employees_tab(p) for p in people]}
    )


@require_manager_api
@require_http_methods(["PATCH"])
def person_roles(request: HttpRequest, legacy_id: str):
    """Set a Person's leder ('leder' — the manager they report to) and buddy.

    PATCH /api/onboarding/manage/people/<legacy_id>/roles
    Body: {"leder_id": "E1000" | null, "buddy_id": "E1001" | null}

    Both keys are optional — an absent key leaves that field untouched;
    ``null`` clears it. This is the same underlying ``Person.leder``/
    ``Person.buddy`` the "Tildel flow" dialog sets — exposed here too so
    they're editable from the employee editor directly (see
    ``planner.models.Person`` — these fields are visible/editable anywhere
    a Person is shown, not just at flow-attach time), and from the planner
    app's own Person editor via ``PUT /planner/api/people/<id>``.
    """
    from apps.planner.models import Person

    person = Person.objects.filter(legacy_id=legacy_id).first()
    if person is None:
        return JsonResponse({"detail": "Person not found."}, status=404)

    payload, err = _parse_json_optional(request)
    if err is not None:
        return err

    changed = []
    for field, key in (("leder", "leder_id"), ("buddy", "buddy_id")):
        if key not in payload:
            continue
        raw = payload.get(key)
        if raw in (None, ""):
            setattr(person, field, None)
            changed.append(field)
            continue
        if not isinstance(raw, str):
            return JsonResponse({"detail": f"{key} must be a string or null."}, status=400)
        if raw == legacy_id:
            return JsonResponse({"detail": f"{key} cannot reference the person themselves."}, status=400)
        target = Person.objects.filter(legacy_id=raw).first()
        if target is None:
            return JsonResponse({"detail": f"{key} references an unknown person '{raw}'."}, status=404)
        setattr(person, field, target)
        changed.append(field)

    if changed:
        person.save(update_fields=[*changed, "updated_at"])

    return JsonResponse(_serialize_person_for_employees_tab(person))


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
                f"{getattr(user, 'email', None) or 'You'} hasn't connected Google "
                "yet. Sign in with Google once (top nav) with that account before "
                "attaching a flow — the welcome email and meetings are sent/booked "
                "from it."
            )
        },
        status=400,
    )


@require_manager_api
@require_http_methods(["POST", "DELETE"])
def assign_flow(request: HttpRequest, erp_id: str):
    """Assign/plan (POST) or cancel (DELETE) the onboarding flow for a person.

    POST /api/onboarding/manage/employees/<erp_id>/assign-flow/
    Body: {
      "flow_slug": "some-slug",
      "leder_id": "E1000",        # required — planner Person.legacy_id
      "buddy_id": "E1001",        # required — planner Person.legacy_id
      "start_date": "2026-09-01",     # employee's start date (saved on them;
                                      # meetings are placed relative to it)
      "run_mode": "now" | "on_start_date",  # when email + bookings happen
      "scheduled_for": "2026-09-01",  # legacy alternative to run_mode
      "country": "DK" | "NO",          # optional, defaults to the employee's
      "welcome_email_template_id": 3   # optional, default = language default
    }

    ``leder_id``/``buddy_id`` reference existing planner ``Person`` records
    (neither may be the employee themselves). Resolved and persisted onto
    the employee's ``Person.leder``/``Person.buddy`` fields — so they show
    up (and stay editable) anywhere a Person is edited, not just here — and
    then snapshotted onto the assignment's ``leder_name``/``leder_email``/
    ``buddy_name``/``buddy_email`` the first time this flow is attached
    (see ``services.attach_flow``). Available as the ``{{ leder_name }}``/
    ``{{ leder_email }}``/``{{ buddy_name }}``/``{{ buddy_email }}`` merge
    tags in the welcome email (``welcome_email.py``), and as the default
    meeting organizer for ``calendar_meeting`` steps configured with role
    ``leder``/``buddy`` (an unspecified role also falls back to ``leder`` —
    see ``components.CalendarMeetingComponent``).

    ``scheduled_for`` controls *when* the attach automation below actually
    runs. Today or a past date (the default when omitted) runs it
    immediately, in this request — the original behaviour. A future date
    creates the assignment now but defers the automation entirely; the
    ``run_scheduled_onboarding`` management command (run daily via cron)
    picks it up once that date arrives. Either way the response's
    ``automation`` field reflects what happened: populated outcomes when it
    ran now, or ``{"deferredUntil": "<date>"}`` when it didn't yet.

    This is the one deliberate "attach a flow" action in the system —
    creating an employee never does this as a side effect (see
    ``services.py`` module docstring). Before attaching anything, pre-flight
    checks can block the request outright (400/404, nothing created):

      1. The employee (planner ``Person``) must have an email address.
      2. The acting manager (``request.user``) must have a connected
         Google account.
      3. ``leder_id``/``buddy_id`` must resolve to existing, distinct-from-
         the-employee ``Person`` rows.

    These are hard requirements for what happens next, so we check them
    before creating the assignment rather than creating it and reporting a
    partial failure afterwards.

    Once due (immediately, or later via the cron job — see
    ``automation.run_onboarding_attach_automation``), attaching:
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

    Re-attaching an already-due assignment (idempotent replay) skips steps
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

        from .calendar_booking import OrganizerResolutionError, scheduler_user

        # Whoever sends the welcome email / owns the meetings must have
        # Google connected: the shared scheduler mailbox when configured,
        # otherwise the manager doing the assigning.
        try:
            sender = scheduler_user() or request.user
        except OrganizerResolutionError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        if not has_google_credentials(sender):
            return _manager_google_not_connected_error(sender)

        cleaned, err = validate_schedule_flow_fields(payload or {})
        if err is not None:
            return err

        welcome_template = None
        if cleaned["welcome_email_template_id"]:
            welcome_template = WelcomeEmailTemplate.objects.filter(
                pk=cleaned["welcome_email_template_id"]
            ).first()
            if welcome_template is None:
                return _template_not_found()

        from apps.planner.models import Person

        leder_person = Person.objects.filter(legacy_id=cleaned["leder_id"]).first()
        if leder_person is None:
            return JsonResponse({"detail": f"Leder '{cleaned['leder_id']}' not found."}, status=404)
        if leder_person.legacy_id == person.legacy_id:
            return JsonResponse({"detail": "Leder cannot be the employee themselves."}, status=400)

        buddy_person = Person.objects.filter(legacy_id=cleaned["buddy_id"]).first()
        if buddy_person is None:
            return JsonResponse({"detail": f"Buddy '{cleaned['buddy_id']}' not found."}, status=404)
        if buddy_person.legacy_id == person.legacy_id:
            return JsonResponse({"detail": "Buddy cannot be the employee themselves."}, status=400)
        # ------------------------------------------------------------------

        # Persist leder/buddy on the Person record itself — these are
        # employee attributes visible/editable anywhere Person is shown,
        # not just an attach-time-only choice (see planner.models.Person).
        person_fields_changed = []
        if person.leder_id != leder_person.id:
            person.leder = leder_person
            person_fields_changed.append("leder")
        if person.buddy_id != buddy_person.id:
            person.buddy = buddy_person
            person_fields_changed.append("buddy")
        if person_fields_changed:
            person.save(update_fields=[*person_fields_changed, "updated_at"])

        # Country is an employee attribute too: a change in the dialog is
        # saved on the profile, then snapshotted onto the assignment.
        country = cleaned["country"] or op.country
        if country != op.country:
            op.country = country
            op.save(update_fields=["country", "updated_at"])

        # The start date lives on the employee (it's what meetings are
        # placed relative to), so the dialog's value is saved there.
        if cleaned["start_date"] is not None and op.start_date != cleaned["start_date"]:
            op.start_date = cleaned["start_date"]
            op.save(update_fields=["start_date", "updated_at"])

        today = timezone.localdate()
        if cleaned["run_mode"] == "on_start_date":
            scheduled_for = cleaned["start_date"]
        elif cleaned["run_mode"] == "now":
            scheduled_for = today
        else:  # older API callers
            scheduled_for = cleaned["scheduled_for"] or today
        if scheduled_for < today:
            scheduled_for = today  # clamp — a past date just means "now"

        assignment, is_new = attach_flow(
            profile=op,
            flow=flow,
            requested_by=request.user,
            leder=leder_person,
            buddy=buddy_person,
            scheduled_for=scheduled_for,
            country=country,
            welcome_email_template=welcome_template,
        )

        due = assignment.scheduled_for is None or assignment.scheduled_for <= today
        if due:
            automation = run_onboarding_attach_automation(
                person=person, assignment=assignment, requested_by=request.user
            )
        else:
            automation = {
                "welcomeEmail": None,
                "meetings": None,
                "slackInvite": None,
                "deferredUntil": assignment.scheduled_for.isoformat(),
            }

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


def _template_not_found() -> JsonResponse:
    return JsonResponse({"detail": "Welcome email template not found."}, status=404)


def _clean_template_payload(request):
    """Parse + validate a template save body. Returns (cleaned, error)."""
    payload, err = _parse_json(request)
    if err is not None:
        return None, err
    cleaned, err = validate_welcome_email_template(payload)
    if err is not None:
        return None, err

    from .welcome_email import validate_template_syntax

    try:
        validate_template_syntax(subject=cleaned["subject"], html_body=cleaned["html_body"])
    except ValidationError as exc:
        return None, _validation_error(exc)
    return cleaned, None


@require_manager_api
@require_http_methods(["GET", "POST"])
def welcome_emails_collection(request: HttpRequest):
    """The welcome-email template library ("Velkomstmail" tab).

    GET  /api/onboarding/manage/welcome-emails
         -> {"results": [template, ...], "starter": {"subject", "html_body"}}
         ``starter`` is the built-in content, used to prefill a new template.
    POST /api/onboarding/manage/welcome-emails
         Body: {"name", "language": "da"|"no", "subject", "html_body", "is_default"}
         Rejects bad ``{% %}``/``{{ }}`` syntax with 400 before saving.
    """
    if request.method == "GET":
        return JsonResponse(list_welcome_email_templates())

    cleaned, err = _clean_template_payload(request)
    if err is not None:
        return err
    template = save_welcome_email_template(None, data=cleaned, updated_by=request.user)
    return JsonResponse(serialize_welcome_email_template(template), status=201)


@require_manager_api
@require_http_methods(["GET", "PUT", "DELETE"])
def welcome_emails_detail(request: HttpRequest, template_id: int):
    """GET/PUT/DELETE /api/onboarding/manage/welcome-emails/<id>.

    Deleting a template that assignments picked is fine — they fall back to
    their language's default (``OnboardingAssignment.welcome_email_template``
    is SET_NULL).
    """
    template = WelcomeEmailTemplate.objects.filter(pk=template_id).first()
    if template is None:
        return _template_not_found()

    if request.method == "GET":
        return JsonResponse(serialize_welcome_email_template(template))

    if request.method == "PUT":
        cleaned, err = _clean_template_payload(request)
        if err is not None:
            return err
        template = save_welcome_email_template(template, data=cleaned, updated_by=request.user)
        return JsonResponse(serialize_welcome_email_template(template))

    template.delete()
    return JsonResponse({"deleted": True, "id": template_id})


@require_manager_api
@require_http_methods(["POST"])
def welcome_email_preview(request: HttpRequest):
    """Render a welcome email without sending it.

    POST /api/onboarding/manage/welcome-emails/preview
    Body (all optional): {
      "subject": "...", "html_body": "...",   # preview unsaved draft content
      "template_id": 3,                        # ...or a saved template
      "country": "DK" | "NO",                  # language of steps / default template
      "flow_slug": "bct-onboarding",           # whose steps to list (default flow)
      "erp_id": "E1234",                       # render with a real employee
      "buddy_name", "buddy_email", "leder_name", "leder_email"
    }

    Without ``subject``/``html_body`` or ``template_id`` this previews the
    default template for ``country``'s language — what an assignment with
    no explicit choice would send.

    Returns {"subject", "html", "plain", "source", "template_id"}.
    """
    payload, err = _parse_json_optional(request)
    if err is not None:
        return err
    cleaned, err = validate_welcome_email_preview(payload)
    if err is not None:
        return err

    from apps.planner.models import Person

    from .countries import language_for_country, normalize_country

    person = None
    profile = None
    if cleaned["erp_id"]:
        person = Person.objects.select_related("onboarding_profile").filter(
            legacy_id=cleaned["erp_id"]
        ).first()
        if person is None:
            return JsonResponse({"detail": "Person not found."}, status=404)
        profile = getattr(person, "onboarding_profile", None)

    if cleaned["flow_slug"]:
        flow = _get_flow(cleaned["flow_slug"])
        if flow is None:
            return _flow_not_found()
    else:
        flow = (
            OnboardingFlow.objects.filter(is_default=True).first()
            or OnboardingFlow.objects.filter(is_active=True).first()
        )

    country = normalize_country(cleaned["country"] or getattr(profile, "country", None))

    from .welcome_email import (
        build_merge_context,
        html_to_plain,
        render_merge_tags,
        resolve_welcome_email_template,
    )

    class _SamplePerson:
        name = "Anna Andersen"
        email = "anna.andersen@example.com"

    class _NoFlow:
        name = "Onboarding"

        class steps:  # noqa: N801 — mimics the related manager
            @staticmethod
            def all():
                return FlowStep.objects.none()

    context = build_merge_context(
        person=person or _SamplePerson(),
        flow=flow or _NoFlow(),
        requested_by=request.user,
        buddy_name=cleaned["buddy_name"],
        buddy_email=cleaned["buddy_email"],
        leder_name=cleaned["leder_name"],
        leder_email=cleaned["leder_email"],
        profile=profile,
        country=country,
    )

    template_id = None
    if "subject" in cleaned:
        subject_template, html_template, source = cleaned["subject"], cleaned["html_body"], "draft"
    else:
        template, source = resolve_welcome_email_template(
            template_id=cleaned["template_id"], language=language_for_country(country)
        )
        subject_template, html_template = template.subject, template.html_body
        template_id = template.pk

    try:
        subject = render_merge_tags(subject_template, context)
        html = render_merge_tags(html_template, context)
    except Exception as exc:
        return JsonResponse({"detail": f"Could not render template: {exc}"}, status=400)

    return JsonResponse(
        {
            "subject": subject,
            "html": html,
            "plain": html_to_plain(html),
            "source": source,
            "template_id": template_id,
        }
    )


# ---------------------------------------------------------------------------
# Onboarding settings ("Indstillinger" tab) + employee documents (Drive)
# ---------------------------------------------------------------------------


def _serialize_onboarding_settings() -> dict:
    from django.conf import settings as dj_settings

    from apps.planner.google.credentials import has_google_credentials

    from .calendar_booking import OrganizerResolutionError, scheduler_email, scheduler_user
    from .drive import folder_url
    from .google_auth import has_drive_access
    from .models import OnboardingSettings

    cfg = OnboardingSettings.load()
    email = scheduler_email()
    if cfg.system_email is None:
        source = "default" if email else "none"
    else:
        source = "setting" if email else "none"
    try:
        user = scheduler_user()
    except OrganizerResolutionError:
        user = None
    return {
        "drive_root_folder_id": cfg.drive_root_folder_id,
        "drive_root_folder_name": cfg.drive_root_folder_name,
        "drive_root_folder_url": folder_url(cfg.drive_root_folder_id),
        "updated_at": cfg.updated_at.isoformat() if cfg.drive_root_folder_id else None,
        "updated_by": getattr(cfg.updated_by, "email", None) if cfg.updated_by_id else None,
        "scheduler_email": email,
        "system_email_source": source,
        "system_email_default": (getattr(dj_settings, "ONBOARDING_SCHEDULER_EMAIL", "") or "").strip(),
        "scheduler_signed_in": bool(user is not None and has_google_credentials(user)),
        "scheduler_drive_connected": bool(user is not None and has_drive_access(user)),
    }


@require_manager_api
@require_http_methods(["GET", "PUT"])
def onboarding_settings(request: HttpRequest):
    """GET/PUT /api/onboarding/manage/settings

    PUT body (each key optional):
      {"system_email": "x@..." | "" | null,   # "" = none, null = deploy default
       "drive_root_folder": "<Drive folder link or id>"}  # checked against Drive
    The system account owns onboarding meetings, sends the welcome email and
    uploads to Drive.
    """
    from .drive import DriveError, verify_root_folder
    from .models import OnboardingSettings

    if request.method == "GET":
        return JsonResponse(_serialize_onboarding_settings())

    payload, err = _parse_json(request)
    if err is not None:
        return err
    payload = payload or {}
    if not isinstance(payload, dict):
        return JsonResponse({"detail": "Body must be a JSON object."}, status=400)

    cfg = OnboardingSettings.load()

    # Partial update: only the keys that are present are changed.
    if "system_email" in payload:
        raw_email = payload.get("system_email")
        if raw_email is not None and not isinstance(raw_email, str):
            return JsonResponse({"detail": "system_email must be a string or null."}, status=400)
        if raw_email is None:
            cfg.system_email = None  # back to the deploy default
        else:
            raw_email = raw_email.strip().lower()
            if raw_email:
                from django.core.validators import validate_email

                try:
                    validate_email(raw_email)
                except ValidationError:
                    return JsonResponse({"detail": "Ugyldig e-mailadresse."}, status=400)
            cfg.system_email = raw_email  # "" = no system account
        cfg.save(update_fields=["system_email", "updated_at"])

    if "drive_root_folder" in payload:
        raw = payload.get("drive_root_folder") or ""
        if not isinstance(raw, str):
            return JsonResponse({"detail": "drive_root_folder must be a string."}, status=400)
        if raw.strip():
            try:
                folder_id, name = verify_root_folder(raw)
            except DriveError as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
            cfg.drive_root_folder_id, cfg.drive_root_folder_name = folder_id, name
        else:
            cfg.drive_root_folder_id, cfg.drive_root_folder_name = "", ""

    cfg.updated_by = request.user
    cfg.save()
    return JsonResponse(_serialize_onboarding_settings())


def _serialize_document(doc) -> dict:
    return {
        "id": doc.pk,
        "name": doc.name,
        "web_view_link": doc.web_view_link,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "uploaded_at": doc.created_at.isoformat(),
        "uploaded_by": getattr(doc.uploaded_by, "email", None) if doc.uploaded_by_id else None,
    }


@require_manager_api
@require_http_methods(["GET", "POST"])
def employee_documents(request: HttpRequest, erp_id: str):
    """List (GET) or upload (POST, multipart ``file`` — one or more) the
    employee's documents. Uploads go to "<Name> (<ERP id>)" inside the
    Employee folder in Google Drive — see ``drive.py``.
    """
    from apps.planner.models import Person

    from .drive import DriveError, folder_url, upload_employee_documents

    person = Person.objects.select_related("onboarding_profile").filter(legacy_id=erp_id).first()
    if person is None:
        return JsonResponse({"detail": "Person not found."}, status=404)
    profile = getattr(person, "onboarding_profile", None)
    if profile is None:
        return JsonResponse(
            {"detail": "Gem medarbejderen først — dokumenter kræver en onboarding-profil."},
            status=400,
        )

    if request.method == "POST":
        try:
            upload_employee_documents(
                profile=profile, files=request.FILES.getlist("file"), uploaded_by=request.user
            )
        except DriveError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        profile.refresh_from_db()

    docs = profile.documents.select_related("uploaded_by")
    return JsonResponse(
        {
            "folder_url": folder_url(profile.drive_folder_id),
            "results": [_serialize_document(d) for d in docs],
        },
        status=201 if request.method == "POST" else 200,
    )
