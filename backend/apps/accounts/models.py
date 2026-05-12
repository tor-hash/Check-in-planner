"""Models for the accounts app.

Currently this app only owns the ``Invitation`` model: a lightweight way for
existing users to invite new colleagues to sign in without an admin having
to edit the ``GOOGLE_WORKSPACE_ALLOWED_EMAILS`` env var. The static env-var
allowlist still acts as the seed list (it bootstraps the first users);
afterwards anyone with a Django user can invite the next person.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class Invitation(models.Model):
    """An open invitation for ``email`` to sign in.

    The pipeline step ``apps.accounts.pipeline.ensure_allowed_email`` consults
    this table. An invitation is *open* when ``accepted_at is None``; the
    first time the invited address signs in successfully we stamp
    ``accepted_at`` so the same row cannot be reused later.
    """

    email = models.EmailField(unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="invitations_sent",
    )
    created_at = models.DateTimeField(default=timezone.now)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        status = "accepted" if self.accepted_at else "pending"
        return f"{self.email} ({status})"

    @property
    def is_open(self) -> bool:
        return self.accepted_at is None

    def mark_accepted(self) -> None:
        self.accepted_at = timezone.now()
        self.save(update_fields=["accepted_at"])
