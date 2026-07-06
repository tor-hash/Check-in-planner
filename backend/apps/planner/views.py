from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.planner.services.state import is_manager_or_admin, is_super_admin


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

    Only accessible to users who are managers (or admins). Regular managers
    always see their own settings. Super-admins (see
    ``services.state.is_super_admin``) may additionally pass
    ``?manager=<legacy_id>`` to view/edit another manager's settings, and get
    a manager-picker on the page itself to switch between them -- this is how
    the "am I even set up right" managers get looked after by someone else.
    """
    from apps.planner.models import ManagerProfile

    if not is_manager_or_admin(request.user):
        return redirect("planner:home")

    own_manager = getattr(request.user, "manager_profile", None)
    super_admin = is_super_admin(request.user)

    manager = None
    requested_id = (request.GET.get("manager") or "").strip()
    if super_admin and requested_id:
        manager = ManagerProfile.objects.filter(legacy_id=requested_id).first()

    if manager is None:
        manager = own_manager

    if manager is None and super_admin:
        # Super-admin with no ManagerProfile of their own (e.g. a pure admin
        # account) — default to the first manager instead of bouncing them to
        # the Django admin.
        manager = ManagerProfile.objects.order_by("legacy_id").first()

    if manager is None:
        # Not a super-admin and has no ManagerProfile of their own -- nothing
        # for a plain manager/admin group member to configure here.
        if request.user.is_superuser or request.user.is_staff:
            return redirect("/admin/planner/managerprofile/")
        return redirect("planner:home")

    return render(
        request,
        "planner/manager_settings.html",
        {
            "nav_section": "settings",
            "manager_id": manager.legacy_id,
            "planner_user_is_manager": True,
            "planner_user_is_super_admin": super_admin,
            "planner_user_email": request.user.email,
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


@login_required
def manager_bookings_view(request):
    """Booking overview: run history + recent meetings + 'Run now' button."""
    if not is_manager_or_admin(request.user):
        return redirect("planner:home")
    return render(
        request,
        "planner/manager_bookings.html",
        {
            "nav_section": "bookings",
            "planner_user_is_manager": True,
            "planner_user_email": request.user.email,
        },
    )
