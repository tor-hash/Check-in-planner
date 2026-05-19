"""Biweekly rotation engine.

Rule: 3 teams x 3 managers in a 6-week cycle of 3 biweekly sessions, where
each manager meets each team exactly once per cycle. Sessions are indexed
0/1/2 corresponding to weeks 1/3/5 of the cycle.

Default assignment matrix (rotates each session so each manager hits each
team once across the cycle)::

           Session 0   Session 1   Session 2
    team-1 mgr_0       mgr_1       mgr_2
    team-2 mgr_1       mgr_2       mgr_0
    team-3 mgr_2       mgr_0       mgr_1

The week-offset on PlannerConfig shifts the starting session, so successive
cycles can rotate which manager opens with which team.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from django.db import transaction
from django.utils import timezone

from apps.planner.models import (
    ManagerProfile,
    Person,
    PlannerConfig,
    RotationSession,
    TeamMembership,
)

logger = logging.getLogger(__name__)


SESSIONS_PER_CYCLE = 3
DEFAULT_WEEKS_PER_SESSION = 2
MIN_WEEKS_PER_SESSION = 1
MAX_WEEKS_PER_SESSION = 12
TEAM_KEYS = ("team-1", "team-2", "team-3")


def weeks_per_session_value() -> int:
    """Weeks per check-in rotation block (from PlannerConfig, default 2)."""
    try:
        n = int(PlannerConfig.singleton().weeks_per_session)
    except (TypeError, ValueError, AttributeError):
        n = DEFAULT_WEEKS_PER_SESSION
    return max(MIN_WEEKS_PER_SESSION, min(MAX_WEEKS_PER_SESSION, n))


def cycle_weeks_value() -> int:
    return SESSIONS_PER_CYCLE * weeks_per_session_value()


class RotationError(ValueError):
    """Raised when rotation invariants are violated."""


@dataclass(frozen=True)
class SessionWindow:
    cycle_start: date
    session_index: int
    week_start: date  # Monday of the session's first week
    week_end: date    # Sunday of the session's second week (inclusive)

    def contains(self, when: date) -> bool:
        return self.week_start <= when <= self.week_end


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _config_start() -> date:
    cfg = PlannerConfig.singleton()
    return _monday_of(cfg.start_date)


def cycle_start_for(when: date | None = None) -> date:
    """Return the Monday of week 1 of the cycle that contains ``when``."""
    when = when or timezone.now().date()
    when = _monday_of(when)
    base = _config_start()
    if when < base:
        # Jobs in the past — fall back to the configured base.
        return base
    weeks_since_base = (when - base).days // 7
    cycle_weeks = cycle_weeks_value()
    cycles_since_base = weeks_since_base // cycle_weeks
    return base + timedelta(weeks=cycles_since_base * cycle_weeks)


def session_window_for(when: date | datetime | None = None) -> SessionWindow:
    """Return the SessionWindow that contains ``when``."""
    if isinstance(when, datetime):
        when = when.date()
    when = when or timezone.now().date()
    cycle_start = cycle_start_for(when)
    wps = weeks_per_session_value()
    weeks_into = (_monday_of(when) - cycle_start).days // 7
    session_index = max(0, min(SESSIONS_PER_CYCLE - 1, weeks_into // wps))
    week_start = cycle_start + timedelta(weeks=session_index * wps)
    week_end = week_start + timedelta(weeks=wps) - timedelta(days=1)
    return SessionWindow(
        cycle_start=cycle_start,
        session_index=session_index,
        week_start=week_start,
        week_end=week_end,
    )


def upcoming_session_windows(n: int = 4, *, from_date: date | None = None) -> list[SessionWindow]:
    """Return the next ``n`` session windows starting at the one containing ``from_date``."""
    if n <= 0:
        return []
    base = session_window_for(from_date)
    out = [base]
    cycle_start = base.cycle_start
    session_index = base.session_index
    while len(out) < n:
        session_index += 1
        wps = weeks_per_session_value()
        if session_index >= SESSIONS_PER_CYCLE:
            session_index = 0
            cycle_start = cycle_start + timedelta(weeks=cycle_weeks_value())
        week_start = cycle_start + timedelta(weeks=session_index * wps)
        week_end = week_start + timedelta(weeks=wps) - timedelta(days=1)
        out.append(
            SessionWindow(
                cycle_start=cycle_start,
                session_index=session_index,
                week_start=week_start,
                week_end=week_end,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Cycle generation
# ---------------------------------------------------------------------------


def _ordered_managers() -> list[ManagerProfile]:
    """Return managers in the canonical order (insertion order via id)."""
    return list(ManagerProfile.objects.order_by("id"))


def _default_assignment_matrix(managers: list[ManagerProfile]) -> dict[tuple[int, str], ManagerProfile]:
    """Build the default ``(session_index, team) -> manager`` matrix.

    Uses the rotating matrix described in the module docstring. Requires at
    least 3 managers; extra managers cycle through additional sessions.
    """
    if len(managers) < 3:
        raise RotationError("Rotation requires at least 3 managers.")
    matrix: dict[tuple[int, str], ManagerProfile] = {}
    for s in range(SESSIONS_PER_CYCLE):
        for t_idx, team in enumerate(TEAM_KEYS):
            mgr_idx = (s + t_idx) % len(managers)
            matrix[(s, team)] = managers[mgr_idx]
    return matrix


@transaction.atomic
def generate_cycle(cycle_start: date | None = None) -> list[RotationSession]:
    """Materialise (or update) a full cycle of RotationSession rows.

    Returns the 9 sessions for this cycle (3 sessions x 3 teams). Existing
    rows in this cycle are updated in place; missing rows are created. We
    don't delete extras — manual overrides set in admin are preserved unless
    they collide with a default assignment.
    """
    cycle_start = cycle_start or _config_start()
    cycle_start = _monday_of(cycle_start)
    managers = _ordered_managers()
    if not managers:
        logger.warning("generate_cycle called with no managers configured")
        return []
    matrix = _default_assignment_matrix(managers)

    sessions: list[RotationSession] = []
    for (session_index, team), manager in matrix.items():
        session, _ = RotationSession.objects.update_or_create(
            cycle_start=cycle_start,
            session_index=session_index,
            team=team,
            defaults={"manager": manager},
        )
        sessions.append(session)
    return sessions


def get_or_create_session(
    *, cycle_start: date, session_index: int, team: str
) -> RotationSession | None:
    """Look up the rotation session that owns this slot.

    If the row doesn't exist yet (cycle not generated), materialise the cycle
    on demand and try again.
    """
    qs = RotationSession.objects.filter(
        cycle_start=cycle_start, session_index=session_index, team=team
    )
    session = qs.first()
    if session:
        return session
    generate_cycle(cycle_start)
    return RotationSession.objects.filter(
        cycle_start=cycle_start, session_index=session_index, team=team
    ).first()


# ---------------------------------------------------------------------------
# Booking validation
# ---------------------------------------------------------------------------


def _team_for_person(person: Person) -> str | None:
    membership = (
        TeamMembership.objects.filter(person=person)
        .exclude(team="pool")
        .order_by("team")
        .first()
    )
    return membership.team if membership else None


@dataclass
class ValidationOutcome:
    ok: bool
    session: RotationSession | None
    reason: str = ""


def validate_booking(
    *,
    manager: ManagerProfile,
    person: Person,
    when: datetime,
) -> ValidationOutcome:
    """Reject bookings that violate the rotation contract.

    The booking is allowed iff:
      - the person belongs to a team (not just the pool), and
      - the active RotationSession for that ``when`` assigns the person's
        team to ``manager``.

    Pool members can be booked by any manager — they're not on rotation.
    """
    team = _team_for_person(person)
    if team is None:
        # Pool: any manager can book.
        return ValidationOutcome(ok=True, session=None)

    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)

    window = session_window_for(when.date())
    session = get_or_create_session(
        cycle_start=window.cycle_start,
        session_index=window.session_index,
        team=team,
    )
    if session is None:
        return ValidationOutcome(
            ok=False,
            session=None,
            reason=f"No rotation session for {team} in cycle starting {window.cycle_start}.",
        )
    if session.manager_id != manager.id:
        return ValidationOutcome(
            ok=False,
            session=session,
            reason=(
                f"This week '{team}' is assigned to manager '{session.manager.legacy_id}', "
                f"not '{manager.legacy_id}'."
            ),
        )
    return ValidationOutcome(ok=True, session=session)


# ---------------------------------------------------------------------------
# Helpers exposed to the API layer
# ---------------------------------------------------------------------------


def assigned_emails_for(manager: ManagerProfile, *, include_self: bool = True) -> list[str]:
    """Emails the manager should query free/busy against in the current session.

    Includes the manager's own email if ``include_self`` and they have one,
    plus all developers on the team currently assigned to this manager.
    """
    out: list[str] = []
    if include_self and manager.person and manager.person.email:
        out.append(manager.person.email)

    window = session_window_for()
    for team in TEAM_KEYS:
        session = get_or_create_session(
            cycle_start=window.cycle_start,
            session_index=window.session_index,
            team=team,
        )
        if session and session.manager_id == manager.id:
            for membership in TeamMembership.objects.select_related("person").filter(team=team):
                email = membership.person.email
                if email and email not in out:
                    out.append(email)
            break
    return out


def people_by_emails(emails: Iterable[str]) -> dict[str, Person]:
    return {p.email.lower(): p for p in Person.objects.filter(email__in=emails) if p.email}
