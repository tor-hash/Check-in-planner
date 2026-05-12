from django.contrib import admin

from .models import Invitation


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "invited_by", "created_at", "accepted_at")
    list_filter = ("accepted_at",)
    search_fields = ("email", "invited_by__email", "invited_by__username")
    readonly_fields = ("created_at", "accepted_at")
