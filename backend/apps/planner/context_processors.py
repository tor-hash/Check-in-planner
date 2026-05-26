"""Template context shared by the authenticated app shell."""
from __future__ import annotations

from apps.planner.services.state import is_manager_or_admin


def app_shell(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "planner_user_is_manager": is_manager_or_admin(request.user),
        "planner_user_email": request.user.email or request.user.username,
    }
