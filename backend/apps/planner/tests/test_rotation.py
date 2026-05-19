"""Tests for the rotation engine in apps.planner.services.rotation."""
from __future__ import annotations

from datetime import UTC, date, datetime

from django.test import TestCase

from apps.planner.models import RotationSession
from apps.planner.services import rotation
from apps.planner.tests.factories import (
    ManagerFactory,
    PersonFactory,
    TeamMembershipFactory,
    ensure_planner_config,
)


class CycleGenerationTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.mgr_a = ManagerFactory(legacy_id="a")
        self.mgr_b = ManagerFactory(legacy_id="b")
        self.mgr_c = ManagerFactory(legacy_id="c")

    def test_generate_cycle_creates_nine_rows(self):
        sessions = rotation.generate_cycle()
        self.assertEqual(len(sessions), 9)
        self.assertEqual(RotationSession.objects.count(), 9)

    def test_each_manager_meets_each_team_once(self):
        rotation.generate_cycle()
        for manager in (self.mgr_a, self.mgr_b, self.mgr_c):
            teams = set(
                RotationSession.objects.filter(manager=manager).values_list("team", flat=True)
            )
            self.assertEqual(teams, {"team-1", "team-2", "team-3"})

    def test_each_session_team_pair_unique(self):
        rotation.generate_cycle()
        seen = set()
        for s in RotationSession.objects.all():
            key = (s.session_index, s.team)
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_generate_is_idempotent(self):
        rotation.generate_cycle()
        first_ids = sorted(RotationSession.objects.values_list("id", flat=True))
        rotation.generate_cycle()
        self.assertEqual(
            sorted(RotationSession.objects.values_list("id", flat=True)),
            first_ids,
        )

    def test_requires_three_managers(self):
        ManagerFactory._meta.model.objects.exclude(legacy_id="a").delete()
        with self.assertRaises(rotation.RotationError):
            rotation.generate_cycle()


class SessionWindowTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))

    def test_session_index_advances_biweekly(self):
        # Cycle base: Mon 2026-01-05.
        # Session 0 = weeks 1-2, session 1 = weeks 3-4, session 2 = weeks 5-6.
        s0 = rotation.session_window_for(date(2026, 1, 12))
        s1 = rotation.session_window_for(date(2026, 1, 19))
        s2 = rotation.session_window_for(date(2026, 2, 9))
        self.assertEqual(s0.session_index, 0)
        self.assertEqual(s1.session_index, 1)
        self.assertEqual(s2.session_index, 2)

    def test_cycle_advances_after_six_weeks(self):
        first = rotation.session_window_for(date(2026, 1, 5))
        second = rotation.session_window_for(date(2026, 2, 16))  # 6 weeks later
        self.assertEqual(first.cycle_start, date(2026, 1, 5))
        self.assertEqual(second.cycle_start, date(2026, 2, 16))

    def test_upcoming_returns_n_unique_windows(self):
        windows = rotation.upcoming_session_windows(4, from_date=date(2026, 1, 5))
        self.assertEqual(len(windows), 4)
        keys = {(w.cycle_start, w.session_index) for w in windows}
        self.assertEqual(len(keys), 4)

    def test_four_week_sessions_span_four_iso_weeks(self):
        cfg = ensure_planner_config(date(2026, 1, 5))
        cfg.weeks_per_session = 4
        cfg.save()
        window = rotation.session_window_for(date(2026, 1, 12))
        self.assertEqual((window.week_end - window.week_start).days, 27)


class BookingValidationTests(TestCase):
    def setUp(self):
        ensure_planner_config(date(2026, 1, 5))
        self.mgr_a = ManagerFactory(legacy_id="a")
        self.mgr_b = ManagerFactory(legacy_id="b")
        self.mgr_c = ManagerFactory(legacy_id="c")
        self.person_t1 = PersonFactory(legacy_id="alice", email="alice@example.com")
        TeamMembershipFactory(team="team-1", person=self.person_t1)
        self.person_pool = PersonFactory(legacy_id="pia")
        TeamMembershipFactory(team="pool", person=self.person_pool)

    def _aware(self, when: datetime) -> datetime:
        return when.replace(tzinfo=UTC)

    def test_pool_member_can_be_booked_by_any_manager(self):
        outcome = rotation.validate_booking(
            manager=self.mgr_a,
            person=self.person_pool,
            when=self._aware(datetime(2026, 1, 12, 10, 0)),
        )
        self.assertTrue(outcome.ok)

    def test_team_member_only_bookable_by_assigned_manager(self):
        rotation.generate_cycle()
        # Find which manager owns team-1 in session 0.
        session = RotationSession.objects.get(
            cycle_start=date(2026, 1, 5), session_index=0, team="team-1"
        )
        owner = session.manager
        non_owner = next(
            m for m in (self.mgr_a, self.mgr_b, self.mgr_c) if m.id != owner.id
        )

        ok = rotation.validate_booking(
            manager=owner,
            person=self.person_t1,
            when=self._aware(datetime(2026, 1, 12, 10, 0)),
        )
        rejected = rotation.validate_booking(
            manager=non_owner,
            person=self.person_t1,
            when=self._aware(datetime(2026, 1, 12, 10, 0)),
        )
        self.assertTrue(ok.ok)
        self.assertFalse(rejected.ok)
        self.assertIn("team-1", rejected.reason)

    def test_validation_auto_generates_missing_session(self):
        # No sessions in DB yet.
        self.assertEqual(RotationSession.objects.count(), 0)
        outcome = rotation.validate_booking(
            manager=self.mgr_a,
            person=self.person_t1,
            when=self._aware(datetime(2026, 1, 12, 10, 0)),
        )
        # Whether or not mgr_a is the owner, the cycle must have been
        # materialised on demand.
        self.assertEqual(RotationSession.objects.count(), 9)
        self.assertIsNotNone(outcome.session)
