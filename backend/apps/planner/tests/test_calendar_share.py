"""Tests for calendar share request workflow (Gmail mocked)."""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.utils import timezone

from apps.planner.models import CalendarShareRequest
from apps.planner.services import calendar_share
from apps.planner.tests.factories import PersonFactory, UserFactory


class CalendarShareServiceTests(TestCase):
    def setUp(self):
        self.manager = UserFactory(manager_role=True)
        self.person = PersonFactory(legacy_id="alice", email="alice@example.com")

    @patch("apps.planner.services.calendar_share.send_calendar_share_email")
    def test_send_share_request_creates_success_record(self, mock_send):
        record = calendar_share.send_share_request(
            person=self.person,
            requested_by=self.manager,
        )
        mock_send.assert_called_once()
        self.assertTrue(record.success)
        self.assertEqual(CalendarShareRequest.objects.count(), 1)

    @patch("apps.planner.services.calendar_share.send_calendar_share_email")
    def test_cooldown_skips_recent_success(self, mock_send):
        CalendarShareRequest.objects.create(
            person=self.person,
            requested_by=self.manager,
            sent_at=timezone.now(),
            success=True,
        )
        allowed, reason = calendar_share.can_send_share_request(
            person=self.person,
            requested_by=self.manager,
            force=False,
        )
        self.assertFalse(allowed)
        self.assertIn("7 days", reason or "")
        summary = calendar_share.send_share_requests(
            person_ids=["alice"],
            requested_by=self.manager,
            force=False,
        )
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["sent"], 0)
        mock_send.assert_not_called()

    @patch("apps.planner.services.calendar_share.send_calendar_share_email")
    def test_force_bypasses_cooldown(self, mock_send):
        CalendarShareRequest.objects.create(
            person=self.person,
            requested_by=self.manager,
            sent_at=timezone.now(),
            success=True,
        )
        summary = calendar_share.send_share_requests(
            person_ids=["alice"],
            requested_by=self.manager,
            force=True,
        )
        self.assertEqual(summary["sent"], 1)
        mock_send.assert_called_once()

    @patch("apps.planner.services.calendar_share.send_calendar_share_email")
    def test_old_success_allows_resend(self, mock_send):
        CalendarShareRequest.objects.create(
            person=self.person,
            requested_by=self.manager,
            sent_at=timezone.now() - timedelta(days=8),
            success=True,
        )
        summary = calendar_share.send_share_requests(
            person_ids=["alice"],
            requested_by=self.manager,
            force=False,
        )
        self.assertEqual(summary["sent"], 1)
        mock_send.assert_called_once()


class CalendarShareApiTests(TestCase):
    def setUp(self):
        self.person = PersonFactory(legacy_id="bob", email="bob@example.com")
        self.user = UserFactory(manager_role=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_post_requires_manager(self):
        plain = UserFactory()
        self.client.force_login(plain)
        response = self.client.post(
            "/api/calendar-share-requests",
            data=json.dumps({"person_ids": ["bob"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_post_validates_payload(self):
        response = self.client.post(
            "/api/calendar-share-requests",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    @patch("apps.planner.services.calendar_share.send_calendar_share_email")
    def test_post_sends_email(self, mock_send):
        response = self.client.post(
            "/api/calendar-share-requests",
            data=json.dumps({"person_ids": ["bob"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["sent"], 1)
        mock_send.assert_called_once()

    @patch("apps.planner.services.calendar_share.send_calendar_share_email")
    def test_get_share_status(self, _mock_send):
        response = self.client.get("/api/calendar-share-requests?person_ids=bob")
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["person_id"], "bob")
        self.assertTrue(results[0]["can_send"])
