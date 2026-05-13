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

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "with_email": "manager@blackcapitaltechnology.com",
            "duration_minutes": 30,
            "suggested_window": "first week",
        }

    @classmethod
    def validate_config(cls, config: Any) -> None:
        cfg = _require_dict(config, "config")
        with_email = _require_str(cfg.get("with_email"), "config.with_email")
        if "@" not in with_email:
            raise ValidationError("config.with_email must be an email address.")
        duration = cfg.get("duration_minutes", 30)
        if not isinstance(duration, int) or duration < _DURATION_MIN or duration > _DURATION_MAX:
            raise ValidationError(
                f"config.duration_minutes must be int in [{_DURATION_MIN},{_DURATION_MAX}]."
            )
        if "suggested_window" in cfg:
            _require_str(cfg["suggested_window"], "config.suggested_window", allow_empty=True)

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
