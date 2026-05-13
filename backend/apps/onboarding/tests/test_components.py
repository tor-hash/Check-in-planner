"""Tests for apps.onboarding.components validators."""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.onboarding.components import COMPONENTS, get_component


class GetComponentTests(TestCase):
    def test_known_type(self):
        self.assertIs(get_component("checkbox"), COMPONENTS["checkbox"])

    def test_unknown_type_raises(self):
        with self.assertRaises(ValidationError):
            get_component("definitely-not-a-thing")


class InfoLinkTests(TestCase):
    def setUp(self):
        self.cls = COMPONENTS["info_link"]

    def test_default_config_is_valid(self):
        self.cls.validate_config(self.cls.default_config())

    def test_url_required(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config({"body": "hi"})

    def test_url_must_be_http(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config({"url": "javascript:alert(1)"})

    def test_completion_accepts_empty(self):
        self.cls.validate_completion({})

    def test_completion_read_at_must_be_string(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_completion({"read_at": 42})


class CheckboxTests(TestCase):
    def setUp(self):
        self.cls = COMPONENTS["checkbox"]

    def test_label_required(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config({})

    def test_completion_requires_checked_bool(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_completion({})
        with self.assertRaises(ValidationError):
            self.cls.validate_completion({"checked": "yes"})
        self.cls.validate_completion({"checked": True})


class FormTests(TestCase):
    def setUp(self):
        self.cls = COMPONENTS["form"]

    def test_at_least_one_field(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config({"fields": []})

    def test_field_name_validated(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config(
                {"fields": [{"name": "bad name!", "label": "x", "type": "text"}]}
            )

    def test_unknown_field_type_rejected(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config(
                {"fields": [{"name": "x", "label": "x", "type": "magic"}]}
            )

    def test_duplicate_field_names_rejected(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config(
                {
                    "fields": [
                        {"name": "a", "label": "A", "type": "text"},
                        {"name": "a", "label": "A2", "type": "text"},
                    ]
                }
            )

    def test_completion_requires_values_dict(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_completion({})
        with self.assertRaises(ValidationError):
            self.cls.validate_completion({"values": "x"})
        self.cls.validate_completion({"values": {"a": 1}})


class CalendarMeetingTests(TestCase):
    def setUp(self):
        self.cls = COMPONENTS["calendar_meeting"]

    def test_default_config_is_valid(self):
        self.cls.validate_config(self.cls.default_config())

    def test_with_email_required(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config({"duration_minutes": 30})

    def test_duration_bounds(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_config({"with_email": "a@b.c", "duration_minutes": 2})
        with self.assertRaises(ValidationError):
            self.cls.validate_config({"with_email": "a@b.c", "duration_minutes": 999})

    def test_completion_requires_scheduled_at(self):
        with self.assertRaises(ValidationError):
            self.cls.validate_completion({})
        self.cls.validate_completion({"scheduled_at": "2026-06-01T10:00:00+00:00"})
