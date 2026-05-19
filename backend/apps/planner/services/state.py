from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from apps.planner.models import (
    CheckInMeeting,
    CustomDate,
    FunctionTag,
    JournalEntry,
    ManagerProfile,
    Person,
    PlannerConfig,
    PlannerStateVersion,
    Project,
    TeamMembership,
)

DEFAULT_WORK_HOURS = {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True}


# ---------------------------------------------------------------------------
# Roles + auth helpers
# ---------------------------------------------------------------------------


def ensure_default_roles() -> None:
    Group.objects.get_or_create(name="manager")
    Group.objects.get_or_create(name="admin")


def is_manager_or_admin(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=["manager", "admin"]).exists()


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _to_date(value: str | None) -> date:
    if not value:
        return timezone.now().date()
    return date.fromisoformat(value)


def _deleted_at(value: Any):
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except Exception:
        return None


def _project_lookup() -> dict[str, Project]:
    return {item.name: item for item in Project.objects.all()}


def _bump_state_version() -> None:
    version = PlannerStateVersion.singleton()
    version.version += 1
    version.save(update_fields=["version", "updated_at"])


# ---------------------------------------------------------------------------
# Read: aggregate state payload (legacy contract)
# ---------------------------------------------------------------------------


def serialize_person(person: Person) -> dict[str, Any]:
    return {
        "id": person.legacy_id,
        "name": person.name,
        "mbti": person.mbti,
        "title": person.title,
        "org": person.org,
        "fn": person.function_name or (person.function.display_name if person.function else ""),
        "loc": person.loc,
        "email": person.email,
        "phone": person.phone,
        "linkedin": person.linkedin,
        "dessert": person.dessert,
        "projects": [project.name for project in person.projects.all()],
    }


def serialize_journal_entry(entry: JournalEntry) -> dict[str, Any]:
    return {
        "id": entry.entry_id,
        "personId": entry.person.legacy_id if entry.person_id else "",
        "managerId": entry.manager.legacy_id if entry.manager else "",
        "date": entry.date.isoformat(),
        "trivsel": entry.trivsel,
        "faglig": entry.faglig,
        "personlig": entry.personlig,
        "udfordringer": entry.udfordringer,
        "maal": entry.maal,
        "noter": entry.noter,
        "opfolgning": entry.opfolgning,
        "obs": entry.obs,
        "files": entry.files or [],
        "createdAt": int(entry.created_at.timestamp() * 1000),
        "updatedAt": int(entry.updated_at.timestamp() * 1000),
        "deletedAt": int(entry.deleted_at.timestamp() * 1000) if entry.deleted_at else None,
    }


def build_state_payload() -> dict[str, Any]:
    ensure_default_roles()
    cfg = PlannerConfig.singleton()
    state_version = PlannerStateVersion.singleton()

    people = [serialize_person(p) for p in Person.objects.prefetch_related("projects", "function").all()]

    mgrs = list(ManagerProfile.objects.order_by("id").values_list("legacy_id", flat=True))

    teams: dict[str, list[str]] = {"team-1": [], "team-2": [], "team-3": [], "pool": []}
    for membership in TeamMembership.objects.select_related("person").order_by("team", "sort_order", "id"):
        teams.setdefault(membership.team, []).append(membership.person.legacy_id)

    projects = [
        {"name": project.name, "description": project.description, "color": project.color}
        for project in Project.objects.order_by("name")
    ]
    fn_tags = [
        {"label": item.label, "displayName": item.display_name, "color": item.color}
        for item in FunctionTag.objects.order_by("display_name")
    ]
    custom_dates = {row.key: row.value for row in CustomDate.objects.order_by("key")}

    journal: dict[str, list[dict[str, Any]]] = {}
    for row in JournalEntry.objects.select_related("person", "manager").order_by("-date", "-updated_at"):
        journal.setdefault(row.person.legacy_id, []).append(serialize_journal_entry(row))

    from .bookings import serialize_booking

    bookings = [
        serialize_booking(row)
        for row in CheckInMeeting.objects.select_related("manager", "person")
        .filter(status="scheduled")
        .order_by("starts_at")[:200]
    ]

    return {
        "people": people,
        "mgrs": mgrs,
        "teams": teams,
        "startDate": cfg.start_date.isoformat(),
        "customDates": custom_dates,
        "workHours": cfg.work_hours or DEFAULT_WORK_HOURS,
        "oauth": {"lastFetch": None, "busy": {}, "autoRefresh": False, "lastErrors": []},
        "viewedMgrFilter": cfg.viewed_mgr_filter or "all",
        "weekOffset": cfg.week_offset or 0,
        "weeksPerSession": cfg.weeks_per_session or 2,
        "projects": projects,
        "journal": journal,
        "fnTags": fn_tags,
        "bookings": bookings,
        "_meta": {"version": state_version.version, "updatedAt": state_version.updated_at.isoformat()},
    }


# ---------------------------------------------------------------------------
# Per-entity upsert helpers (the building blocks of non-destructive sync)
# ---------------------------------------------------------------------------


def upsert_function_tag(payload: dict[str, Any], user) -> FunctionTag:
    display_name = (payload.get("displayName") or "").strip()[:128]
    if not display_name:
        raise ValueError("FunctionTag requires displayName.")
    defaults = {
        "label": (payload.get("label") or "")[:16],
        "color": payload.get("color") or "#6ea8fe",
        "updated_by": user,
    }
    tag, created = FunctionTag.objects.get_or_create(
        display_name=display_name, defaults={**defaults, "created_by": user}
    )
    if not created:
        for key, value in defaults.items():
            setattr(tag, key, value)
        tag.save()
    return tag


def upsert_project(payload: dict[str, Any], user) -> Project:
    name = (payload.get("name") or "").strip()[:128]
    if not name:
        raise ValueError("Project requires name.")
    defaults = {
        "description": payload.get("description") or "",
        "color": payload.get("color") or "",
        "updated_by": user,
    }
    project, created = Project.objects.get_or_create(
        name=name, defaults={**defaults, "created_by": user}
    )
    if not created:
        for key, value in defaults.items():
            setattr(project, key, value)
        project.save()
    return project


def upsert_person(payload: dict[str, Any], user) -> Person:
    legacy_id = (payload.get("id") or "").strip()[:32]
    if not legacy_id:
        raise ValueError("Person requires id.")

    fn_name = payload.get("fn") or ""
    fn_tag = None
    if fn_name:
        fn_tag = FunctionTag.objects.filter(display_name=fn_name).first()

    defaults = {
        "name": (payload.get("name") or "")[:255],
        "mbti": (payload.get("mbti") or "")[:32],
        "title": (payload.get("title") or "")[:255],
        "org": (payload.get("org") or "BCT")[:255],
        "function": fn_tag,
        "function_name": fn_name[:255],
        "loc": (payload.get("loc") or "")[:255],
        "email": (payload.get("email") or "")[:254],
        "phone": (payload.get("phone") or "")[:64],
        "linkedin": (payload.get("linkedin") or "")[:255],
        "dessert": (payload.get("dessert") or "")[:255],
        "updated_by": user,
    }
    person, created = Person.objects.get_or_create(
        legacy_id=legacy_id, defaults={**defaults, "created_by": user}
    )
    if not created:
        for key, value in defaults.items():
            setattr(person, key, value)
        person.save()

    # Sync the M2M project list to exactly the names provided. Skip projects
    # that don't exist yet — caller is responsible for creating them first.
    project_names = payload.get("projects") or []
    projects_qs = Project.objects.filter(name__in=project_names)
    person.projects.set(projects_qs)
    return person


def delete_person(legacy_id: str) -> bool:
    deleted, _ = Person.objects.filter(legacy_id=legacy_id).delete()
    return deleted > 0


def upsert_manager(legacy_id: str, user) -> ManagerProfile:
    legacy_id = (legacy_id or "").strip()[:32]
    if not legacy_id:
        raise ValueError("Manager requires legacy_id.")
    person = Person.objects.filter(legacy_id=legacy_id).first()
    manager, created = ManagerProfile.objects.get_or_create(
        legacy_id=legacy_id, defaults={"person": person, "created_by": user, "updated_by": user}
    )
    if not created:
        if person and manager.person_id != person.id:
            manager.person = person
        manager.updated_by = user
        manager.save()
    return manager


def replace_team_membership(team: str, person_ids: list[str], user) -> None:
    """Replace the membership list for a single team in deterministic order.

    Removes only the rows for *this* team — other teams are untouched.
    """
    TeamMembership.objects.filter(team=team).delete()
    for idx, pid in enumerate(person_ids):
        person = Person.objects.filter(legacy_id=pid).first()
        if not person:
            continue
        TeamMembership.objects.create(
            team=team,
            person=person,
            sort_order=idx,
            created_by=user,
            updated_by=user,
        )


def upsert_journal_entry(payload: dict[str, Any], user) -> JournalEntry:
    entry_id = (payload.get("id") or "").strip()[:64]
    if not entry_id:
        raise ValueError("JournalEntry requires id.")
    person_id = (payload.get("personId") or "").strip()
    if not person_id:
        raise ValueError("JournalEntry requires personId.")
    person = Person.objects.filter(legacy_id=person_id).first()
    if not person:
        raise ValueError(f"Unknown personId '{person_id}'.")

    manager = None
    manager_id = (payload.get("managerId") or "").strip()
    if manager_id:
        manager = ManagerProfile.objects.filter(legacy_id=manager_id).first()

    defaults = {
        "person": person,
        "manager": manager,
        "date": _to_date(payload.get("date")),
        "trivsel": payload.get("trivsel") or "",
        "faglig": payload.get("faglig") or "",
        "personlig": payload.get("personlig") or "",
        "udfordringer": payload.get("udfordringer") or "",
        "maal": payload.get("maal") or "",
        "noter": payload.get("noter") or "",
        "opfolgning": payload.get("opfolgning") or "",
        "obs": payload.get("obs") or "",
        "files": payload.get("files") or [],
        "deleted_at": _deleted_at(payload.get("deletedAt")),
        "updated_by": user,
    }
    entry, created = JournalEntry.objects.get_or_create(
        entry_id=entry_id, defaults={**defaults, "created_by": user}
    )
    if not created:
        for key, value in defaults.items():
            setattr(entry, key, value)
        entry.save()
    return entry


def soft_delete_journal_entry(entry_id: str) -> bool:
    entry = JournalEntry.objects.filter(entry_id=entry_id).first()
    if not entry:
        return False
    entry.deleted_at = timezone.now()
    entry.save(update_fields=["deleted_at", "updated_at"])
    return True


def update_planner_config(payload: dict[str, Any], user) -> PlannerConfig:
    cfg = PlannerConfig.singleton()
    if "startDate" in payload:
        cfg.start_date = _to_date(payload.get("startDate"))
    if "workHours" in payload:
        cfg.work_hours = payload.get("workHours") or DEFAULT_WORK_HOURS
    if "viewedMgrFilter" in payload:
        cfg.viewed_mgr_filter = payload.get("viewedMgrFilter") or "all"
    if "weekOffset" in payload:
        try:
            cfg.week_offset = int(payload.get("weekOffset") or 0)
        except (TypeError, ValueError):
            cfg.week_offset = 0
    if "weeksPerSession" in payload:
        try:
            n = int(payload.get("weeksPerSession") or 2)
            cfg.weeks_per_session = max(1, min(12, n))
        except (TypeError, ValueError):
            cfg.weeks_per_session = 2
    cfg.updated_by = user
    if not cfg.created_by:
        cfg.created_by = user
    cfg.save()
    return cfg


def replace_function_tags(rows: list[dict[str, Any]], user) -> None:
    incoming_names = {
        (row.get("displayName") or "").strip()[:128]
        for row in rows or []
    }
    incoming_names.discard("")
    FunctionTag.objects.exclude(display_name__in=incoming_names).delete()
    for row in rows or []:
        upsert_function_tag(row, user)


def replace_custom_dates(values: dict[str, str], user) -> None:
    incoming_keys = set(values.keys())
    CustomDate.objects.exclude(key__in=incoming_keys).delete()
    for key, value in values.items():
        CustomDate.objects.update_or_create(
            key=str(key)[:255],
            defaults={"value": str(value)[:64], "updated_by": user},
        )


# ---------------------------------------------------------------------------
# Aggregate persist (legacy PUT /api/state/update) — now non-destructive.
# ---------------------------------------------------------------------------


@transaction.atomic
def persist_state(payload: dict[str, Any], user) -> dict[str, Any]:
    """Apply a full state snapshot using upsert + delete-missing semantics.

    This preserves IDs (and therefore FK references like JournalEntry.person)
    across saves. Entities present in the payload are upserted; entities
    missing from the payload are removed.

    Kept for backward compatibility with the legacy single-PUT contract.
    Per-resource endpoints (POST /api/people, etc.) are now the preferred
    write path.
    """
    ensure_default_roles()

    incoming_fn_names = {
        (row.get("displayName") or "").strip()[:128]
        for row in payload.get("fnTags", []) or []
    }
    incoming_fn_names.discard("")
    FunctionTag.objects.exclude(display_name__in=incoming_fn_names).delete()
    for row in payload.get("fnTags", []) or []:
        upsert_function_tag(row, user)

    incoming_project_names = {
        (row.get("name") or "").strip()[:128]
        for row in payload.get("projects", []) or []
    }
    incoming_project_names.discard("")
    Project.objects.exclude(name__in=incoming_project_names).delete()
    for row in payload.get("projects", []) or []:
        upsert_project(row, user)

    incoming_person_ids = {
        (row.get("id") or "").strip()[:32]
        for row in payload.get("people", []) or []
    }
    incoming_person_ids.discard("")
    Person.objects.exclude(legacy_id__in=incoming_person_ids).delete()
    for row in payload.get("people", []) or []:
        upsert_person(row, user)

    incoming_manager_ids = {
        str(legacy_id).strip()[:32] for legacy_id in payload.get("mgrs", []) or []
    }
    incoming_manager_ids.discard("")
    ManagerProfile.objects.exclude(legacy_id__in=incoming_manager_ids).delete()
    for legacy_id in payload.get("mgrs", []) or []:
        upsert_manager(str(legacy_id), user)

    teams_payload = payload.get("teams") or {}
    for team_name in ("team-1", "team-2", "team-3", "pool"):
        if team_name in teams_payload:
            replace_team_membership(team_name, teams_payload.get(team_name) or [], user)

    replace_custom_dates(payload.get("customDates") or {}, user)
    update_planner_config(payload, user)

    incoming_entry_ids = {
        (entry.get("id") or "").strip()[:64]
        for entries in (payload.get("journal") or {}).values()
        for entry in entries
    }
    incoming_entry_ids.discard("")
    JournalEntry.objects.exclude(entry_id__in=incoming_entry_ids).delete()
    for person_id, entries in (payload.get("journal") or {}).items():
        for entry in entries:
            entry_with_person = {**entry, "personId": person_id}
            upsert_journal_entry(entry_with_person, user)

    _bump_state_version()
    return build_state_payload()
