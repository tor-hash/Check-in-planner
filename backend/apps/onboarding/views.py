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
