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
    if not isinstance(payload, dict):
        return None, _err("Body must be a JSON object.")

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

    flow_slug = payload.get("flow_slug")
    if flow_slug is not None:
        if not isinstance(flow_slug, str) or not flow_slug.strip():
            return None, _err("flow_slug must be a non-empty string when provided.")
        flow_slug = flow_slug.strip()

    return (
        {
            "erp_employee_id": erp_id,
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "position": position,
            "department": department,
            "start_date": start_date,
            "flow_slug": flow_slug,
        },
        None,
    )


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
