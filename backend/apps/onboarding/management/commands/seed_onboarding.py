"""Seed the default onboarding flow.

Idempotent: looks up the flow by slug. New steps are appended; existing
steps are updated in place by ``order`` so re-running won't multiply them.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.onboarding.models import FlowStep, OnboardingFlow

DEFAULT_FLOW_SLUG = "default"
DEFAULT_FLOW_NAME = "BCT onboarding"
DEFAULT_FLOW_DESCRIPTION = "Welcome flow for every new BCT employee."

DEFAULT_STEPS = [
    {
        "order": 1,
        "component_type": "info_link",
        "title": "Read employee handbook",
        "description": "Skim the BCT handbook end to end.",
        "is_required": True,
        "config": {
            "body": "Click the link, read the handbook, then mark this step complete.",
            "url": "https://blackcapitaltechnology.com/handbook",
            "requires_read": True,
        },
    },
    {
        "order": 2,
        "component_type": "checkbox",
        "title": "Employee photo taken",
        "description": "Reception takes a photo for your badge.",
        "is_required": True,
        "config": {"label": "Photo taken?"},
    },
    {
        "order": 3,
        "component_type": "form",
        "title": "Tax information",
        "description": "Fill in your tax details so payroll can register you.",
        "is_required": True,
        "config": {
            "fields": [
                {"name": "tax_number", "label": "Tax number", "type": "text", "required": True},
                {"name": "country", "label": "Country of residence", "type": "text", "required": True},
            ]
        },
    },
    {
        "order": 4,
        "component_type": "calendar_meeting",
        "title": "Welcome 1:1 with manager",
        "description": "30-minute kickoff with your direct manager.",
        "is_required": True,
        "config": {
            "with_email": "hr@blackcapitaltechnology.com",
            "duration_minutes": 30,
            "suggested_window": "first week",
        },
    },
]


class Command(BaseCommand):
    help = "Create or update the default onboarding flow."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            default=DEFAULT_FLOW_SLUG,
            help=f"Flow slug to seed (default: {DEFAULT_FLOW_SLUG}).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        slug = options["slug"]
        flow, created = OnboardingFlow.objects.update_or_create(
            slug=slug,
            defaults={
                "name": DEFAULT_FLOW_NAME,
                "description": DEFAULT_FLOW_DESCRIPTION,
                "is_default": True,
                "is_active": True,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} flow '{slug}'."))

        for step_payload in DEFAULT_STEPS:
            step, step_created = FlowStep.objects.update_or_create(
                flow=flow,
                order=step_payload["order"],
                defaults={
                    "component_type": step_payload["component_type"],
                    "title": step_payload["title"],
                    "description": step_payload["description"],
                    "is_required": step_payload["is_required"],
                    "config": step_payload["config"],
                },
            )
            verb = "Created" if step_created else "Updated"
            self.stdout.write(f"  {verb} step #{step.order}: {step.title}")

        self.stdout.write(self.style.SUCCESS("Onboarding seed complete."))
