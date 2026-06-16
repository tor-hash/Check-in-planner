from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.planner.services.state import is_manager_or_admin


@login_required
def home_view(request):
    return render(
        request,
        "planner/index.html",
        {"nav_section": "home"},
    )


@login_required
@ensure_csrf_cookie
def app_view(request):
    return render(
        request,
        "checkin-planner.html",
        {
            "nav_section": "planner",
            "planner_api_base": "/api",
            "planner_user_email": request.user.email,
            "planner_user_is_manager": is_manager_or_admin(request.user),
            "planner_use_sheet_journal": getattr(settings, "USE_GOOGLE_SHEET_JOURNAL", False),
        },
    )


@login_required
def manager_settings_view(request):
    """Per-manager booking preference page.

    Only accessible to users who are managers (or admins).  The page itself is
    a thin shell that loads settings via the JSON API, so the template just
    needs the manager's legacy_id to build the API URL.
    """
    if not is_manager_or_admin(request.user):
        return redirect("planner:home")
    manager = getattr(request.user, "manager_profile", None)
    if manager is None:
        return redirect("planner:home")
    return render(
        request,
        "planner/manager_settings.html",
        {
            "nav_section": "settings",
            "manager_id": manager.legacy_id,
        },
    )


def root_redirect(request):
    return redirect("planner:home")


def healthz_view(request):
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse({"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "error"}, status=status)
