from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Feedback


class FeedbackViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("a", email="a@example.com", password="x")
        self.client.force_login(self.user)

    def test_list_renders(self):
        Feedback.objects.create(title="Hello", description="World", created_by=self.user)
        resp = self.client.get(reverse("feedback:list"))
        self.assertContains(resp, "Hello")

    def test_create_sets_author(self):
        resp = self.client.post(reverse("feedback:create"), {"title": "T", "description": "D"})
        self.assertRedirects(resp, reverse("feedback:list"))
        self.assertEqual(Feedback.objects.get().created_by, self.user)

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse("feedback:list"))
        self.assertEqual(resp.status_code, 302)


class FeedbackPermissionTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group

        User = get_user_model()
        self.owner = User.objects.create_user("owner", email="o@example.com")
        self.other = User.objects.create_user("other", email="x@example.com")
        self.admin = User.objects.create_user("admin", email="ad@example.com")
        self.admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        self.item = Feedback.objects.create(title="T", description="D", created_by=self.owner)
        self.edit_url = reverse("feedback:edit", args=[self.item.pk])
        self.delete_url = reverse("feedback:delete", args=[self.item.pk])

    def _edit(self, user):
        self.client.force_login(user)
        return self.client.post(self.edit_url, {"title": "New", "description": "D"})

    def test_owner_can_edit(self):
        self.assertEqual(self._edit(self.owner).status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "New")

    def test_other_cannot_edit(self):
        self.assertEqual(self._edit(self.other).status_code, 403)

    def test_admin_can_edit(self):
        self.assertEqual(self._edit(self.admin).status_code, 302)

    def test_owner_can_delete(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.delete_url).status_code, 302)
        self.assertFalse(Feedback.objects.exists())

    def test_other_cannot_delete(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.delete_url).status_code, 403)
        self.assertTrue(Feedback.objects.exists())

    def test_admin_can_delete(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.delete_url).status_code, 302)
        self.assertFalse(Feedback.objects.exists())

    def test_buttons_shown_by_permission(self):
        self.client.force_login(self.other)
        resp = self.client.get(reverse("feedback:list"))
        self.assertNotContains(resp, self.edit_url)
        self.assertNotContains(resp, self.delete_url)
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("feedback:list"))
        self.assertContains(resp, self.edit_url)
        self.assertContains(resp, self.delete_url)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("feedback:list"))
        self.assertContains(resp, self.delete_url)
