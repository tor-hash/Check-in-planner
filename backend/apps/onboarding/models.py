"""Database models for the onboarding app.

Six tables:

* ``OnboardingProfile`` — extra info for an employee. 1:1 with Django User
  (we reuse ``auth.User`` so existing infra applies; the user is created
  ``is_active=False`` so they can never sign in).
* ``OnboardingFlow`` — a flow template (name + ordered steps).
* ``FlowStep`` — one ordered step inside a flow with a component type +
  config JSON validated by ``components.py``.
* ``OnboardingAssignment`` — one row per (employee, flow) pair.
* ``StepProgress`` — per-step state for a given assignment.
* ``WelcomeEmailTemplate`` — a named welcome email in one language (subject
  + HTML body with merge tags), picked per assignment. See ``welcome_email.py``.

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
from .countries import (
    COUNTRY_CHOICES,
    COUNTRY_NO,
    DEFAULT_COUNTRY,
    LANG_DA,
    LANGUAGE_CHOICES,
)


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
    # ``title``/``description`` are the primary (Danish) text. The
    # ``*_no`` fields are the Norwegian version, used for employees whose
    # country is Norway; blank falls back to the primary text.
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    title_no = models.CharField(max_length=200, blank=True)
    description_no = models.TextField(blank=True)
    config = models.JSONField(default=dict, blank=True)
    is_required = models.BooleanField(default=True)

    class Meta:
        unique_together = (("flow", "order"),)
        ordering = ["order"]

    def __str__(self) -> str:
        return f"{self.flow.slug} #{self.order} {self.title}"

    def clean(self) -> None:
        get_component(self.component_type).validate_config(self.config)

    def title_for(self, country: str | None) -> str:
        if (country or "").upper() == COUNTRY_NO and self.title_no.strip():
            return self.title_no
        return self.title

    def description_for(self, country: str | None) -> str:
        if (country or "").upper() == COUNTRY_NO and self.description_no.strip():
            return self.description_no
        return self.description


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
    country = models.CharField(
        max_length=2,
        choices=COUNTRY_CHOICES,
        default=DEFAULT_COUNTRY,
        help_text="Country the employee works in. Decides the language of "
        "their onboarding (welcome email, meeting titles) and which public "
        "holidays meeting booking skips.",
    )
    drive_folder_id = models.CharField(
        max_length=128,
        blank=True,
        help_text="Google Drive id of this employee's own document folder "
        "(created on first upload inside the Employee folder from "
        "OnboardingSettings). Remembered so renames don't create duplicates.",
    )

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
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="onboarding_assignments_made",
        help_text="Manager/user who attached this flow. Used as the welcome "
        "email sender and to resolve 'assigning_manager' meeting organizers.",
    )
    welcome_email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once the combined welcome/calendar-share email has "
        "been sent for this assignment. Re-attaching does not resend it.",
    )
    buddy_name = models.CharField(
        max_length=128,
        blank=True,
        help_text="Snapshot of the employee's planner Person.buddy name at "
        "attach/schedule time. Locked in alongside the welcome email, which "
        "only ever sends once. Available in the welcome email as the "
        "{{ buddy_name }} merge tag, and as the default meeting organizer "
        "for calendar_meeting steps configured with role 'buddy'.",
    )
    buddy_email = models.EmailField(
        blank=True,
        help_text="Snapshot of the employee's planner Person.buddy email at "
        "attach/schedule time. See buddy_name.",
    )
    leder_name = models.CharField(
        max_length=128,
        blank=True,
        help_text="Snapshot of the employee's planner Person.leder ('leder' "
        "— the manager they report to) name at attach/schedule time. "
        "Available in the welcome email as the {{ leder_name }} merge tag, "
        "and as the default meeting organizer for calendar_meeting steps "
        "(role 'leder', which is also what an unspecified role falls back to).",
    )
    leder_email = models.EmailField(
        blank=True,
        help_text="Snapshot of the employee's planner Person.leder email at "
        "attach/schedule time. See leder_name.",
    )
    scheduled_for = models.DateField(
        null=True,
        blank=True,
        help_text="The date this onboarding flow is planned to kick off. "
        "When this is today or in the past at attach time, the welcome "
        "email / calendar booking / Slack invite automation runs "
        "immediately. When it's in the future, the automation is deferred "
        "until that date (see management command run_scheduled_onboarding "
        "and scheduled_automation_ran_at).",
    )
    country = models.CharField(
        max_length=2,
        choices=COUNTRY_CHOICES,
        default=DEFAULT_COUNTRY,
        help_text="Snapshot of the employee's country at attach time — "
        "decides language and public holidays for this onboarding.",
    )
    welcome_email_template = models.ForeignKey(
        "WelcomeEmailTemplate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Welcome email chosen in the assign dialog. Empty means "
        "the default template for the assignment's language.",
    )
    scheduled_automation_ran_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once the attach automation (welcome email, calendar "
        "booking, Slack invite) has been attempted for this assignment — "
        "immediately at attach time, or later by run_scheduled_onboarding "
        "once scheduled_for arrives. Never re-attempted after this is set, "
        "mirroring welcome_email_sent_at's 'only ever once' semantics.",
    )

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


class WelcomeEmailTemplate(TimestampedModel):
    """A named, reusable welcome email in one language.

    Templates live in a library on the "Velkomstmail" tab and are not tied
    to a flow: the manager picks one in the "Tildel flow" dialog (stored on
    ``OnboardingAssignment.welcome_email_template``). Rendered with Django's
    own template engine against ``welcome_email.build_merge_context``.

    At most one template *per language* has ``is_default`` set — the one
    preselected in the assign dialog (and used when none was picked).
    Enforced in ``save()``, like ``OnboardingFlow.is_default``.
    """

    name = models.CharField(max_length=128)
    language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default=LANG_DA)
    subject = models.CharField(max_length=255)
    html_body = models.TextField()
    is_default = models.BooleanField(
        default=False,
        help_text="Preselected for new assignments in this language. Only one "
        "template per language can be the default.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["language", "name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.language}]" + (" (standard)" if self.is_default else "")

    def save(self, *args, **kwargs):
        if self.is_default:
            (
                WelcomeEmailTemplate.objects.exclude(pk=self.pk)
                .filter(is_default=True, language=self.language)
                .update(is_default=False)
            )
        super().save(*args, **kwargs)


class OnboardingSettings(TimestampedModel):
    """Global onboarding settings (Onboarding → Indstillinger tab). Singleton."""

    singleton_key = models.CharField(max_length=32, unique=True, default="default")
    drive_root_folder_id = models.CharField(
        max_length=128,
        blank=True,
        help_text="Google Drive id of the shared Employee folder. Each "
        "employee gets a sub-folder here for their documents.",
    )
    drive_root_folder_name = models.CharField(max_length=255, blank=True)
    # The account the system acts as: owns onboarding meetings, sends the
    # welcome email, uploads to Drive. NULL = never set here, use the
    # ONBOARDING_SCHEDULER_EMAIL env default; "" = deliberately off (old
    # behaviour: meetings in the first participant's calendar, welcome
    # email from whoever assigns the flow). See calendar_booking.scheduler_email.
    system_email = models.EmailField(
        max_length=254,
        null=True,
        blank=True,
        help_text="System account used for meetings, welcome emails and Drive "
        "uploads. Empty = none; unset = ONBOARDING_SCHEDULER_EMAIL.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    def __str__(self) -> str:
        return "Onboarding settings"

    @classmethod
    def load(cls) -> OnboardingSettings:
        obj, _ = cls.objects.get_or_create(singleton_key="default")
        return obj


class EmployeeDocument(TimestampedModel):
    """A document (contract, ...) uploaded to an employee's Drive folder.

    The file itself lives in Google Drive; this row is the app's record of
    it — who uploaded it, when, and the link to open it.
    """

    profile = models.ForeignKey(
        OnboardingProfile, related_name="documents", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=255)
    drive_file_id = models.CharField(max_length=128)
    web_view_link = models.URLField(max_length=500, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.profile.erp_employee_id}: {self.name}"
