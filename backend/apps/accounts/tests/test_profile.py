from django.contrib.auth.models import User
from django.test import Client, TestCase


class ProfileTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="profile-user",
            email="profile@blackcapitaltechnology.com",
            password="x",
            first_name="Profile",
            last_name="User",
        )

    def test_profile_requires_login(self):
        response = self.client.get("/accounts/profile/")
        self.assertEqual(response.status_code, 302)

    def test_profile_returns_identity(self):
        self.client.force_login(self.user)
        response = self.client.get("/accounts/profile/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["email"], "profile@blackcapitaltechnology.com")
