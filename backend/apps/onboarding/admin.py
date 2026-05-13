from __future__ import annotations

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError

from .components import get_component
from .models import (
    FlowStep,
    OnboardingAssignment,
    OnboardingFlow,
    OnboardingProfile,
    StepProgress,
)


class FlowStepForm(forms.ModelForm):
    class Meta:
        model = FlowStep
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        component_type = cleaned.get("component_type")
        config = cleaned.get("config", {})
        if component_type:
            try:
                get_component(component_type).validate_config(config)
            except ValidationError as exc:
                self.add_error("config", exc)
        return cleaned


class FlowStepInline(admin.TabularInline):
    model = FlowStep
    form = FlowStepForm
    extra = 0
    fields = ("order", "component_type", "title", "is_required", "config")
    ordering = ("order",)


@admin.register(OnboardingFlow)
class OnboardingFlowAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "is_default", "is_active", "step_count")
    list_filter = ("is_default", "is_active")
    search_fields = ("slug", "name")
    inlines = [FlowStepInline]
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Steps")
    def step_count(self, obj: OnboardingFlow) -> int:
        return obj.steps.count()


@admin.register(FlowStep)
class FlowStepAdmin(admin.ModelAdmin):
    form = FlowStepForm
    list_display = ("flow", "order", "component_type", "title", "is_required")
    list_filter = ("component_type", "flow")
    search_fields = ("title", "flow__slug")
    autocomplete_fields = ("flow",)


@admin.register(OnboardingProfile)
class OnboardingProfileAdmin(admin.ModelAdmin):
    list_display = ("erp_employee_id", "email", "first_name", "last_name", "start_date")
    search_fields = ("erp_employee_id", "user__email", "first_name", "last_name")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Email")
    def email(self, obj: OnboardingProfile) -> str:
        return obj.user.email


@admin.register(OnboardingAssignment)
class OnboardingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("profile", "flow", "status", "assigned_at", "completed_at")
    list_filter = ("status", "flow")
    search_fields = ("profile__erp_employee_id", "profile__user__email")
    readonly_fields = ("assigned_at", "started_at", "completed_at", "created_at", "updated_at")
    autocomplete_fields = ("profile", "flow")


@admin.register(StepProgress)
class StepProgressAdmin(admin.ModelAdmin):
    list_display = ("assignment", "step", "status", "completed_at", "completed_by")
    list_filter = ("status",)
    search_fields = (
        "assignment__profile__erp_employee_id",
        "step__title",
    )
    readonly_fields = (
        "assignment",
        "step",
        "completed_at",
        "completed_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return False
