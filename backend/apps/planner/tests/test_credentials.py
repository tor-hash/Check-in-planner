"""Tests for Google credential scope handling."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.planner.google.credentials import (
    _granted_scopes_from_extra,
    credentials_for_user,
)


class GrantedScopesTests(TestCase):
    def test_parses_space_separated_scope_string(self):
        extra = {
            "scope": (
                "openid email profile "
                "https://www.googleapis.com/auth/calendar.freebusy "
                "https://www.googleapis.com/auth/calendar.events"
            )
        }
        scopes = _granted_scopes_from_extra(extra)
        self.assertIn("openid", scopes)
        self.assertIn("https://www.googleapis.com/auth/calendar.freebusy", scopes)

    def test_returns_none_when_scope_missing(self):
        self.assertIsNone(_granted_scopes_from_extra({}))


class CredentialsForUserTests(TestCase):
    @patch("apps.planner.google.credentials._social_auth_for_user")
    @patch("google.oauth2.credentials.Credentials")
    def test_uses_granted_scopes_not_settings_list(self, mock_credentials, mock_social):
        mock_social.return_value = MagicMock(
            extra_data={
                "refresh_token": "rt-1",
                "access_token": "at-1",
                "scope": "openid https://www.googleapis.com/auth/calendar.freebusy",
            }
        )
        user = MagicMock(is_authenticated=True)
        credentials_for_user(user)
        kwargs = mock_credentials.call_args.kwargs
        self.assertEqual(
            kwargs["scopes"],
            ["openid", "https://www.googleapis.com/auth/calendar.freebusy"],
        )
        self.assertNotIn("https://www.googleapis.com/auth/gmail.send", kwargs["scopes"])

    @patch("apps.planner.google.credentials._social_auth_for_user")
    @patch("google.oauth2.credentials.Credentials")
    def test_omits_scopes_when_not_stored(self, mock_credentials, mock_social):
        mock_social.return_value = MagicMock(
            extra_data={"refresh_token": "rt-1", "access_token": "at-1"}
        )
        user = MagicMock(is_authenticated=True)
        credentials_for_user(user)
        kwargs = mock_credentials.call_args.kwargs
        self.assertNotIn("scopes", kwargs)
