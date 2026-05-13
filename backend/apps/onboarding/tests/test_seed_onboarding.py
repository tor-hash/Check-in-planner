"""Smoke test for the seed_onboarding management command."""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.onboarding.models import FlowStep, OnboardingFlow


class SeedOnboardingTests(TestCase):
    def test_creates_default_flow_with_steps(self):
        call_command("seed_onboarding", stdout=StringIO())
        flow = OnboardingFlow.objects.get(slug="default")
        self.assertTrue(flow.is_default)
        self.assertEqual(FlowStep.objects.filter(flow=flow).count(), 4)

    def test_idempotent(self):
        call_command("seed_onboarding", stdout=StringIO())
        call_command("seed_onboarding", stdout=StringIO())
        self.assertEqual(OnboardingFlow.objects.filter(slug="default").count(), 1)
        self.assertEqual(FlowStep.objects.filter(flow__slug="default").count(), 4)
