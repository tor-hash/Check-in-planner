"""Tests for the per-resource API endpoints introduced in Phase 1.

These complement test_api.py which covers the legacy aggregate state endpoint.
"""
from __future__ import annotations

import json

from django.contrib.auth.models import Group, User
from django.test import Client, TestCase

from apps.planner.models import (
    FunctionTag,
    JournalEntry,
    ManagerProfile,
    Person,
    Project,
    TeamMembership,
)


def _as_manager(user: User) -> User:
    group, _ = Group.objects.get_or_create(name="manager")
    user.groups.add(group)
    return user


class PeopleResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice",
            email="alice@blackcapitaltechnology.com",
            password="x",
        )
        _as_manager(self.user)
        self.client.force_login(self.user)

    def test_create_person(self):
        response = self.client.post(
            "/api/people",
            data=json.dumps({"id": "alice", "name": "Alice Andersen", "email": "alice@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["id"], "alice")
        self.assertEqual(body["name"], "Alice Andersen")
        self.assertEqual(Person.objects.count(), 1)

    def test_create_person_duplicate_id(self):
        Person.objects.create(legacy_id="alice", name="Alice")
        response = self.client.post(
            "/api/people",
            data=json.dumps({"id": "alice", "name": "Alice II"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_create_person_invalid_id(self):
        response = self.client.post(
            "/api/people",
            data=json.dumps({"id": "bad id with spaces", "name": "X"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_update_person(self):
        Person.objects.create(legacy_id="alice", name="Alice")
        response = self.client.put(
            "/api/people/alice",
            data=json.dumps({"name": "Alice Updated", "email": "alice@example.com"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        person = Person.objects.get(legacy_id="alice")
        self.assertEqual(person.name, "Alice Updated")
        self.assertEqual(person.email, "alice@example.com")

    def test_delete_person(self):
        Person.objects.create(legacy_id="alice", name="Alice")
        response = self.client.delete("/api/people/alice")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Person.objects.filter(legacy_id="alice").exists())

    def test_get_collection_unauthenticated(self):
        self.client.logout()
        response = self.client.get("/api/people")
        self.assertEqual(response.status_code, 302)

    def test_get_collection_authenticated_no_manager(self):
        non_mgr = User.objects.create_user(
            username="reader",
            email="reader@blackcapitaltechnology.com",
            password="x",
        )
        self.client.force_login(non_mgr)
        Person.objects.create(legacy_id="alice", name="Alice")
        response = self.client.get("/api/people")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["people"]), 1)

    def test_non_manager_cannot_create(self):
        non_mgr = User.objects.create_user(
            username="reader",
            email="reader@blackcapitaltechnology.com",
            password="x",
        )
        self.client.force_login(non_mgr)
        response = self.client.post(
            "/api/people",
            data=json.dumps({"id": "alice", "name": "Alice"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class ProjectsResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        _as_manager(self.user)
        self.client.force_login(self.user)

    def test_create_project(self):
        response = self.client.post(
            "/api/projects",
            data=json.dumps({"name": "Phoenix", "color": "#6ea8fe"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Project.objects.filter(name="Phoenix").exists())

    def test_create_project_duplicate(self):
        Project.objects.create(name="Phoenix")
        response = self.client.post(
            "/api/projects",
            data=json.dumps({"name": "Phoenix"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_update_project(self):
        Project.objects.create(name="Phoenix")
        response = self.client.put(
            "/api/projects/Phoenix",
            data=json.dumps({"description": "AI workstream", "color": "#ff0"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        proj = Project.objects.get(name="Phoenix")
        self.assertEqual(proj.description, "AI workstream")

    def test_delete_project(self):
        Project.objects.create(name="Phoenix")
        response = self.client.delete("/api/projects/Phoenix")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.filter(name="Phoenix").exists())


class TeamsResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        _as_manager(self.user)
        self.client.force_login(self.user)
        Person.objects.create(legacy_id="alice", name="Alice")
        Person.objects.create(legacy_id="bob", name="Bob")
        Person.objects.create(legacy_id="charlie", name="Charlie")

    def test_replace_team_membership(self):
        response = self.client.put(
            "/api/teams/team-1",
            data=json.dumps({"personIds": ["alice", "bob"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        members = list(
            TeamMembership.objects.filter(team="team-1").order_by("sort_order").values_list(
                "person__legacy_id", flat=True
            )
        )
        self.assertEqual(members, ["alice", "bob"])

    def test_replace_team_does_not_touch_other_teams(self):
        TeamMembership.objects.create(
            team="team-2", person=Person.objects.get(legacy_id="charlie"), sort_order=0
        )
        response = self.client.put(
            "/api/teams/team-1",
            data=json.dumps({"personIds": ["alice"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TeamMembership.objects.filter(team="team-2", person__legacy_id="charlie").exists())

    def test_unknown_team(self):
        response = self.client.put(
            "/api/teams/team-99",
            data=json.dumps({"personIds": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class JournalResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        self.client.force_login(self.user)
        self.person = Person.objects.create(legacy_id="alice", name="Alice")
        self.manager = ManagerProfile.objects.create(legacy_id="tor")

    def test_create_entry(self):
        response = self.client.post(
            "/api/journal-entries",
            data=json.dumps(
                {
                    "id": "entry-1",
                    "personId": "alice",
                    "managerId": "tor",
                    "date": "2026-05-12",
                    "trivsel": "Going great",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(JournalEntry.objects.filter(entry_id="entry-1").exists())

    def test_update_entry(self):
        JournalEntry.objects.create(
            entry_id="entry-1", person=self.person, manager=self.manager, date="2026-05-12"
        )
        response = self.client.put(
            "/api/journal-entries/entry-1",
            data=json.dumps(
                {
                    "personId": "alice",
                    "managerId": "tor",
                    "date": "2026-05-12",
                    "trivsel": "Updated",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        entry = JournalEntry.objects.get(entry_id="entry-1")
        self.assertEqual(entry.trivsel, "Updated")

    def test_update_entry_accepts_numeric_trivsel(self):
        JournalEntry.objects.create(
            entry_id="entry-obs",
            person=self.person,
            manager=self.manager,
            date="2026-05-27",
        )
        response = self.client.put(
            "/api/journal-entries/entry-obs",
            data=json.dumps(
                {
                    "personId": "alice",
                    "managerId": "tor",
                    "date": "2026-05-27",
                    "trivsel": 7,
                    "obs": "TEST",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        entry = JournalEntry.objects.get(entry_id="entry-obs")
        self.assertEqual(entry.trivsel, "7")
        self.assertEqual(entry.obs, "TEST")

    def test_soft_delete_entry(self):
        JournalEntry.objects.create(
            entry_id="entry-1", person=self.person, manager=self.manager, date="2026-05-12"
        )
        response = self.client.delete("/api/journal-entries/entry-1")
        self.assertEqual(response.status_code, 200)
        entry = JournalEntry.objects.get(entry_id="entry-1")
        self.assertIsNotNone(entry.deleted_at)

    def test_filter_by_person(self):
        other = Person.objects.create(legacy_id="bob", name="Bob")
        JournalEntry.objects.create(entry_id="e-1", person=self.person, date="2026-05-12")
        JournalEntry.objects.create(entry_id="e-2", person=other, date="2026-05-12")
        response = self.client.get("/api/journal-entries?personId=alice")
        self.assertEqual(response.status_code, 200)
        ids = [e["id"] for e in response.json()["entries"]]
        self.assertEqual(ids, ["e-1"])

    def test_invalid_person_returns_400(self):
        response = self.client.post(
            "/api/journal-entries",
            data=json.dumps(
                {"id": "e-1", "personId": "ghost", "date": "2026-05-12"}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class FunctionTagsResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        _as_manager(self.user)
        self.client.force_login(self.user)

    def test_create_tag(self):
        response = self.client.post(
            "/api/function-tags",
            data=json.dumps({"label": "ENG", "displayName": "Engineering", "color": "#6ea8fe"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(FunctionTag.objects.filter(display_name="Engineering").exists())

    def test_replace_tags(self):
        FunctionTag.objects.create(label="OLD", display_name="Old Tag", color="#000000")
        response = self.client.put(
            "/api/function-tags",
            data=json.dumps(
                {
                    "fnTags": [
                        {"label": "ENG", "displayName": "Engineering", "color": "#6ea8fe"},
                        {"label": "BD", "displayName": "Business Development", "color": "#f5a97f"},
                    ]
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        names = set(FunctionTag.objects.values_list("display_name", flat=True))
        self.assertEqual(names, {"Engineering", "Business Development"})


class CustomDatesResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        _as_manager(self.user)
        self.client.force_login(self.user)

    def test_put_flat_keys_round_trip(self):
        response = self.client.put(
            "/api/custom-dates",
            data=json.dumps(
                {"customDates": {"tor:0": "2026-05-12T10:00", "alice:1": "2026-05-26T14:30"}}
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["customDates"]["tor:0"], "2026-05-12T10:00")

        get_response = self.client.get("/api/custom-dates")
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["customDates"]["alice:1"], "2026-05-26T14:30")

    def test_put_rejects_nested_values(self):
        response = self.client.put(
            "/api/custom-dates",
            data=json.dumps({"customDates": {"tor": {"0": "2026-05-12T10:00"}}}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class ConfigResourceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        _as_manager(self.user)
        self.client.force_login(self.user)

    def test_get_config(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("startDate", body)
        self.assertIn("workHours", body)
        self.assertIn("weeksPerSession", body)

    def test_update_config(self):
        response = self.client.put(
            "/api/config",
            data=json.dumps(
                {
                    "startDate": "2026-06-01",
                    "workHours": {"start": "08:00", "end": "16:00"},
                    "weekOffset": 2,
                    "weeksPerSession": 4,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["startDate"], "2026-06-01")
        self.assertEqual(body["weekOffset"], 2)
        self.assertEqual(body["weeksPerSession"], 4)


class NonDestructivePersistTests(TestCase):
    """The new persist_state must keep stable IDs across saves so FKs survive."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="alice", email="alice@blackcapitaltechnology.com", password="x"
        )
        _as_manager(self.user)
        self.client.force_login(self.user)

    def _full_state(self) -> dict:
        return {
            "people": [{"id": "alice", "name": "Alice"}, {"id": "bob", "name": "Bob"}],
            "mgrs": ["tor"],
            "teams": {"team-1": ["alice"], "team-2": ["bob"], "team-3": [], "pool": []},
            "startDate": "2026-01-05",
            "customDates": {},
            "workHours": {"start": "09:00", "end": "17:00", "excludeLunch": True, "weekdaysOnly": True},
            "projects": [{"name": "Phoenix"}],
            "journal": {"alice": [{"id": "j1", "date": "2026-01-12"}]},
            "fnTags": [],
        }

    def test_persist_state_preserves_pks(self):
        # First save
        first = self.client.put(
            "/api/state/update",
            data=json.dumps(self._full_state()),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)
        alice_pk = Person.objects.get(legacy_id="alice").pk
        entry_pk = JournalEntry.objects.get(entry_id="j1").pk
        project_pk = Project.objects.get(name="Phoenix").pk

        # Second save with same data
        second = self.client.put(
            "/api/state/update",
            data=json.dumps(self._full_state()),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(Person.objects.get(legacy_id="alice").pk, alice_pk)
        self.assertEqual(JournalEntry.objects.get(entry_id="j1").pk, entry_pk)
        self.assertEqual(Project.objects.get(name="Phoenix").pk, project_pk)

    def test_persist_state_removes_missing_entities(self):
        self.client.put(
            "/api/state/update",
            data=json.dumps(self._full_state()),
            content_type="application/json",
        )
        modified = self._full_state()
        modified["people"] = [{"id": "alice", "name": "Alice"}]  # bob removed
        self.client.put(
            "/api/state/update",
            data=json.dumps(modified),
            content_type="application/json",
        )
        self.assertFalse(Person.objects.filter(legacy_id="bob").exists())
        self.assertTrue(Person.objects.filter(legacy_id="alice").exists())
