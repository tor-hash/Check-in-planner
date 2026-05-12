from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

REQUIRED_TOP_LEVEL_KEYS = {
    "people",
    "mgrs",
    "teams",
    "startDate",
    "customDates",
    "workHours",
    "projects",
    "journal",
    "fnTags",
}

VALID_TEAMS = {"team-1", "team-2", "team-3", "pool"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COLOR_PATTERN = re.compile(r"^#?[0-9A-Fa-f]{3,8}$")
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def _is_string(value: Any, max_len: int = 1024) -> bool:
    return isinstance(value, str) and 0 <= len(value) <= max_len


def _is_id(value: Any) -> bool:
    return isinstance(value, str) and bool(ID_PATTERN.match(value))


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        # tolerate trailing Z
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------


def validate_person_payload(payload: Any, *, require_id: bool = True) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(False, ["Person payload must be a JSON object."])
    if require_id and not _is_id(payload.get("id")):
        errors.append("Person.id is required and must match [A-Za-z0-9._-]{1,64}.")
    name = payload.get("name", "")
    if not _is_string(name, 255) or not name.strip():
        errors.append("Person.name is required (1-255 chars).")
    for key in ("mbti", "title", "org", "fn", "loc", "phone", "linkedin", "dessert"):
        if key in payload and not _is_string(payload.get(key) or "", 255):
            errors.append(f"Person.{key} must be a string ≤ 255 chars.")
    email = payload.get("email", "")
    if email and (not _is_string(email, 254) or not EMAIL_PATTERN.match(email)):
        errors.append("Person.email must look like an email address.")
    projects = payload.get("projects", [])
    if not isinstance(projects, list) or not all(isinstance(p, str) for p in projects):
        errors.append("Person.projects must be a list of project names (strings).")
    return ValidationResult(not errors, errors)


# ---------------------------------------------------------------------------
# Project / FunctionTag
# ---------------------------------------------------------------------------


def validate_project_payload(payload: Any) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(False, ["Project payload must be a JSON object."])
    name = payload.get("name", "")
    if not _is_string(name, 128) or not name.strip():
        errors.append("Project.name is required (1-128 chars).")
    if "description" in payload and not _is_string(payload.get("description") or "", 4096):
        errors.append("Project.description must be a string ≤ 4096 chars.")
    color = payload.get("color", "")
    if color and not COLOR_PATTERN.match(color):
        errors.append("Project.color must be a hex color like #6ea8fe.")
    return ValidationResult(not errors, errors)


def validate_function_tag_payload(payload: Any) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(False, ["FunctionTag payload must be a JSON object."])
    display_name = payload.get("displayName", "")
    if not _is_string(display_name, 128) or not display_name.strip():
        errors.append("FunctionTag.displayName is required (1-128 chars).")
    label = payload.get("label", "")
    if label and not _is_string(label, 16):
        errors.append("FunctionTag.label must be ≤ 16 chars.")
    color = payload.get("color", "")
    if color and not COLOR_PATTERN.match(color):
        errors.append("FunctionTag.color must be a hex color.")
    return ValidationResult(not errors, errors)


# ---------------------------------------------------------------------------
# Journal entry
# ---------------------------------------------------------------------------


def validate_journal_entry_payload(payload: Any, *, require_id: bool = True) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(False, ["JournalEntry payload must be a JSON object."])
    if require_id and not _is_id(payload.get("id")):
        errors.append("JournalEntry.id is required and must match [A-Za-z0-9._-]{1,64}.")
    if not _is_id(payload.get("personId")):
        errors.append("JournalEntry.personId is required.")
    if "managerId" in payload and payload.get("managerId") not in (None, ""):
        if not _is_id(payload.get("managerId")):
            errors.append("JournalEntry.managerId must match [A-Za-z0-9._-]{1,64} when provided.")
    if "date" in payload and payload["date"] is not None and not _is_iso_date(payload.get("date")):
        errors.append("JournalEntry.date must be ISO-8601 (YYYY-MM-DD).")
    for key in ("trivsel", "faglig", "personlig", "udfordringer", "maal", "noter", "opfolgning", "obs"):
        if key in payload and not _is_string(payload.get(key) or "", 16384):
            errors.append(f"JournalEntry.{key} must be a string ≤ 16384 chars.")
    files = payload.get("files", [])
    if not isinstance(files, list):
        errors.append("JournalEntry.files must be a list.")
    return ValidationResult(not errors, errors)


# ---------------------------------------------------------------------------
# Booking + freebusy
# ---------------------------------------------------------------------------


def validate_booking_payload(payload: Any) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(False, ["Booking payload must be a JSON object."])
    if not _is_id(payload.get("personId")):
        errors.append("Booking.personId is required.")
    if not _is_id(payload.get("managerId")):
        errors.append("Booking.managerId is required.")
    if not _is_iso_datetime(payload.get("startsAt")):
        errors.append("Booking.startsAt must be ISO-8601 datetime.")
    duration = payload.get("durationMinutes", 30)
    if not isinstance(duration, int) or duration < 5 or duration > 240:
        errors.append("Booking.durationMinutes must be an integer between 5 and 240.")
    title = payload.get("title", "")
    if title and not _is_string(title, 255):
        errors.append("Booking.title must be a string ≤ 255 chars.")
    agenda = payload.get("agenda", "")
    if agenda and not _is_string(agenda, 8192):
        errors.append("Booking.agenda must be a string ≤ 8192 chars.")
    return ValidationResult(not errors, errors)


def validate_freebusy_query(params: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    if not _is_iso_datetime(params.get("from") or ""):
        errors.append("freebusy.from must be ISO-8601 datetime.")
    if not _is_iso_datetime(params.get("to") or ""):
        errors.append("freebusy.to must be ISO-8601 datetime.")
    team = params.get("team")
    if team and team not in VALID_TEAMS and not _is_id(team):
        errors.append("freebusy.team must be one of team-1/2/3/pool or a person id list.")
    return ValidationResult(not errors, errors)


# ---------------------------------------------------------------------------
# Aggregate state (legacy contract)
# ---------------------------------------------------------------------------


def validate_state_payload(payload: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ValidationResult(False, ["State payload must be a JSON object."])
    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(payload.keys()))
    if missing:
        errors.append(f"Missing top-level keys: {', '.join(missing)}")

    if not isinstance(payload.get("people", []), list):
        errors.append("people must be a list")
    else:
        for idx, person in enumerate(payload.get("people", [])):
            res = validate_person_payload(person, require_id=True)
            errors.extend([f"people[{idx}]: {e}" for e in res.errors])

    if not isinstance(payload.get("mgrs", []), list):
        errors.append("mgrs must be a list")
    else:
        for idx, mgr in enumerate(payload.get("mgrs", [])):
            if not _is_id(mgr):
                errors.append(f"mgrs[{idx}] must be a valid id.")

    teams = payload.get("teams", {})
    if not isinstance(teams, dict):
        errors.append("teams must be an object")
    else:
        for team_name, members in teams.items():
            if team_name not in VALID_TEAMS:
                errors.append(f"teams.{team_name} is not a valid team key.")
            if not isinstance(members, list):
                errors.append(f"teams.{team_name} must be a list of person ids.")

    if "startDate" in payload and payload["startDate"] is not None and not _is_iso_date(payload["startDate"]):
        errors.append("startDate must be ISO-8601 (YYYY-MM-DD).")

    work_hours = payload.get("workHours", {})
    if work_hours and isinstance(work_hours, dict):
        for key in ("start", "end"):
            if key in work_hours and work_hours[key] and not TIME_PATTERN.match(str(work_hours[key])):
                errors.append(f"workHours.{key} must be HH:MM (24h).")

    if not isinstance(payload.get("journal", {}), dict):
        errors.append("journal must be an object")
    else:
        for person_id, entries in payload.get("journal", {}).items():
            if not _is_id(person_id):
                errors.append(f"journal[{person_id}] key must be a valid id.")
            if not isinstance(entries, list):
                errors.append(f"journal[{person_id}] must be a list of entries.")
                continue
            for idx, entry in enumerate(entries):
                merged = {**entry, "personId": person_id} if isinstance(entry, dict) else entry
                res = validate_journal_entry_payload(merged, require_id=True)
                errors.extend([f"journal[{person_id}][{idx}]: {e}" for e in res.errors])

    projects = payload.get("projects", [])
    if not isinstance(projects, list):
        errors.append("projects must be a list")
    else:
        for idx, project in enumerate(projects):
            res = validate_project_payload(project)
            errors.extend([f"projects[{idx}]: {e}" for e in res.errors])

    fn_tags = payload.get("fnTags", [])
    if not isinstance(fn_tags, list):
        errors.append("fnTags must be a list")
    else:
        for idx, tag in enumerate(fn_tags):
            res = validate_function_tag_payload(tag)
            errors.extend([f"fnTags[{idx}]: {e}" for e in res.errors])

    custom_dates = payload.get("customDates", {})
    if not isinstance(custom_dates, dict):
        errors.append("customDates must be an object")

    return ValidationResult(not errors, errors)
