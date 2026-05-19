from django.contrib import admin

from .models import (
    CheckInMeeting,
    CustomDate,
    FunctionTag,
    JournalEntry,
    JournalEntryFile,
    ManagerProfile,
    Person,
    PlannerConfig,
    PlannerStateVersion,
    Project,
    RotationSession,
    TeamMembership,
)


@admin.register(FunctionTag)
class FunctionTagAdmin(admin.ModelAdmin):
    list_display = ("display_name", "label", "color", "updated_at")
    search_fields = ("display_name", "label")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "updated_at")
    search_fields = ("name",)


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ("legacy_id", "name", "email", "function_name", "updated_at")
    search_fields = ("legacy_id", "name", "email")


@admin.register(ManagerProfile)
class ManagerProfileAdmin(admin.ModelAdmin):
    list_display = ("legacy_id", "person", "user", "updated_at")
    search_fields = ("legacy_id", "person__name", "user__email")


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("team", "person", "sort_order", "updated_at")
    list_filter = ("team",)


@admin.register(PlannerConfig)
class PlannerConfigAdmin(admin.ModelAdmin):
    list_display = ("singleton_key", "start_date", "weeks_per_session", "updated_at")


@admin.register(CustomDate)
class CustomDateAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key",)


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("entry_id", "person", "manager", "date", "updated_at", "deleted_at")
    search_fields = ("entry_id", "person__name")
    list_filter = ("date", "deleted_at")


@admin.register(JournalEntryFile)
class JournalEntryFileAdmin(admin.ModelAdmin):
    list_display = ("id", "entry", "name", "size_bytes", "content_type", "created_at")
    search_fields = ("name", "entry__entry_id")


@admin.register(PlannerStateVersion)
class PlannerStateVersionAdmin(admin.ModelAdmin):
    list_display = ("id", "version", "updated_at")


@admin.register(RotationSession)
class RotationSessionAdmin(admin.ModelAdmin):
    list_display = ("cycle_start", "session_index", "team", "manager", "updated_at")
    list_filter = ("cycle_start", "team")
    search_fields = ("manager__legacy_id", "team")


@admin.register(CheckInMeeting)
class CheckInMeetingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "manager",
        "person",
        "starts_at",
        "duration_minutes",
        "status",
        "google_event_id",
        "updated_at",
    )
    list_filter = ("status", "manager")
    search_fields = (
        "manager__legacy_id",
        "person__legacy_id",
        "person__name",
        "google_event_id",
    )
    readonly_fields = ("google_event_id", "google_html_link")
