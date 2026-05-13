"""Database models for the onboarding app.

Five tables:

* ``OnboardingProfile`` — extra info for an employee. 1:1 with Django User
  (we reuse ``auth.User`` so existing infra applies; the user is created
  ``is_active=False`` so they can never sign in).
* ``OnboardingFlow`` — a flow template (name + ordered steps).
* ``FlowStep`` — one ordered step inside a flow with a component type +
  config JSON validated by ``components.py``.
* ``OnboardingAssignment`` — one row per (employee, flow) pair.
* ``StepProgress`` — per-step state for a given assignment.

When an assignment is created we snapshot one ``StepProgress`` row per
``FlowStep`` so the template can later be edited without retro-affecting
in-flight onboardings (we still FK to the step; we just don't delete
progress rows when the template changes).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .components import COMPONENT_CHOICES, get_component


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OnboardingFlow(TimestampedModel):
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if self.is_default:
            (
                OnboardingFlow.objects.exclude(pk=self.pk)
                .filter(is_default=True)
                .update(is_default=False)
            )
        super().save(*args, **kwargs)


class FlowStep(TimestampedModel):
    flow = models.ForeignKey(
        OnboardingFlow, related_name="steps", on_delete=models.CASCADE
    )
    order = models.PositiveIntegerField()
    component_type = models.CharField(max_length=64, choices=COMPONENT_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    config = models.JSONField(default=dict, blank=True)
    is_required = models.BooleanField(default=True)

    class Meta:
        unique_together = (("flow", "order"),)
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.flow.slug} #{self.order} {self.title}"

    def clean(self) -> None:
        get_component(self.component_type).validate_config(self.config)


class OnboardingProfile(TimestampedModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="onboarding_profile",
    )
    erp_employee_id = models.CharField(max_length=64, unique=True)
    first_name = models.CharField(max_length=128, blank=True)
    last_name = models.CharField(max_length=128, blank=True)
    position = models.CharField(max_length=128, blank=True)
    department = models.CharField(max_length=128, blank=True)
    start_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.erp_employee_id} ({self.user.email})"


class OnboardingAssignment(TimestampedModel):
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_COMPLETED, "Completed"),
    )

    profile = models.ForeignKey(
        OnboardingProfile, related_name="assignments", on_delete=models.CASCADE
    )
    flow = models.ForeignKey(OnboardingFlow, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    assigned_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "flow"], name="onboarding_unique_profile_flow"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.profile.erp_employee_id} → {self.flow.slug} ({self.status})"


class StepProgress(TimestampedModel):
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_SKIPPED, "Skipped"),
    )

    assignment = models.ForeignKey(
        OnboardingAssignment, related_name="step_progress", on_delete=models.CASCADE
    )
    step = models.ForeignKey(FlowStep, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    completion_data = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.CharField(max_length=128, blank=True)

    class Meta:
        ordering = ["step__order"]
        unique_together = (("assignment", "step"),)

    def __str__(self) -> str:
        return f"{self.assignment} step={self.step.order} {self.status}"

    def clean(self) -> None:
        if self.status == self.STATUS_COMPLETED:
            get_component(self.step.component_type).validate_completion(self.completion_data)
