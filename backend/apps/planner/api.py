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
    normalize_journal_entry_payload,
    validate_booking_payload,
    validate_calendar_share_payload,
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
# Manager booking settings
# ---------------------------------------------------------------------------

_VALID_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}


def _validate_blocked_windows(windows: object) -> str | None:
    """Return an error message, or None if valid."""
    if not isinstance(windows, list):
        return "bookingBlockedWindows must be a list."
    for i, w in enumerate(windows):
        if not isinstance(w, dict):
            return f"bookingBlockedWindows[{i}] must be an object."
        days = w.get("days")
        if days != "all" and not (
            isinstance(days, list) and all(isinstance(d, str) and d in _VALID_WEEKDAYS for d in days)
        ):
            return (
                f'bookingBlockedWindows[{i}].days must be "all" or a list of '
                f"weekday names (monday–sunday)."
            )
        for field in ("start_time", "end_time"):
            val = w.get(field)
            if not isinstance(val, str) or len(val) != 5 or val[2] != ":":
                return f'bookingBlockedWindows[{i}].{field} must be "HH:MM".'
    return None


def _serialize_manager_settings(manager: "ManagerProfile") -> dict:
    return {
        "managerId": manager.legacy_id,
        "autoBookingEnabled": manager.auto_booking_enabled,
        "bookingBlockedWindows": manager.booking_blocked_windows,
        "preferredMeetingDurationMinutes": manager.preferred_meeting_duration_minutes,
        "bookingPreferredDays": manager.booking_preferred_days,
        "notificationEmail": manager.notification_email,
    }


@login_required
@require_http_methods(["GET", "PUT"])
def manager_settings(request: HttpRequest, manager_id: str):
    """GET/PUT the booking preferences for a single manager.

    GET is open to any authenticated user (manager IDs are not secret).
    PUT requires the user to be the manager themselves, or an admin/superuser.
    """
    manager = ManagerProfile.objects.filter(legacy_id=manager_id).first()
    if not manager:
        return JsonResponse({"detail": "Manager not found."}, status=404)

    if request.method == "GET":
        return JsonResponse(_serialize_manager_settings(manager))

    # --- PUT ---
    # Only the manager themselves or an admin may change these settings.
    own_manager = getattr(request.user, "manager_profile", None)
    is_own = own_manager is not None and own_manager.pk == manager.pk
    if not is_own and not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "You may only update your own settings."}, status=403)

    payload, err = _parse_json(request)
    if err:
        return err

    # Apply each field if present in the payload (partial update).
    if "autoBookingEnabled" in payload:
        val = payload["autoBookingEnabled"]
        if not isinstance(val, bool):
            return JsonResponse({"detail": "autoBookingEnabled must be a boolean."}, status=400)
        manager.auto_booking_enabled = val

    if "bookingBlockedWindows" in payload:
        err_msg = _validate_blocked_windows(payload["bookingBlockedWindows"])
        if err_msg:
            return JsonResponse({"detail": err_msg}, status=400)
        manager.booking_blocked_windows = payload["bookingBlockedWindows"]

    if "preferredMeetingDurationMinutes" in payload:
        dur = payload["preferredMeetingDurationMinutes"]
        if not isinstance(dur, int) or dur < 15 or dur > 120:
            return JsonResponse(
                {"detail": "preferredMeetingDurationMinutes must be an integer between 15 and 120."},
                status=400,
            )
        manager.preferred_meeting_duration_minutes = dur

    if "bookingPreferredDays" in payload:
        days = payload["bookingPreferredDays"]
        if not isinstance(days, list) or not all(
            isinstance(d, str) and d in _VALID_WEEKDAYS for d in days
        ):
            return JsonResponse(
                {"detail": "bookingPreferredDays must be a list of weekday names (monday–sunday)."},
                status=400,
            )
        manager.booking_preferred_days = days

    if "notificationEmail" in payload:
        email = payload["notificationEmail"]
        if not isinstance(email, str):
            return JsonResponse({"detail": "notificationEmail must be a string."}, status=400)
        email = email.strip()
        if email:
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError
            try:
                validate_email(email)
            except DjangoValidationError:
                return JsonResponse({"detail": "notificationEmail is not a valid email address."}, status=400)
        manager.notification_email = email

    manager.updated_by = request.user
    manager.save()
    return JsonResponse(_serialize_manager_settings(manager))


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
    payload = normalize_journal_entry_payload(payload)
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
    payload = normalize_journal_entry_payload({**payload, "id": entry_id})
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
        busy_result, calendar_errors = query_freebusy(
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
        detail = f"Calendar API error: {exc}"
        if "invalid_scope" in str(exc).lower():
            return JsonResponse(
                {
                    "detail": (
                        "Google-tilladelse skal opdateres. Log ud og log ind igen "
                        "(accepter kalender-tilladelser)."
                    ),
                    "needs_consent": True,
                },
                status=401,
            )
        return JsonResponse({"detail": detail}, status=502)

    serialized = {
        email: [interval.as_dict() for interval in intervals]
        for email, intervals in busy_result.items()
    }
    return JsonResponse(
        {
            "calendars": serialized,
            "errors": calendar_errors,
            "from": time_min.isoformat(),
            "to": time_max.isoformat(),
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def calendar_share_requests(request: HttpRequest):
    """Ask employees (by email) to share Google Calendar free/busy with the manager."""
    if not is_manager_or_admin(request.user):
        return JsonResponse(
            {"detail": "Only manager/admin users can send calendar share requests."},
            status=403,
        )

    if request.method == "GET":
        from .services.calendar_share import serialize_share_status

        raw_ids = request.GET.get("person_ids", "")
        person_ids = [p.strip() for p in raw_ids.split(",") if p.strip()]
        if not person_ids:
            return JsonResponse({"detail": "person_ids query param required."}, status=400)
        people = Person.objects.filter(legacy_id__in=person_ids)
        by_id = {p.legacy_id: p for p in people}
        results = []
        for pid in person_ids:
            person = by_id.get(pid)
            if person is None:
                results.append({"person_id": pid, "error": "Person not found."})
                continue
            results.append(
                serialize_share_status(person=person, requested_by=request.user)
            )
        return JsonResponse({"results": results})

    payload, err = _parse_json(request)
    if err:
        return err
    validation = validate_calendar_share_payload(payload)
    if not validation.valid:
        return _validation_error(validation)

    from .services.calendar_share import send_share_requests

    summary = send_share_requests(
        person_ids=payload["person_ids"],
        requested_by=request.user,
        force=bool(payload.get("force", False)),
    )
    return JsonResponse(summary)


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


@login_required
@require_http_methods(["POST"])
def bookings_rebook(request: HttpRequest, booking_id: int):
    """POST /api/bookings/<id>/rebook

    Cancels the original meeting (if not already cancelled) and books a
    replacement in the same session window.

    Optional body fields:
      ``startsAt`` -- ISO-8601 datetime for an explicit new time.  When omitted
                     the slot-finder finds the next free slot.
      ``durationMinutes`` -- override meeting length.
    """
    meeting = (
        CheckInMeeting.objects.select_related(
            "manager", "manager__user", "manager__person", "person", "session"
        )
        .filter(pk=booking_id)
        .first()
    )
    if not meeting:
        return JsonResponse({"detail": "Not found."}, status=404)

    if not is_manager_or_admin(request.user):
        return JsonResponse({"detail": "Only manager/admin users can rebook meetings."}, status=403)

    if meeting.status not in ("declined", "scheduled", "cancelled"):
        return JsonResponse(
            {"detail": f"Cannot rebook a meeting with status '{meeting.status}'."},
            status=409,
        )

    payload, err = _parse_json(request)
    if err:
        return err

    from .services.bookings import (
        BookingError,
        BookingRequest,
        GoogleBookingError,
        cancel_booking,
        create_booking,
        serialize_booking,
    )
    from .services.rotation import SessionWindow, session_window_for, weeks_per_session_value
    from .google.credentials import GoogleCredentialsUnavailable
    from datetime import timedelta

    # Determine the session window to search in.  Prefer the existing session's
    # window; fall back to the window that contains the original starts_at.
    if meeting.session:
        wps = weeks_per_session_value()
        week_start = meeting.session.cycle_start + timedelta(
            weeks=meeting.session.session_index * wps
        )
        week_end = week_start + timedelta(weeks=wps) - timedelta(days=1)
        window = SessionWindow(
            cycle_start=meeting.session.cycle_start,
            session_index=meeting.session.session_index,
            week_start=week_start,
            week_end=week_end,
        )
    else:
        window = session_window_for(meeting.starts_at)

    duration_minutes = int(payload.get("durationMinutes", meeting.duration_minutes or 30))
    starts_at_raw = payload.get("startsAt")

    if starts_at_raw:
        # Explicit time provided by the manager.
        try:
            starts_at = datetime.fromisoformat(starts_at_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return JsonResponse({"detail": "Invalid startsAt."}, status=400)
        if starts_at.tzinfo is None:
            starts_at = starts_at.replace(tzinfo=UTC)
    else:
        # Auto-find next free slot.
        organizer = meeting.manager.user
        if organizer is None:
            return JsonResponse(
                {"detail": "Manager has no linked user account -- cannot query calendar."},
                status=422,
            )
        from .services.slot_finder import find_available_slot

        slot = find_available_slot(
            manager=meeting.manager,
            person=meeting.person,
            window=window,
            organizer_user=organizer,
            duration_minutes=duration_minutes,
        )
        if slot is None:
            return JsonResponse(
                {
                    "detail": (
                        f"No free slot found in the session window "
                        f"{window.week_start} – {window.week_end}."
                    )
                },
                status=409,
            )
        starts_at = slot.starts_at

    # Cancel the original meeting.
    if meeting.status not in ("cancelled",):
        try:
            cancel_booking(meeting, organizer_user=request.user, audit_user=request.user)
        except Exception:
            pass  # best-effort; proceed to rebook regardless

    # Create the replacement booking.
    tz_name = getattr(settings, "GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
    req = BookingRequest(
        manager=meeting.manager,
        person=meeting.person,
        organizer_user=request.user,
        starts_at=starts_at,
        duration_minutes=duration_minutes,
        title=meeting.title or "Check-in samtale",
        agenda=meeting.agenda or "",
        timezone=tz_name,
    )
    try:
        new_meeting = create_booking(req, audit_user=request.user)
    except BookingError as exc:
        return JsonResponse({"detail": str(exc)}, status=409)
    except GoogleCredentialsUnavailable as exc:
        return JsonResponse({"detail": str(exc), "needs_consent": True}, status=401)
    except GoogleBookingError as exc:
        return JsonResponse({"detail": f"Google rejected the booking: {exc}"}, status=502)

    return JsonResponse(serialize_booking(new_meeting), status=201)


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET"])
def notifications_collection(request: HttpRequest):
    """GET /api/notifications -- return unread (or recent) notifications for the
    requesting manager.

    Query params:
      ``unread_only=1``  (default true) -- return only unread notifications.
      ``limit=<n>``      -- cap at n results (default 50, max 200).
    """
    manager = getattr(request.user, "manager_profile", None)
    if manager is None:
        return JsonResponse({"notifications": []})

    from .models import ManagerNotification

    unread_only = request.GET.get("unread_only", "1") not in ("0", "false", "no")
    try:
        limit = max(1, min(200, int(request.GET.get("limit", "50"))))
    except ValueError:
        limit = 50

    qs = ManagerNotification.objects.filter(manager=manager)
    if unread_only:
        qs = qs.filter(is_read=False)
    qs = qs.order_by("-created_at")[:limit]

    return JsonResponse({"notifications": [n.serialize() for n in qs]})


@login_required
@require_http_methods(["POST"])
def notification_mark_read(request: HttpRequest, notification_id: int):
    """POST /api/notifications/<id>/read -- mark a single notification as read."""
    manager = getattr(request.user, "manager_profile", None)
    if manager is None:
        return JsonResponse({"detail": "Not a manager."}, status=403)

    from .models import ManagerNotification

    notif = ManagerNotification.objects.filter(pk=notification_id, manager=manager).first()
    if not notif:
        return JsonResponse({"detail": "Not found."}, status=404)

    notif.is_read = True
    notif.save(update_fields=["is_read"])
    return JsonResponse(notif.serialize())


@login_required
@require_http_methods(["POST"])
def notifications_mark_all_read(request: HttpRequest):
    """POST /api/notifications/read-all -- mark all unread notifications as read."""
    manager = getattr(request.user, "manager_profile", None)
    if manager is None:
        return JsonResponse({"detail": "Not a manager."}, status=403)

    from .models import ManagerNotification

    updated = ManagerNotification.objects.filter(manager=manager, is_read=False).update(
        is_read=True
    )
    return JsonResponse({"markedRead": updated})


# ---------------------------------------------------------------------------
# Rotation introspection
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
