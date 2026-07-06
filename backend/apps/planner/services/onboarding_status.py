"""Helpers to check whether a Person is in an active onboarding and has a team.

Used by the auto-booking guard to skip employees who are not yet fully
onboarded or who have not been assigned to a team.

Rules:
- ``has_team_assignment``: True if the person has at least one TeamMembership.
- ``onboarding_is_complete``: True if the person has no linked OnboardingProfile
  (legacy / already-onboarded employee), OR the most recent assignment is
  ``completed``. While an assignment is ``pending`` or ``in_progress`` the
  function returns False and auto-booking will skip the person.
"""
from __future__ import annotations

from apps.planner.models import Person


def has_team_assignment(person: Person) -> bool:
    """Return True if person belongs to at least one team."""
    return person.team_memberships.exists()


def onboarding_is_complete(person: Person) -> bool:
    """Return True when the person should be included in auto-booking.

    - No linked OnboardingProfile → legacy employee, treat as done.
    - OnboardingProfile with no assignment → treat as done.
    - Latest assignment status == 'completed' → done.
    - Otherwise (pending / in_progress) → False, skip from auto-booking.
    """
    op = getattr(person, "onboarding_profile", None)
    if op is None:
        return True  # no profile: already-active / legacy employee

    # Use prefetch-aware accessor; fall back to a DB query if needed.
    assignment = (
        op.assignments.order_by("-assigned_at").first()
    )
    if assignment is None:
        return True  # profile exists but no flow assigned yet → treat as done

    from apps.onboarding.models import OnboardingAssignment  # local import avoids circular
    return assignment.status == OnboardingAssignment.STATUS_COMPLETED
