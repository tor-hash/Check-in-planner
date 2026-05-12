"""Tests for the invitations UI under /accounts/invites/."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Invitation


@override_settings(
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS=["blackcapitaltechnology.com"],
)
class InvitationViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="alice",
            email="alice@blackcapitaltechnology.com",
            password="x",
        )
        self.other = User.objects.create_user(
            username="bob",
            email="bob@blackcapitaltechnology.com",
            password="x",
        )

    def test_login_required(self):
        response = self.client.get(reverse("account-invitations"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_get_lists_pending(self):
        Invitation.objects.create(
            email="newhire@blackcapitaltechnology.com", invited_by=self.other
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("account-invitations"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "newhire@blackcapitaltechnology.com")

    def test_create_invitation(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account-invitations"),
            {"email": "newhire@blackcapitaltechnology.com"},
        )
        self.assertEqual(response.status_code, 302)
        inv = Invitation.objects.get(email="newhire@blackcapitaltechnology.com")
        self.assertEqual(inv.invited_by, self.user)
        self.assertIsNone(inv.accepted_at)

    def test_email_normalised_to_lowercase(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("account-invitations"),
            {"email": "  NewHire@BlackCapitalTechnology.com  "},
        )
        self.assertTrue(
            Invitation.objects.filter(email="newhire@blackcapitaltechnology.com").exists()
        )

    def test_rejects_wrong_domain(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("account-invitations"),
            {"email": "stranger@gmail.com"},
        )
        self.assertFalse(Invitation.objects.filter(email="stranger@gmail.com").exists())

    def test_rejects_self_invite(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("account-invitations"),
            {"email": self.user.email},
        )
        self.assertFalse(Invitation.objects.filter(email=self.user.email).exists())

    def test_rejects_existing_user(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("account-invitations"),
            {"email": self.other.email},
        )
        self.assertFalse(Invitation.objects.filter(email=self.other.email).exists())

    def test_rejects_duplicate_pending(self):
        Invitation.objects.create(
            email="newhire@blackcapitaltechnology.com", invited_by=self.other
        )
        self.client.force_login(self.user)
        self.client.post(
            reverse("account-invitations"),
            {"email": "newhire@blackcapitaltechnology.com"},
        )
        self.assertEqual(
            Invitation.objects.filter(email="newhire@blackcapitaltechnology.com").count(),
            1,
        )

    def test_rejects_invalid_email(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("account-invitations"),
            {"email": "not-an-email"},
        )
        self.assertEqual(Invitation.objects.count(), 0)


@override_settings(
    SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS=["blackcapitaltechnology.com"],
)
class InvitationRevokeTests(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.alice = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        self.bob = User.objects.create_user(
            username="bob", email="bob@blackcapitaltechnology.com", password="x"
        )
        self.staff = User.objects.create_user(
            username="staff",
            email="staff@blackcapitaltechnology.com",
            password="x",
            is_staff=True,
        )
        self.invitation = Invitation.objects.create(
            email="newhire@blackcapitaltechnology.com",
            invited_by=self.alice,
        )

    def test_inviter_can_revoke(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("account-invitation-revoke", args=[self.invitation.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Invitation.objects.filter(pk=self.invitation.pk).exists())

    def test_other_user_cannot_revoke(self):
        self.client.force_login(self.bob)
        self.client.post(
            reverse("account-invitation-revoke", args=[self.invitation.pk])
        )
        self.assertTrue(Invitation.objects.filter(pk=self.invitation.pk).exists())

    def test_staff_can_revoke_any(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("account-invitation-revoke", args=[self.invitation.pk])
        )
        self.assertFalse(Invitation.objects.filter(pk=self.invitation.pk).exists())

    def test_accepted_invitations_404(self):
        from django.utils import timezone

        self.invitation.accepted_at = timezone.now()
        self.invitation.save(update_fields=["accepted_at"])
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("account-invitation-revoke", args=[self.invitation.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Invitation.objects.filter(pk=self.invitation.pk).exists())

    def test_get_not_allowed(self):
        self.client.force_login(self.alice)
        response = self.client.get(
            reverse("account-invitation-revoke", args=[self.invitation.pk])
        )
        self.assertEqual(response.status_code, 405)
