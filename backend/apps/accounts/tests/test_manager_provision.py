"""Tests for automatic manager group provisioning on sign-in."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.accounts.models import Invitation
from apps.accounts.pipeline import ensure_manager_provisioned
from apps.planner.models import ManagerProfile, Person
from apps.planner.services.state import ensure_default_roles, upsert_manager, upsert_person


class _FakeBackend:
    name = "google-oauth2"


@override_settings(
    GOOGLE_WORKSPACE_ALLOWED_EMAILS=[
        "tor@blackcapitaltechnology.com",
        "jvo@blackcapitaltechnology.com",
    ]
)
class ManagerProvisionTests(TestCase):
    def setUp(self):
        ensure_default_roles()
        self.user = get_user_model().objects.create_user(
            username="jvo",
            email="jvo@blackcapitaltechnology.com",
        )

    def test_allowlisted_user_gets_manager_group(self):
        ensure_manager_provisioned(
            _FakeBackend(),
            user=self.user,
            details={"email": "jvo@blackcapitaltechnology.com"},
        )
        self.assertTrue(self.user.groups.filter(name="manager").exists())

    def test_invited_user_gets_manager_group(self):
        invited = get_user_model().objects.create_user(
            username="newmgr",
            email="newmgr@blackcapitaltechnology.com",
        )
        inv = Invitation.objects.create(
            email="newmgr@blackcapitaltechnology.com",
            invited_by=self.user,
        )
        inv.mark_accepted()

        ensure_manager_provisioned(
            _FakeBackend(),
            user=invited,
            details={"email": "newmgr@blackcapitaltechnology.com"},
        )
        self.assertTrue(invited.groups.filter(name="manager").exists())

    def test_non_allowlisted_non_invited_user_unchanged(self):
        other = get_user_model().objects.create_user(
            username="other",
            email="other@blackcapitaltechnology.com",
        )
        ensure_manager_provisioned(
            _FakeBackend(),
            user=other,
            details={"email": "other@blackcapitaltechnology.com"},
        )
        self.assertFalse(other.groups.filter(name="manager").exists())

    def test_idempotent_on_repeat_login(self):
        ensure_manager_provisioned(
            _FakeBackend(),
            user=self.user,
            details={"email": "jvo@blackcapitaltechnology.com"},
        )
        ensure_manager_provisioned(
            _FakeBackend(),
            user=self.user,
            details={"email": "jvo@blackcapitaltechnology.com"},
        )
        self.assertEqual(
            self.user.groups.filter(name="manager").count(),
            1,
        )

    def test_links_manager_profile_when_person_email_matches(self):
        upsert_person(
            {
                "id": "jvo",
                "name": "Jonas Vo",
                "email": "jvo@blackcapitaltechnology.com",
                "org": "BCT",
            },
            self.user,
        )
        upsert_manager("jvo", self.user)

        ensure_manager_provisioned(
            _FakeBackend(),
            user=self.user,
            details={"email": "jvo@blackcapitaltechnology.com"},
        )

        profile = ManagerProfile.objects.get(legacy_id="jvo")
        self.assertEqual(profile.user_id, self.user.id)
        self.assertEqual(profile.person.email, "jvo@blackcapitaltechnology.com")
