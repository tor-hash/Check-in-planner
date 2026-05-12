from datetime import date

from django.conf import settings
from django.db import models

TEAM_CHOICES = (
    ("team-1", "Team 1"),
    ("team-2", "Team 2"),
    ("team-3", "Team 3"),
    ("pool", "Pool"),
)


class AuditFieldsModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_created",
        on_delete=models.SET_NULL,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
        on_delete=models.SET_NULL,
    )

    class Meta:
        abstract = True


class FunctionTag(AuditFieldsModel):
    label = models.CharField(max_length=16)
    display_name = models.CharField(max_length=128, unique=True)
    color = models.CharField(max_length=16, default="#6ea8fe")

    class Meta:
        ordering = ["display_name"]


class Project(AuditFieldsModel):
    name = models.CharField(max_length=128, unique=True)
    description = models.TextField(blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")

    class Meta:
        ordering = ["name"]


class Person(AuditFieldsModel):
    legacy_id = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    mbti = models.CharField(max_length=32, blank=True, default="")
    title = models.CharField(max_length=255, blank=True, default="")
    org = models.CharField(max_length=255, blank=True, default="BCT")
    function = models.ForeignKey(
        FunctionTag,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="people",
    )
    function_name = models.CharField(max_length=255, blank=True, default="")
    loc = models.CharField(max_length=255, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    linkedin = models.CharField(max_length=255, blank=True, default="")
    dessert = models.CharField(max_length=255, blank=True, default="")
    projects = models.ManyToManyField(Project, blank=True, related_name="people")

    class Meta:
        ordering = ["name"]


class ManagerProfile(AuditFieldsModel):
    legacy_id = models.CharField(max_length=32, unique=True)
    person = models.OneToOneField(
        Person,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="manager_profile",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="manager_profile",
    )

    class Meta:
        ordering = ["legacy_id"]


class TeamMembership(AuditFieldsModel):
    team = models.CharField(max_length=16, choices=TEAM_CHOICES)
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="team_memberships")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["team", "sort_order", "person__name"]
        unique_together = (("team", "person"),)


class PlannerConfig(AuditFieldsModel):
    singleton_key = models.CharField(max_length=32, unique=True, default="default")
    start_date = models.DateField()
    work_hours = models.JSONField(default=dict, blank=True)
    viewed_mgr_filter = models.CharField(max_length=32, default="all")
    week_offset = models.IntegerField(default=0)

    @classmethod
    def singleton(cls):
        obj, _ = cls.objects.get_or_create(
            singleton_key="default",
            defaults={
                "start_date": date(2026, 1, 5),
                "work_hours": {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True},
            },
        )
        return obj


class CustomDate(AuditFieldsModel):
    key = models.CharField(max_length=255, unique=True)
    value = models.CharField(max_length=64)

    class Meta:
        ordering = ["key"]


class JournalEntry(AuditFieldsModel):
    entry_id = models.CharField(max_length=64, unique=True)
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="journal_entries")
    manager = models.ForeignKey(
        ManagerProfile,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_entries",
    )
    date = models.DateField()
    trivsel = models.TextField(blank=True, default="")
    faglig = models.TextField(blank=True, default="")
    personlig = models.TextField(blank=True, default="")
    udfordringer = models.TextField(blank=True, default="")
    maal = models.TextField(blank=True, default="")
    noter = models.TextField(blank=True, default="")
    opfolgning = models.TextField(blank=True, default="")
    obs = models.TextField(blank=True, default="")
    # Inline file metadata snapshot (legacy compat). Authoritative file rows
    # live in JournalEntryFile via the FK below.
    files = models.JSONField(default=list, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-updated_at"]


def journal_attachment_path(instance, filename: str) -> str:
    """Storage path: journal/<entry_id>/<filename>."""
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"journal/{instance.entry.entry_id}/{safe_name}"


class JournalEntryFile(AuditFieldsModel):
    """File attachment for a JournalEntry, stored in Django's file storage."""

    entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="attachments"
    )
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.PositiveIntegerField(default=0)
    file = models.FileField(upload_to=journal_attachment_path)

    class Meta:
        ordering = ["-created_at"]

    def serialize(self) -> dict:
        return {
            "id": self.pk,
            "name": self.name,
            "type": self.content_type,
            "size": self.size_bytes,
            "url": self.file.url if self.file else "",
        }


class PlannerStateVersion(models.Model):
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def singleton(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"version": 1})
        return obj


# ---------------------------------------------------------------------------
# Rotation + booking domain
# ---------------------------------------------------------------------------


class RotationSession(AuditFieldsModel):
    """One slot in the 6-week rotation calendar.

    A "cycle" is 3 sessions (biweekly) covering 3 teams x 3 managers, so each
    manager meets each team exactly once per cycle. ``cycle_start`` is the
    Monday of week 1 in that cycle; ``session_index`` is 0/1/2 (week 1, 3, 5).
    """

    cycle_start = models.DateField()
    session_index = models.PositiveSmallIntegerField()
    team = models.CharField(max_length=16, choices=TEAM_CHOICES)
    manager = models.ForeignKey(
        "ManagerProfile", on_delete=models.PROTECT, related_name="rotation_sessions"
    )

    class Meta:
        ordering = ["cycle_start", "session_index", "team"]
        unique_together = (("cycle_start", "session_index", "team"),)

    def __str__(self) -> str:
        return f"{self.cycle_start.isoformat()} #{self.session_index} {self.team} -> {self.manager_id}"


class CheckInMeeting(AuditFieldsModel):
    """A scheduled 1:1 between a manager and a developer.

    The Google Calendar event is the source of truth for "did this happen"
    (the link in google_html_link), but we record the booking here so we have
    an audit trail, can enforce the rotation contract, and can attach a
    JournalEntry once the conversation is written up.
    """

    STATUS_CHOICES = (
        ("scheduled", "Scheduled"),
        ("cancelled", "Cancelled"),
        ("completed", "Completed"),
    )

    manager = models.ForeignKey(
        "ManagerProfile", on_delete=models.PROTECT, related_name="check_ins"
    )
    person = models.ForeignKey(
        "Person", on_delete=models.PROTECT, related_name="check_ins"
    )
    session = models.ForeignKey(
        RotationSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="check_ins",
    )
    starts_at = models.DateTimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=30)
    title = models.CharField(max_length=255, blank=True, default="Check-in samtale")
    agenda = models.TextField(blank=True, default="")
    google_event_id = models.CharField(max_length=128, blank=True, default="")
    google_html_link = models.URLField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="scheduled")
    journal_entry = models.OneToOneField(
        "JournalEntry",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="check_in",
    )

    class Meta:
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["manager", "starts_at"]),
            models.Index(fields=["person", "starts_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.manager_id} x {self.person_id} @ {self.starts_at.isoformat()}"
