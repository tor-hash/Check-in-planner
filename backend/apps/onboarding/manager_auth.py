"""Session auth for manager-facing onboarding management APIs."""
from __future__ import annotations

from functools import wraps

from django.http import HttpRequest, JsonResponse

from apps.planner.services.state import is_manager_or_admin


def require_manager_api(view_func):
    """Require logged-in manager/admin; return JSON errors for API clients."""

    @wraps(view_func)
    def wrapped(request: HttpRequest, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Authentication required."}, status=401)
        if not is_manager_or_admin(request.user):
            return JsonResponse(
                {"detail": "Only manager/admin users can perform this action."},
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return wrapped
