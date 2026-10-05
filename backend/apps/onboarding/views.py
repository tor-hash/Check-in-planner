from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.planner.services.state import is_manager_or_admin


@login_required(login_url="/accounts/login/")
@ensure_csrf_cookie
def flows_editor_view(request):
    if not is_manager_or_admin(request.user):
        return redirect("planner:home")
    return render(
        request,
        "onboarding/flows_editor.html",
        {
            "nav_section": "onboarding",
            "onboarding_api_base": "/api/onboarding/manage",
        },
    )


@login_required(login_url="/accounts/login/")
def drive_connect_view(request):
    """Start a Google sign-in that also asks for Google Drive access.

    Meant to be clicked once while signed in as the scheduler account —
    see ``google_auth.py``. Comes back to the Indstillinger tab.
    """
    from .google_auth import DRIVE_CONNECT_SESSION_KEY

    if not is_manager_or_admin(request.user):
        return redirect("planner:home")
    request.session[DRIVE_CONNECT_SESSION_KEY] = True
    return redirect("/auth/login/google-oauth2/?next=/onboarding/flows/%23indstillinger")
