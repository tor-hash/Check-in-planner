"""Test helpers for building onboarding fixtures."""
from __future__ import annotations

from apps.onboarding.models import FlowStep, OnboardingFlow


def make_default_flow(slug: str = "default", *, with_steps: bool = True) -> OnboardingFlow:
    flow, _ = OnboardingFlow.objects.update_or_create(
        slug=slug,
        defaults={
            "name": "Test flow",
            "description": "",
            "is_default": True,
            "is_active": True,
        },
    )
    if not with_steps:
        return flow
    FlowStep.objects.update_or_create(
        flow=flow,
        order=1,
        defaults={
            "component_type": "info_link",
            "title": "Read handbook",
            "config": {"url": "https://example.com/handbook"},
            "is_required": True,
        },
    )
    FlowStep.objects.update_or_create(
        flow=flow,
        order=2,
        defaults={
            "component_type": "checkbox",
            "title": "Photo taken",
            "config": {"label": "Photo taken?"},
            "is_required": True,
        },
    )
    FlowStep.objects.update_or_create(
        flow=flow,
        order=3,
        defaults={
            "component_type": "form",
            "title": "Tax info",
            "config": {
                "fields": [
                    {"name": "tax_number", "label": "Tax #", "type": "text", "required": True},
                ]
            },
            "is_required": False,
        },
    )
    return flow
