"""API-key auth for the onboarding REST API.

Single shared token (``settings.ONBOARDING_API_TOKEN``). When the token is
unset the API responds 503 — that way local dev / CI / a fresh deploy
without the secret configured never accidentally exposes the endpoints
without auth.
"""
from __future__ import annotations

import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def require_api_key(view_func):
    """Decorator: enforce ``X-API-Key`` matches ``ONBOARDING_API_TOKEN``.

    Also strips CSRF (this API is service-to-service, never browser
    sessions). Returns:

    * 503 — token not configured at all
    * 401 — header missing
    * 403 — header present but wrong
    """

    @csrf_exempt
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        expected = getattr(settings, "ONBOARDING_API_TOKEN", "") or ""
        if not expected:
            return JsonResponse(
                {"detail": "Onboarding API token not configured on this deployment."},
                status=503,
            )
        provided = request.headers.get("X-API-Key", "")
        if not provided:
            return JsonResponse({"detail": "Missing X-API-Key header."}, status=401)
        if not hmac.compare_digest(provided, expected):
            return JsonResponse({"detail": "Invalid X-API-Key."}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapped
