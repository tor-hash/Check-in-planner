"""Seed the default onboarding flow.

Idempotent: looks up the flow by slug. New steps are appended; existing
steps are updated in place by ``order`` so re-running won't multiply them.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.onboarding.seed_baseline import DEFAULT_FLOW_SLUG, ensure_default_flow


class Command(BaseCommand):
    help = "Create or update the default onboarding flow."

    def add_arguments(self, parser):
        parser.add_argument(
            "--slug",
            default=DEFAULT_FLOW_SLUG,
            help=f"Flow slug to seed (default: {DEFAULT_FLOW_SLUG}).",
        )

    def handle(self, *args, **options):
        slug = options["slug"]
        flow, created = ensure_default_flow(slug=slug)
        self.stdout.write(
            self.style.SUCCESS(f"{'Created' if created else 'Updated'} flow '{slug}'.")
        )
        for step in flow.steps.order_by("order"):
            self.stdout.write(f"  Step #{step.order}: {step.title}")
        self.stdout.write(self.style.SUCCESS("Onboarding seed complete."))
