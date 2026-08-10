"""Payload validators for the onboarding REST API.

Each ``validate_*`` function returns a tuple ``(cleaned, error)``. On
success ``error`` is ``None`` and ``cleaned`` is a normalised dict ready
for the service layer. On failure ``cleaned`` is ``None`` and ``error``
is a ``JsonResponse`` ready to be returned by the view.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from django.http import JsonResponse

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ERP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_NAME_MAX = 128
_TITLE_MAX = 200


def _err(detail: str, **extra) -> JsonResponse:
    return JsonResponse({"detail": detail, **extra}, status=400)


def _opt_str(value: Any, name: str, *, max_length: int) -> tuple[str, JsonResponse | None]:
    if value is None or value == "":
        return "", None
    if not isinstance(value, str):
        return "", _err(f"{name} must be a string.")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        return "", _err(f"{name} must be at most {max_length} chars.")
    return cleaned, None


def validate_create_employee(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Validate an employee-creation payload.

    ``flow_slug`` is intentionally not accepted here — creating an employee
    never attaches a flow. Attaching one is a separate, deliberate action
    (the manage API's assign-flow endpoint) and is the only place the
    welcome email / calendar booking / Slack invite automation runs.
    """
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    if "flow_slug" in payload:
        return None, _err(
            "flow_slug is not accepted when creating an employee. Create the "
            "employee first, then attach a flow via the assign-flow action."
        )

    erp_id = payload.get("erp_employee_id")
    if not isinstance(erp_id, str) or not _ERP_ID_RE.match(erp_id.strip()):
        return None, _err("erp_employee_id is required and must match /^[A-Za-z0-9_-]{1,64}$/.")
    erp_id = erp_id.strip()

    email = payload.get("email")
    if not isinstance(email, str) or not _EMAIL_RE.match(email.strip().lower()):
        return None, _err("email is required and must be a valid email address.")
    email = email.strip().lower()

    first_name, err = _opt_str(payload.get("first_name"), "first_name", max_length=_NAME_MAX)
    if err is not None:
        return None, err
    last_name, err = _opt_str(payload.get("last_name"), "last_name", max_length=_NAME_MAX)
    if err is not None:
        return None, err
    position, err = _opt_str(payload.get("position"), "position", max_length=_NAME_MAX)
    if err is not None:
        return None, err
    department, err = _opt_str(payload.get("department"), "department", max_length=_NAME_MAX)
    if err is not None:
        return None, err

    start_date_raw = payload.get("start_date")
    start_date: date | None = None
    if start_date_raw not in (None, ""):
        if not isinstance(start_date_raw, str):
            return None, _err("start_date must be an ISO date string (YYYY-MM-DD).")
        try:
            start_date = date.fromisoformat(start_date_raw)
        except ValueError:
            return None, _err("start_date must be an ISO date string (YYYY-MM-DD).")

    return (
        {
            "erp_employee_id": erp_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "department": department,
            "start_date": start_date,
        },
        None,
    )


def validate_provision_employee(
    payload: Any,
) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Alias of ``validate_create_employee`` (kept for call-site clarity).

    ``/provision`` ensures the default flow *template* exists but — like
    plain employee creation — no longer attaches it automatically.
    """
    return validate_create_employee(payload)


def validate_email_lookup(value: Any) -> tuple[str | None, JsonResponse | None]:
    if not isinstance(value, str) or not value.strip():
        return None, _err("email is required.")
    email = value.strip().lower()
    if not _EMAIL_RE.match(email):
        return None, _err("email must be a valid email address.")
    return email, None


def validate_update_employee(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Validate an employee-update (PATCH) payload.

    ``flow_slug`` is not accepted — changing an employee's flow goes
    through the assign-flow / remove-flow endpoints, never a plain field
    update, so that attaching a (new) flow always runs through the same
    deliberate-action path (pre-flight checks + automation).
    """
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    if "flow_slug" in payload:
        return None, _err(
            "flow_slug cannot be changed via PATCH. Use the assign-flow "
            "endpoint to attach a different flow."
        )

    cleaned: dict[str, Any] = {}

    if "email" in payload:
        email = payload.get("email")
        if not isinstance(email, str) or not _EMAIL_RE.match(email.strip().lower()):
            return None, _err("email must be a valid email address.")
        cleaned["email"] = email.strip().lower()

    for field in ("first_name", "last_name", "position", "department"):
        if field in payload:
            val, err = _opt_str(payload.get(field), field, max_length=_NAME_MAX)
            if err is not None:
                return None, err
            cleaned[field] = val

    if "start_date" in payload:
        raw = payload.get("start_date")
        if raw in (None, ""):
            cleaned["start_date"] = None
        else:
            if not isinstance(raw, str):
                return None, _err("start_date must be an ISO date string (YYYY-MM-DD).")
            try:
                cleaned["start_date"] = date.fromisoformat(raw)
            except ValueError:
                return None, _err("start_date must be an ISO date string (YYYY-MM-DD).")

    if not cleaned:
        return None, _err("No fields to update.")

    return cleaned, None


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COMPONENT_TYPES = {"info_link", "checkbox", "form", "calendar_meeting"}


def _require_bool(value: Any, name: str) -> tuple[bool, JsonResponse | None]:
    if not isinstance(value, bool):
        return False, _err(f"{name} must be a boolean.")
    return value, None


def validate_flow_payload(
    payload: Any, *, require_slug: bool
) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    cleaned: dict[str, Any] = {}

    if require_slug:
        slug = payload.get("slug")
        if not isinstance(slug, str) or not _SLUG_RE.match(slug.strip()):
            return None, _err(
                "slug is required and must be lowercase letters, numbers, and hyphens."
            )
        cleaned["slug"] = slug.strip()
    else:
        if "slug" in payload:
            return None, _err("slug cannot be changed on update.")

    if "name" in payload or require_slug:
        name, err = _opt_str(payload.get("name"), "name", max_length=_NAME_MAX)
        if err is not None:
            return None, err
        if require_slug and not name:
            return None, _err("name is required.")
        if name or require_slug:
            cleaned["name"] = name

    if "description" in payload:
        description, err = _opt_str(payload.get("description"), "description", max_length=2000)
        if err is not None:
            return None, err
        cleaned["description"] = description

    if "is_default" in payload:
        is_default, err = _require_bool(payload.get("is_default"), "is_default")
        if err is not None:
            return None, err
        cleaned["is_default"] = is_default

    if "is_active" in payload:
        is_active, err = _require_bool(payload.get("is_active"), "is_active")
        if err is not None:
            return None, err
        cleaned["is_active"] = is_active

    return cleaned, None


def validate_step_payload(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    component_type = payload.get("component_type")
    if not isinstance(component_type, str) or component_type not in _COMPONENT_TYPES:
        return None, _err(
            f"component_type must be one of {sorted(_COMPONENT_TYPES)}."
        )

    title, err = _opt_str(payload.get("title"), "title", max_length=_TITLE_MAX)
    if err is not None:
        return None, err
    if not title:
        return None, _err("title is required.")

    description, err = _opt_str(payload.get("description"), "description", max_length=2000)
    if err is not None:
        return None, err

    order_raw = payload.get("order")
    if order_raw is None:
        return None, _err("order is required.")
    try:
        order = int(order_raw)
    except (TypeError, ValueError):
        return None, _err("order must be a positive integer.")
    if order < 1:
        return None, _err("order must be at least 1.")

    is_required = payload.get("is_required", True)
    is_required_bool, err = _require_bool(is_required, "is_required")
    if err is not None:
        return None, err

    config = payload.get("config")
    if not isinstance(config, dict):
        return None, _err("config must be a JSON object.")

    return (
        {
            "component_type": component_type,
            "title": title,
            "description": description,
            "order": order,
            "is_required": is_required_bool,
            "config": config,
        },
        None,
    )


def validate_reorder_payload(payload: Any) -> tuple[list[int] | None, JsonResponse | None]:
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")
    step_ids = payload.get("step_ids")
    if not isinstance(step_ids, list) or not step_ids:
        return None, _err("step_ids must be a non-empty list of integers.")
    cleaned: list[int] = []
    for raw in step_ids:
        try:
            cleaned.append(int(raw))
        except (TypeError, ValueError):
            return None, _err("step_ids must contain integers only.")
    return cleaned, None


_PROGRESS_STATUSES = {"pending", "completed", "skipped"}


def validate_step_progress_patch(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    status = payload.get("status")
    if not isinstance(status, str) or status not in _PROGRESS_STATUSES:
        return None, _err(f"status must be one of {sorted(_PROGRESS_STATUSES)}.")

    completion_data = payload.get("completion_data", {})
    if not isinstance(completion_data, dict):
        return None, _err("completion_data must be a JSON object.")

    completed_by, err = _opt_str(payload.get("completed_by", ""), "completed_by", max_length=_NAME_MAX)
    if err is not None:
        return None, err

    return (
        {
            "status": status,
            "completion_data": completion_data,
            "completed_by": completed_by,
        },
        None,
    )


_SUBJECT_MAX = 255
_HTML_BODY_MAX = 100_000


def validate_welcome_email_template(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Validate a welcome-email-template save payload (PUT .../welcome-email).

    Template *syntax* (bad ``{% %}``/``{{ }}``) is not checked here — that
    requires actually rendering it, which the view does separately via
    ``welcome_email.validate_template_syntax`` so both failure modes end up
    as the same 400 shape.
    """
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    subject = payload.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        return None, _err("subject is required.")
    subject = subject.strip()
    if len(subject) > _SUBJECT_MAX:
        return None, _err(f"subject must be at most {_SUBJECT_MAX} chars.")

    html_body = payload.get("html_body")
    if not isinstance(html_body, str) or not html_body.strip():
        return None, _err("html_body is required.")
    if len(html_body) > _HTML_BODY_MAX:
        return None, _err(f"html_body must be at most {_HTML_BODY_MAX} chars.")

    is_default_fallback = payload.get("is_default_fallback", False)
    is_default_fallback_bool, err = _require_bool(is_default_fallback, "is_default_fallback")
    if err is not None:
        return None, err

    return (
        {
            "subject": subject,
            "html_body": html_body,
            "is_default_fallback": is_default_fallback_bool,
        },
        None,
    )


def validate_welcome_email_preview(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Validate a preview-render request.

    Every field is optional: an empty body previews the flow's currently
    *saved* effective template with placeholder sample data. ``subject``/
    ``html_body`` (both required together) preview unsaved draft content
    instead — used by the "Velkomstmail" editor so the preview reflects
    what's in the textarea, not what's on disk. ``erp_id`` renders with a
    real employee's data instead of the placeholder sample.
    """
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    has_subject = "subject" in payload and payload.get("subject") not in (None, "")
    has_html = "html_body" in payload and payload.get("html_body") not in (None, "")
    if has_subject != has_html:
        return None, _err("subject and html_body must be provided together, or not at all.")

    cleaned: dict[str, Any] = {}
    if has_subject:
        subject, err = _opt_str(payload.get("subject"), "subject", max_length=_SUBJECT_MAX)
        if err is not None:
            return None, err
        html_body = payload.get("html_body")
        if not isinstance(html_body, str):
            return None, _err("html_body must be a string.")
        if len(html_body) > _HTML_BODY_MAX:
            return None, _err(f"html_body must be at most {_HTML_BODY_MAX} chars.")
        cleaned["subject"] = subject
        cleaned["html_body"] = html_body

    erp_id, err = _opt_str(payload.get("erp_id"), "erp_id", max_length=64)
    if err is not None:
        return None, err
    cleaned["erp_id"] = erp_id

    buddy_name, err = _opt_str(payload.get("buddy_name"), "buddy_name", max_length=_NAME_MAX)
    if err is not None:
        return None, err
    cleaned["buddy_name"] = buddy_name

    buddy_email_raw = payload.get("buddy_email")
    if buddy_email_raw:
        if not isinstance(buddy_email_raw, str) or not _EMAIL_RE.match(buddy_email_raw.strip().lower()):
            return None, _err("buddy_email must be a valid email address.")
        cleaned["buddy_email"] = buddy_email_raw.strip()
    else:
        cleaned["buddy_email"] = ""

    return cleaned, None


def validate_buddy_fields(payload: Any) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Validate the optional buddy_name/buddy_email on an assign-flow payload."""
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

    buddy_name, err = _opt_str(payload.get("buddy_name"), "buddy_name", max_length=_NAME_MAX)
    if err is not None:
        return None, err

    buddy_email_raw = payload.get("buddy_email")
    if buddy_email_raw:
        if not isinstance(buddy_email_raw, str) or not _EMAIL_RE.match(buddy_email_raw.strip().lower()):
            return None, _err("buddy_email must be a valid email address.")
        buddy_email = buddy_email_raw.strip()
    else:
        buddy_email = ""

    return {"buddy_name": buddy_name, "buddy_email": buddy_email}, None
