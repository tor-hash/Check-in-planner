from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .models import Invitation


@login_required
def profile_view(request):
    return JsonResponse(
        {
            "id": request.user.id,
            "email": request.user.email,
            "name": request.user.get_full_name() or request.user.get_username(),
        }
    )


def _allowed_domains() -> set[str]:
    return {
        d.lower()
        for d in getattr(settings, "SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS", [])
        if d
    }


def _validate_invite_email(raw: str, *, inviter_email: str) -> str:
    """Normalise + validate an email address for an invitation.

    Raises ``ValidationError`` with a user-facing message on any problem.
    Returns the normalised (lowercase, stripped) email on success.
    """
    email = (raw or "").strip().lower()
    if not email:
        raise ValidationError("Please enter an email address.")

    try:
        validate_email(email)
    except ValidationError as exc:
        raise ValidationError("That doesn't look like a valid email address.") from exc

    domain = email.split("@", 1)[1]
    allowed = _allowed_domains()
    if allowed and domain not in allowed:
        pretty = ", ".join(sorted(allowed))
        raise ValidationError(f"Only emails on {pretty} can be invited.")

    if email == (inviter_email or "").strip().lower():
        raise ValidationError("You don't need to invite yourself.")

    User = get_user_model()
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError("That person already has an account.")

    if Invitation.objects.filter(email__iexact=email, accepted_at__isnull=True).exists():
        raise ValidationError("That email already has a pending invitation.")

    return email


@login_required
@require_http_methods(["GET", "POST"])
def invitations_view(request):
    """List + create invitations.

    Any logged-in user can invite. We deliberately show *all* invitations
    (not just the ones the caller sent) so people don't accidentally
    duplicate each other's work.
    """
    if request.method == "POST":
        try:
            email = _validate_invite_email(
                request.POST.get("email", ""),
                inviter_email=request.user.email,
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return HttpResponseRedirect(reverse("account-invitations"))

        Invitation.objects.create(email=email, invited_by=request.user)
        messages.success(
            request,
            f"Invitation sent to {email}. They can now sign in with Google.",
        )
        return HttpResponseRedirect(reverse("account-invitations"))

    pending = list(Invitation.objects.filter(accepted_at__isnull=True).select_related("invited_by"))
    accepted = list(
        Invitation.objects.filter(accepted_at__isnull=False)
        .select_related("invited_by")
        .order_by("-accepted_at")[:25]
    )
    return render(
        request,
        "accounts/invitations.html",
        {
            "nav_section": "invite",
            "pending": pending,
            "accepted": accepted,
            "allowed_domains": sorted(_allowed_domains()),
        },
    )


@login_required
@require_http_methods(["POST"])
def invitation_revoke_view(request, pk: int):
    invitation = get_object_or_404(Invitation, pk=pk, accepted_at__isnull=True)
    # Only the original inviter or staff can revoke.
    if invitation.invited_by_id != request.user.id and not request.user.is_staff:
        messages.error(request, "You can only revoke invitations you sent yourself.")
        return HttpResponseRedirect(reverse("account-invitations"))

    email = invitation.email
    invitation.delete()
    messages.success(request, f"Invitation to {email} revoked.")
    return HttpResponseRedirect(reverse("account-invitations"))
