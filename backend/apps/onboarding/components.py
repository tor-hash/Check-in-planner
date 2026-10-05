"""Code-defined registry of onboarding component types.

A *component type* is a class with three responsibilities:

* ``validate_config(config)`` — validate the per-step config stored on
  ``FlowStep.config``. Called from ``FlowStep.clean`` so both the admin
  form and any programmatic creation (seed command, fixtures, tests) get
  the same checks.
* ``validate_completion(data)`` — validate the payload an external system
  sends when marking a step completed. Called from
  ``StepProgress.full_clean`` and from the PATCH view.
* ``default_config()`` — a minimal config used by the admin "add step"
  shortcut so people don't have to author JSON from scratch.

Validators raise ``django.core.exceptions.ValidationError`` on bad input.
"""
from __future__ import annotations

import re
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


class _Component:
    """Base class. Subclasses must override the three classmethods below."""

    type_id: str = ""
    label: str = ""

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {}

    @classmethod
    def validate_config(cls, config: Any) -> None:
        raise NotImplementedError

    @classmethod
    def validate_completion(cls, data: Any) -> None:
        raise NotImplementedError


def _require_dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must be a JSON object.")
    return value


def _require_str(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string.")
    if not allow_empty and not value.strip():
        raise ValidationError(f"{name} must not be empty.")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{name} must be a boolean.")
    return value


class InfoLinkComponent(_Component):
    type_id = "info_link"
    label = "Info with link"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"body": "", "url": "https://example.com", "requires_read": True}

    @classmethod
    def validate_config(cls, config: Any) -> None:
        cfg = _require_dict(config, "config")
        _require_str(cfg.get("url"), "config.url")
        try:
            URLValidator(schemes=["http", "https"])(cfg["url"])
        except ValidationError as exc:
            raise ValidationError("config.url must be a valid http(s) URL.") from exc
        if "body" in cfg:
            _require_str(cfg["body"], "config.body", allow_empty=True)
        if "requires_read" in cfg:
            _require_bool(cfg["requires_read"], "config.requires_read")

    @classmethod
    def validate_completion(cls, data: Any) -> None:
        _require_dict(data, "completion_data")
        # No required keys — UIs may post {"read_at": "..."} or {} on a
        # simple "I've read it" click. Optional read_at must be a string
        # if present (we don't enforce ISO here; that's the caller's job).
        if "read_at" in data and not isinstance(data["read_at"], str):
            raise ValidationError("completion_data.read_at must be a string.")


class CheckboxComponent(_Component):
    type_id = "checkbox"
    label = "Checkbox"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {"label": "Done?"}

    @classmethod
    def validate_config(cls, config: Any) -> None:
        cfg = _require_dict(config, "config")
        _require_str(cfg.get("label"), "config.label")

    @classmethod
    def validate_completion(cls, data: Any) -> None:
        cfg = _require_dict(data, "completion_data")
        if "checked" not in cfg:
            raise ValidationError("completion_data.checked is required.")
        _require_bool(cfg["checked"], "completion_data.checked")


_FIELD_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
_ALLOWED_FIELD_TYPES = {"text", "longtext", "email", "number", "date", "boolean"}


class FormComponent(_Component):
    type_id = "form"
    label = "Form"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "fields": [
                {"name": "example", "label": "Example", "type": "text", "required": True}
            ]
        }

    @classmethod
    def validate_config(cls, config: Any) -> None:
        cfg = _require_dict(config, "config")
        fields = cfg.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValidationError("config.fields must be a non-empty list.")
        seen: set[str] = set()
        for idx, raw in enumerate(fields):
            field = _require_dict(raw, f"config.fields[{idx}]")
            name = _require_str(field.get("name"), f"config.fields[{idx}].name")
            if not _FIELD_NAME_RE.match(name):
                raise ValidationError(
                    f"config.fields[{idx}].name must match /^[a-zA-Z][a-zA-Z0-9_]*$/."
                )
            if name in seen:
                raise ValidationError(f"config.fields[{idx}].name '{name}' is duplicated.")
            seen.add(name)
            _require_str(field.get("label"), f"config.fields[{idx}].label")
            ftype = _require_str(field.get("type"), f"config.fields[{idx}].type")
            if ftype not in _ALLOWED_FIELD_TYPES:
                raise ValidationError(
                    f"config.fields[{idx}].type must be one of "
                    f"{sorted(_ALLOWED_FIELD_TYPES)}."
                )
            if "required" in field:
                _require_bool(field["required"], f"config.fields[{idx}].required")

    @classmethod
    def validate_completion(cls, data: Any) -> None:
        # Caller must know the form definition; we just sanity-check the
        # outer shape. Per-field type validation against config is done
        # in the service layer where we have both sides.
        cfg = _require_dict(data, "completion_data")
        values = cfg.get("values")
        if not isinstance(values, dict):
            raise ValidationError("completion_data.values must be a JSON object.")


_DURATION_MIN = 5
_DURATION_MAX = 240


class CalendarMeetingComponent(_Component):
    type_id = "calendar_meeting"
    label = "Calendar meeting"

    # Sentinel for config.with_email meaning "whoever attached this flow to
    # the employee" (OnboardingAssignment.assigned_by), resolved at booking
    # time rather than baked into the flow template as a literal address.
    # Lets a single "1:1 with your manager" step work for any employee
    # regardless of who their manager actually is.
    ASSIGNING_MANAGER_SENTINEL = "assigning_manager"

    # Sentinels resolved to the employee's chosen leder/buddy (planner
    # Person.leder / Person.buddy, snapshotted onto the OnboardingAssignment
    # at attach time — see calendar_booking._resolve_organizer). LEDER is
    # also what an *unset/blank* with_email falls back to at booking time —
    # see validate_config below and calendar_booking.py — since every
    # employee is required to have a leder chosen before a flow can be
    # attached, unlike ASSIGNING_MANAGER_SENTINEL which depends on who
    # happened to click "Tildel flow".
    LEDER_SENTINEL = "leder"
    BUDDY_SENTINEL = "buddy"

    ROLE_SENTINELS = (ASSIGNING_MANAGER_SENTINEL, LEDER_SENTINEL, BUDDY_SENTINEL)

    # ``participants`` is the list of people the meeting is with, besides
    # the employee: any mix of the role sentinels above and literal email
    # addresses, e.g. ["leder", "buddy"]. The booking job finds a time when
    # all of them are free and invites them all. It supersedes the older
    # single ``with_email`` key — see ``participant_tokens`` — which is
    # still read for steps saved before ``participants`` existed.
    _MAX_PARTICIPANTS = 10

    @classmethod
    def participant_tokens(cls, config: dict | None) -> list[str]:
        """Participant tokens for a step, oldest config shape included.

        ``participants`` wins when present and non-empty; otherwise falls
        back to ``[with_email]``, and a blank/missing value means the leder.
        Duplicates are removed (case-insensitive), order is preserved.
        """
        cfg = config or {}
        raw = cfg.get("participants")
        if isinstance(raw, list) and any(isinstance(t, str) and t.strip() for t in raw):
            tokens = [t.strip() for t in raw if isinstance(t, str) and t.strip()]
        else:
            tokens = [(cfg.get("with_email") or "").strip() or cls.LEDER_SENTINEL]
        seen: set[str] = set()
        out: list[str] = []
        for t in tokens:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                out.append(t)
        return out

    # Optional scheduling anchor: ``day_offset`` places this step N days
    # after the employee's own start date (start date itself is day 0).
    # ``day_unit`` says how those days are counted:
    #
    # * ``"calendar"`` — plain calendar days. "30 days after start" is
    #   ``day_offset`` 30. If that lands on a weekend or a Danish holiday
    #   it rolls forward to the next working day. Used for the 30/60/90-day
    #   milestones.
    # * ``"business"`` — working days (weekends and holidays don't count).
    #   "Week 1 · Mon" is 0, "Week 1 · Tue" is 1, "Week 2 · Mon" is 5. Start
    #   on a Thursday and 0/1/2/3/4 land on Thu/Fri/Mon/Tue/Wed — "Week 1"
    #   simply means the employee's first five working days. Also the
    #   meaning of a step saved without ``day_unit``.
    #
    # See ``calendar_booking.scheduled_day_for_step`` and ``holidays_dk``.
    # ``time_of_day`` is the preferred 24h clock time to try first on that
    # day (falls back to whatever's next free if taken). All optional — a
    # step with no ``day_offset`` books the first available slot.
    DAY_UNITS = ("calendar", "business")
    _TIME_OF_DAY_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "participants": [cls.LEDER_SENTINEL],
            "duration_minutes": 30,
        }

    @classmethod
    def validate_config(cls, config: Any) -> None:
        cfg = _require_dict(config, "config")
        if "participants" not in cfg and "with_email" not in cfg:
            raise ValidationError("config.participants is required.")
        if "with_email" in cfg:
            with_email = _require_str(
                cfg.get("with_email"), "config.with_email", allow_empty=True
            )
            if with_email and with_email not in cls.ROLE_SENTINELS and "@" not in with_email:
                raise ValidationError(
                    "config.with_email must be an email address, blank (defaults "
                    f"to '{cls.LEDER_SENTINEL}'), or one of {list(cls.ROLE_SENTINELS)}."
                )
        if "participants" in cfg:
            participants = cfg["participants"]
            if not isinstance(participants, list) or not participants:
                raise ValidationError(
                    "config.participants must be a non-empty list of participants."
                )
            if len(participants) > cls._MAX_PARTICIPANTS:
                raise ValidationError(
                    f"config.participants can have at most {cls._MAX_PARTICIPANTS} entries."
                )
            for p in participants:
                if (
                    not isinstance(p, str)
                    or not p.strip()
                    or (p.strip() not in cls.ROLE_SENTINELS and "@" not in p)
                ):
                    raise ValidationError(
                        "Each entry in config.participants must be an email address "
                        f"or one of {list(cls.ROLE_SENTINELS)}."
                    )
        duration = cfg.get("duration_minutes", 30)
        if not isinstance(duration, int) or duration < _DURATION_MIN or duration > _DURATION_MAX:
            raise ValidationError(
                f"config.duration_minutes must be int in [{_DURATION_MIN},{_DURATION_MAX}]."
            )
        if "day_offset" in cfg and cfg["day_offset"] is not None:
            day_offset = cfg["day_offset"]
            if not isinstance(day_offset, int) or isinstance(day_offset, bool) or day_offset < 0:
                raise ValidationError(
                    "config.day_offset must be a non-negative integer (days "
                    "after the employee's start date), or omitted/null."
                )
        if "day_unit" in cfg and cfg["day_unit"] is not None:
            if cfg["day_unit"] not in cls.DAY_UNITS:
                raise ValidationError(
                    f"config.day_unit must be one of {list(cls.DAY_UNITS)}, or omitted."
                )
        if "time_of_day" in cfg and cfg["time_of_day"]:
            time_of_day = _require_str(cfg["time_of_day"], "config.time_of_day", allow_empty=True)
            if time_of_day and not cls._TIME_OF_DAY_RE.match(time_of_day):
                raise ValidationError(
                    "config.time_of_day must be 24h 'HH:MM' (e.g. '09:00'), or omitted/blank."
                )

    @classmethod
    def validate_completion(cls, data: Any) -> None:
        cfg = _require_dict(data, "completion_data")
        scheduled_at = cfg.get("scheduled_at")
        if scheduled_at is None or not isinstance(scheduled_at, str) or not scheduled_at.strip():
            raise ValidationError("completion_data.scheduled_at (ISO datetime) is required.")
        for opt in ("google_event_id", "html_link"):
            if opt in cfg and not isinstance(cfg[opt], str):
                raise ValidationError(f"completion_data.{opt} must be a string.")


COMPONENTS: dict[str, type[_Component]] = {
    cls.type_id: cls
    for cls in (
        InfoLinkComponent,
        CheckboxComponent,
        FormComponent,
        CalendarMeetingComponent,
    )
}

COMPONENT_CHOICES = [(cls.type_id, cls.label) for cls in COMPONENTS.values()]


def get_component(type_id: str) -> type[_Component]:
    try:
        return COMPONENTS[type_id]
    except KeyError as exc:
        raise ValidationError(
            f"Unknown component_type '{type_id}'. "
            f"Known types: {sorted(COMPONENTS)}."
        ) from exc
