from django.urls import path

from .views import (
    invitation_revoke_view,
    invitations_view,
    profile_view,
)

urlpatterns = [
    path("profile/", profile_view, name="account-profile"),
    path("invites/", invitations_view, name="account-invitations"),
    path(
        "invites/<int:pk>/revoke/",
        invitation_revoke_view,
        name="account-invitation-revoke",
    ),
]
