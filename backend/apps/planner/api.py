from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_GET, require_http_methods

from .models import (
    CheckInMeeting,
    CustomDate,
    FunctionTag,
    JournalEntry,
    JournalEntryFile,
    ManagerProfile,
    Person,
    PlannerConfig,
    Project,
)
from .schemas import (
    validate_booking_payload,
    validate_freebusy_query,
    validate_function_tag_payload,
    validate_journal_entry_payload,
    validate_person_payload,
    validate_project_payload,
    validate_state_payload,
)
from .services.state import (
    DEFAULT_WORK_HOURS,
    _bump_state_version,
    build_state_payload,
    is_manager_or_admin,
    persist_state,
    replace_custom_dates,
    replace_function_tags,
    replace_team_membership,
    serialize_journal_entry,
    serialize_person,
    soft_delete_journal_entry,
    update_planner_config,
    upsert_function_tag,
    upsert_journal_entry,
    upsert_manager,
    upsert_person,
    upsert_project,
)
from .services.state import (
    delete_person as delete_person_service,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json(request: HttpRequest):
    try:
        return json.loads(request.body or "{}"), None
    except json.JSONDecodeError:
        return None, HttpResponseBadRequest("Invalid JSON")


def _require_manager(view_func: Callable):
    """Decorator: 403 unless the request user is manager/admin/superuser."""

    def wrapped(request: HttpRequest, *args, **kwargs):
        if not is_manager_or_admin(request.user):
            return JsonResponse(
                {"detail": "Only manager/admin users can perform this action."}, status=403
            )
        return view_func(request, *args, **kwargs)

    wrapped.__name__ = view_func.__name__
    return wrapped


def _validation_error(result) -> JsonResponse:
    return JsonResponse({"detail": "Invalid payload", "errors": result.errors}, status=400)


# ---------------------------------------------------------------------------
# Aggregate state (legacy, deprecated for writes)
# ---------------------------------------------------------------------------


@login_required
@require_GET
def state_get(request: HttpRequest):
    return JsonResponse(build_state_payload())


@login_required
@require_http_methods(["PUT"])
@_require_manager
def state_put(request: HttpRequest):
    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_state_payload(payload)
    if not validation.valid:
        return _validation_error(validation)
    saved = persist_state(payload, request.user)
    return JsonResponse(saved)


@login_required
@require_GET
def state_key_get(request: HttpRequest, key: str):
    payload = build_state_payload()
    if key not in payload:
        return JsonResponse({"detail": f"Unknown key '{key}'."}, status=404)
    return JsonResponse({"key": key, "value": payload[key], "meta": payload.get("_meta", {})})


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def people_collection(request: HttpRequest):
    if request.method == "GET":
        people = [serialize_person(p) for p in Person.objects.prefetch_related("projects", "function").all()]
        return JsonResponse({"people": people})

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can create people."}, status=403)

    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_person_payload(payload, require_id=True)
    if not validation.valid:
        return _validation_error(validation)
    if Person.objects.filter(legacy_id=payload.get("id")).exists():
        return JsonResponse({"detail": "Person with this id already exists."}, status=409)
    with transaction.atomic():
        person = upsert_person(payload, request.user)
        _bump_state_version()
    return JsonResponse(serialize_person(person), status=201)


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def people_detail(request: HttpRequest, person_id: str):
    person = Person.objects.prefetch_related("projects", "function").filter(legacy_id=person_id).first()
    if request.method == "GET":
        if not person:
            return JsonResponse({"detail": "Not found."}, status=404)
        return JsonResponse(serialize_person(person))

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can modify people."}, status=403)

    if request.method == "DELETE":
        if not person:
            return JsonResponse({"detail": "Not found."}, status=404)
        with transaction.atomic():
            delete_person_service(person_id)
            _bump_state_version()
        return JsonResponse({"detail": "Deleted.", "id": person_id})

    payload, err = _parse_json(request)
    if err:
        return err
    payload = {**payload, "id": person_id}
    validation = validate_person_payload(payload, require_id=True)
    if not validation.valid:
        return _validation_error(validation)
    with transaction.atomic():
        person = upsert_person(payload, request.user)
        _bump_state_version()
    return JsonResponse(serialize_person(person))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def projects_collection(request: HttpRequest):
    if request.method == "GET":
        projects = [
            {"name": p.name, "description": p.description, "color": p.color}
            for p in Project.objects.order_by("name")
        ]
        return JsonResponse({"projects": projects})

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can create projects."}, status=403)

    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_project_payload(payload)
    if not validation.valid:
        return _validation_error(validation)
    if Project.objects.filter(name=payload.get("name")).exists():
        return JsonResponse({"detail": "Project with this name already exists."}, status=409)
    with transaction.atomic():
        project = upsert_project(payload, request.user)
        _bump_state_version()
    return JsonResponse(
        {"name": project.name, "description": project.description, "color": project.color},
        status=201,
    )


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def projects_detail(request: HttpRequest, name: str):
    project = Project.objects.filter(name=name).first()
    if request.method == "GET":
        if not project:
            return JsonResponse({"detail": "Not found."}, status=404)
        return JsonResponse({"name": project.name, "description": project.description, "color": project.color})

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can modify projects."}, status=403)

    if request.method == "DELETE":
        if not project:
            return JsonResponse({"detail": "Not found."}, status=404)
        with transaction.atomic():
            project.delete()
            _bump_state_version()
        return JsonResponse({"detail": "Deleted.", "name": name})

    payload, err = _parse_json(request)
    if err:
        return err
    payload = {**payload, "name": name}
    validation = validate_project_payload(payload)
    if not validation.valid:
        return _validation_error(validation)
    with transaction.atomic():
        project = upsert_project(payload, request.user)
        _bump_state_version()
    return JsonResponse({"name": project.name, "description": project.description, "color": project.color})


# ---------------------------------------------------------------------------
# Function tags
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST", "PUT"])
def function_tags_collection(request: HttpRequest):
    if request.method == "GET":
        tags = [
            {"label": t.label, "displayName": t.display_name, "color": t.color}
            for t in FunctionTag.objects.order_by("display_name")
        ]
        return JsonResponse({"fnTags": tags})

    if request.method == "PUT":
        if not is_manager_or_admin(request.user):
            return JsonResponse({"detail": "Only manager/admin users can replace function tags."}, status=403)
        payload, err = _parse_json(request)
        if err:
            return err
        rows = payload.get("fnTags", [])
        if not isinstance(rows, list):
            return JsonResponse({"detail": "fnTags must be a list."}, status=400)
        with transaction.atomic():
            replace_function_tags(rows, request.user)
            _bump_state_version()
        tags = [
            {"label": t.label, "displayName": t.display_name, "color": t.color}
            for t in FunctionTag.objects.order_by("display_name")
        ]
        return JsonResponse({"fnTags": tags})

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can create function tags."}, status=403)

    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_function_tag_payload(payload)
    if not validation.valid:
        return _validation_error(validation)
    if FunctionTag.objects.filter(display_name=payload.get("displayName")).exists():
        return JsonResponse({"detail": "FunctionTag with this displayName already exists."}, status=409)
    with transaction.atomic():
        tag = upsert_function_tag(payload, request.user)
        _bump_state_version()
    return JsonResponse(
        {"label": tag.label, "displayName": tag.display_name, "color": tag.color}, status=201
    )


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["PUT"])
@_require_manager
def teams_membership_put(request: HttpRequest, team: str):
    if team not in {"team-1", "team-2", "team-3", "pool"}:
        return JsonResponse({"detail": f"Unknown team '{team}'."}, status=404)
    payload, err = _parse_json(request)
    if err:
        return err
    person_ids = payload.get("personIds", [])
    if not isinstance(person_ids, list) or not all(isinstance(p, str) for p in person_ids):
        return JsonResponse({"detail": "personIds must be a list of person ids."}, status=400)
    with transaction.atomic():
        replace_team_membership(team, person_ids, request.user)
        _bump_state_version()
    return JsonResponse({"team": team, "personIds": person_ids})


# ---------------------------------------------------------------------------
# Managers
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def managers_collection(request: HttpRequest):
    if request.method == "GET":
        managers = list(ManagerProfile.objects.order_by("id").values_list("legacy_id", flat=True))
        return JsonResponse({"mgrs": managers})

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can create managers."}, status=403)

    payload, err = _parse_json(request)
    if err:
        return err
    legacy_id = (payload.get("id") or "").strip()
    if not legacy_id:
        return JsonResponse({"detail": "id is required."}, status=400)
    with transaction.atomic():
        manager = upsert_manager(legacy_id, request.user)
        _bump_state_version()
    return JsonResponse({"id": manager.legacy_id}, status=201)


@login_required
@require_http_methods(["DELETE"])
@_require_manager
def managers_detail(request: HttpRequest, manager_id: str):
    deleted, _ = ManagerProfile.objects.filter(legacy_id=manager_id).delete()
    if not deleted:
        return JsonResponse({"detail": "Not found."}, status=404)
    _bump_state_version()
    return JsonResponse({"detail": "Deleted.", "id": manager_id})


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def journal_collection(request: HttpRequest):
    if request.method == "GET":
        person_id = request.GET.get("personId")
        qs = JournalEntry.objects.select_related("person", "manager")
        if person_id:
            qs = qs.filter(person__legacy_id=person_id)
        qs = qs.order_by("-date", "-updated_at")
        entries = [serialize_journal_entry(e) for e in qs]
        return JsonResponse({"entries": entries})

    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_journal_entry_payload(payload, require_id=True)
    if not validation.valid:
        return _validation_error(validation)
    try:
        with transaction.atomic():
            entry = upsert_journal_entry(payload, request.user)
            _bump_state_version()
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse(serialize_journal_entry(entry), status=201)


@login_required
@require_http_methods(["POST"])
def journal_file_upload(request: HttpRequest, entry_id: str):
    """Upload a single file attachment for a journal entry.

    Multipart form-data: ``file`` field. Returns the JournalEntryFile JSON.
    """
    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can upload attachments."}, status=403)
    entry = JournalEntry.objects.filter(entry_id=entry_id).first()
    if not entry:
        return JsonResponse({"detail": "Journal entry not found."}, status=404)
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"detail": "Missing 'file' multipart field."}, status=400)
    if upload.size > 25 * 1024 * 1024:
        return JsonResponse({"detail": "File too large (max 25 MB)."}, status=413)

    attachment = JournalEntryFile.objects.create(
        entry=entry,
        name=upload.name[:255],
        content_type=upload.content_type or "",
        size_bytes=upload.size,
        file=upload,
        created_by=request.user,
        updated_by=request.user,
    )

    files = list(entry.files or [])
    files.append({
        "id": attachment.pk,
        "name": attachment.name,
        "type": attachment.content_type,
        "size": attachment.size_bytes,
        "url": attachment.file.url,
    })
    entry.files = files
    entry.save(update_fields=["files", "updated_at"])
    _bump_state_version()
    return JsonResponse(attachment.serialize(), status=201)


@login_required
@require_http_methods(["DELETE"])
def journal_file_delete(request: HttpRequest, entry_id: str, file_id: int):
    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can delete attachments."}, status=403)
    entry = JournalEntry.objects.filter(entry_id=entry_id).first()
    if not entry:
        return JsonResponse({"detail": "Journal entry not found."}, status=404)
    attachment = JournalEntryFile.objects.filter(pk=file_id, entry=entry).first()
    if not attachment:
        return JsonResponse({"detail": "Attachment not found."}, status=404)
    attachment.file.delete(save=False)
    attachment.delete()
    entry.files = [f for f in (entry.files or []) if f.get("id") != file_id]
    entry.save(update_fields=["files", "updated_at"])
    _bump_state_version()
    return JsonResponse({"detail": "Deleted."})


@login_required
@require_http_methods(["GET", "PUT", "DELETE"])
def journal_detail(request: HttpRequest, entry_id: str):
    entry = JournalEntry.objects.select_related("person", "manager").filter(entry_id=entry_id).first()
    if request.method == "GET":
        if not entry:
            return JsonResponse({"detail": "Not found."}, status=404)
        return JsonResponse(serialize_journal_entry(entry))

    if request.method == "DELETE":
        if not entry:
            return JsonResponse({"detail": "Not found."}, status=404)
        with transaction.atomic():
            soft_delete_journal_entry(entry_id)
            _bump_state_version()
        return JsonResponse({"detail": "Soft-deleted.", "id": entry_id})

    payload, err = _parse_json(request)
    if err:
        return err
    payload = {**payload, "id": entry_id}
    validation = validate_journal_entry_payload(payload, require_id=True)
    if not validation.valid:
        return _validation_error(validation)
    try:
        with transaction.atomic():
            entry = upsert_journal_entry(payload, request.user)
            _bump_state_version()
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse(serialize_journal_entry(entry))


# ---------------------------------------------------------------------------
# Planner config + custom dates
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "PUT"])
def config_endpoint(request: HttpRequest):
    cfg = PlannerConfig.singleton()
    if request.method == "GET":
        return JsonResponse(
            {
                "startDate": cfg.start_date.isoformat(),
                "workHours": cfg.work_hours or DEFAULT_WORK_HOURS,
                "viewedMgrFilter": cfg.viewed_mgr_filter,
                "weekOffset": cfg.week_offset,
                "weeksPerSession": cfg.weeks_per_session or 2,
            }
        )
    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can update config."}, status=403)
    payload, err = _parse_json(request)
    if err:
        return err
    with transaction.atomic():
        cfg = update_planner_config(payload, request.user)
        _bump_state_version()
    return JsonResponse(
        {
            "startDate": cfg.start_date.isoformat(),
            "workHours": cfg.work_hours or DEFAULT_WORK_HOURS,
            "viewedMgrFilter": cfg.viewed_mgr_filter,
            "weekOffset": cfg.week_offset,
            "weeksPerSession": cfg.weeks_per_session or 2,
        }
    )


@login_required
@require_http_methods(["GET", "PUT"])
def custom_dates_endpoint(request: HttpRequest):
    if request.method == "GET":
        values = {row.key: row.value for row in CustomDate.objects.order_by("key")}
        return JsonResponse({"customDates": values})
    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can update custom dates."}, status=403)
    payload, err = _parse_json(request)
    if err:
        return err
    values = payload.get("customDates", payload)
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
        return JsonResponse({"detail": "customDates must be a {string: string} object."}, status=400)
    with transaction.atomic():
        replace_custom_dates(values, request.user)
        _bump_state_version()
    return JsonResponse({"customDates": values})


# ---------------------------------------------------------------------------
# FreeBusy + Bookings (server-side Google Calendar integration)
# ---------------------------------------------------------------------------


def _parse_iso_param(value: str) -> datetime | None:
    if not value:
        return None
    try:
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@login_required
@require_GET
def freebusy_endpoint(request: HttpRequest):
    """Query Google Calendar FreeBusy for a list of attendees.

    Query params:
        from   ISO-8601 datetime (required)
        to     ISO-8601 datetime (required)
        emails comma-separated email list (optional). If omitted, defaults
               to the assigned developers + the requesting manager.
        team   shortcut: instead of emails, fetch all members of this team.
    """
    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can query free/busy."}, status=403)

    params = {
        "from": request.GET.get("from", ""),
        "to": request.GET.get("to", ""),
        "team": request.GET.get("team"),
    }
    validation = validate_freebusy_query(params)
    if not validation.valid:
        return _validation_error(validation)

    time_min = _parse_iso_param(params["from"])
    time_max = _parse_iso_param(params["to"])
    if not time_min or not time_max or time_max <= time_min:
        return JsonResponse({"detail": "Invalid time window."}, status=400)

    emails_param = request.GET.get("emails", "")
    emails: list[str] = [e.strip() for e in emails_param.split(",") if e.strip()]

    if not emails and params["team"]:
        from .models import TeamMembership

        emails = list(
            TeamMembership.objects.filter(team=params["team"])
            .select_related("person")
            .values_list("person__email", flat=True)
        )
        emails = [e for e in emails if e]

    if not emails:
        return JsonResponse({"calendars": {}, "detail": "No emails to query."})

    try:
        from .google.credentials import GoogleCredentialsUnavailable
        from .google.freebusy import query_freebusy
    except ImportError as exc:
        logger.exception("Google API libraries not installed")
        return JsonResponse(
            {"detail": f"Google API libraries unavailable: {exc}"}, status=503
        )

    try:
        result = query_freebusy(
            requesting_user=request.user,
            emails=emails,
            time_min=time_min,
            time_max=time_max,
            timezone=getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen"),
        )
    except GoogleCredentialsUnavailable as exc:
        return JsonResponse({"detail": str(exc), "needs_consent": True}, status=401)
    except Exception as exc:
        logger.exception("FreeBusy query failed")
        return JsonResponse({"detail": f"Calendar API error: {exc}"}, status=502)

    serialized = {
        email: [interval.as_dict() for interval in intervals]
        for email, intervals in result.items()
    }
    return JsonResponse(
        {
            "calendars": serialized,
            "from": time_min.isoformat(),
            "to": time_max.isoformat(),
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def bookings_collection(request: HttpRequest):
    if request.method == "GET":
        manager_id = request.GET.get("managerId")
        person_id = request.GET.get("personId")
        status = request.GET.get("status")
        qs = CheckInMeeting.objects.select_related("manager", "person", "session")
        if manager_id:
            qs = qs.filter(manager__legacy_id=manager_id)
        if person_id:
            qs = qs.filter(person__legacy_id=person_id)
        if status:
            qs = qs.filter(status=status)
        from .services.bookings import serialize_booking

        return JsonResponse(
            {"bookings": [serialize_booking(m) for m in qs.order_by("-starts_at")[:200]]}
        )

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can create bookings."}, status=403)

    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_booking_payload(payload)
    if not validation.valid:
        return _validation_error(validation)

    manager = ManagerProfile.objects.filter(legacy_id=payload["managerId"]).first()
    if not manager:
        return JsonResponse({"detail": "Unknown managerId."}, status=400)
    person = Person.objects.filter(legacy_id=payload["personId"]).first()
    if not person:
        return JsonResponse({"detail": "Unknown personId."}, status=400)
    starts_at = _parse_iso_param(payload["startsAt"])
    if not starts_at:
        return JsonResponse({"detail": "Invalid startsAt."}, status=400)

    from .google.credentials import GoogleCredentialsUnavailable
    from .services.bookings import (
        BookingError,
        BookingRequest,
        GoogleBookingError,
        create_booking,
        serialize_booking,
    )

    req = BookingRequest(
        manager=manager,
        person=person,
        organizer_user=request.user,
        starts_at=starts_at,
        duration_minutes=int(payload.get("durationMinutes", 30)),
        title=payload.get("title", "Check-in samtale"),
        agenda=payload.get("agenda", ""),
        timezone=getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen"),
    )
    try:
        meeting = create_booking(req, audit_user=request.user)
    except BookingError as exc:
        return JsonResponse({"detail": str(exc)}, status=409)
    except GoogleCredentialsUnavailable as exc:
        return JsonResponse({"detail": str(exc), "needs_consent": True}, status=401)
    except GoogleBookingError as exc:
        return JsonResponse({"detail": f"Google rejected the booking: {exc}"}, status=502)

    return JsonResponse(serialize_booking(meeting), status=201)


@login_required
@require_http_methods(["GET", "DELETE"])
def bookings_detail(request: HttpRequest, booking_id: int):
    meeting = (
        CheckInMeeting.objects.select_related("manager", "person", "session")
        .filter(pk=booking_id)
        .first()
    )
    if not meeting:
        return JsonResponse({"detail": "Not found."}, status=404)

    from .services.bookings import cancel_booking, serialize_booking

    if request.method == "GET":
        return JsonResponse(serialize_booking(meeting))

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can cancel bookings."}, status=403)

    cancel_booking(meeting, organizer_user=request.user, audit_user=request.user)
    return JsonResponse(serialize_booking(meeting))


# ---------------------------------------------------------------------------
# Rotation introspection (lets the UI render upcoming sessions without
# duplicating the rotation logic on the client).
# ---------------------------------------------------------------------------


@login_required
@require_GET
def rotation_endpoint(request: HttpRequest):
    from datetime import date as date_cls

    from .services.rotation import (
        get_or_create_session,
        upcoming_session_windows,
    )

    try:
        n = int(request.GET.get("upcoming", "4"))
    except ValueError:
        n = 4
    n = max(1, min(n, 52))

    from_date = None
    from_raw = request.GET.get("from")
    if from_raw:
        try:
            from_date = date_cls.fromisoformat(from_raw[:10])
        except ValueError:
            return JsonResponse({"detail": "Invalid 'from' date (use YYYY-MM-DD)."}, status=400)

    out = []
    for window in upcoming_session_windows(n, from_date=from_date):
        teams = []
        for team in ("team-1", "team-2", "team-3"):
            session = get_or_create_session(
                cycle_start=window.cycle_start,
                session_index=window.session_index,
                team=team,
            )
            teams.append(
                {
                    "team": team,
                    "managerId": session.manager.legacy_id if session else None,
                }
            )
        out.append(
            {
                "cycleStart": window.cycle_start.isoformat(),
                "sessionIndex": window.session_index,
                "weekStart": window.week_start.isoformat(),
                "weekEnd": window.week_end.isoformat(),
                "teams": teams,
            }
        )
    return JsonResponse({"sessions": out})
