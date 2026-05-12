"""Factories for the planner test suite (factory_boy)."""
from __future__ import annotations

from datetime import date

import factory
from django.contrib.auth.models import Group, User

from apps.planner.models import (
    CheckInMeeting,
    JournalEntry,
    ManagerProfile,
    Person,
    PlannerConfig,
    Project,
    RotationSession,
    TeamMembership,
)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user-{n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.username}@blackcapitaltechnology.com")
    password = "testpw"

    @factory.post_generation
    def manager_role(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        group, _ = Group.objects.get_or_create(name="manager")
        self.groups.add(group)


class PersonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Person

    legacy_id = factory.Sequence(lambda n: f"person{n}")
    name = factory.Sequence(lambda n: f"Person {n}")
    email = factory.LazyAttribute(lambda obj: f"{obj.legacy_id}@blackcapitaltechnology.com")


class ManagerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ManagerProfile

    legacy_id = factory.Sequence(lambda n: f"mgr{n}")
    person = factory.SubFactory(PersonFactory)


class ProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Project

    name = factory.Sequence(lambda n: f"Project-{n}")


class TeamMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TeamMembership

    team = "team-1"
    person = factory.SubFactory(PersonFactory)
    sort_order = factory.Sequence(lambda n: n)


class RotationSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RotationSession

    cycle_start = date(2026, 1, 5)
    session_index = 0
    team = "team-1"
    manager = factory.SubFactory(ManagerFactory)


class CheckInMeetingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CheckInMeeting

    manager = factory.SubFactory(ManagerFactory)
    person = factory.SubFactory(PersonFactory)
    starts_at = factory.LazyFunction(
        lambda: factory.Faker("date_time_this_year").evaluate(None, None, {"locale": "en_US"})
    )


class JournalEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = JournalEntry

    entry_id = factory.Sequence(lambda n: f"entry-{n}")
    person = factory.SubFactory(PersonFactory)
    manager = factory.SubFactory(ManagerFactory)
    date = factory.LazyFunction(date.today)


def ensure_planner_config(start: date = date(2026, 1, 5)) -> PlannerConfig:
    cfg = PlannerConfig.singleton()
    cfg.start_date = start
    cfg.save()
    return cfg
