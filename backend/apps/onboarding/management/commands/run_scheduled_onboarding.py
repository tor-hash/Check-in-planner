"""Management command: run the attach automation for onboarding flows that
have reached their planned date.

Intended to be called by a daily Render Cron Job / Cloud Scheduler job (see
render.yaml / cloudbuild.yaml — mirrors the existing run_auto_bookings /
sync_meeting_statuses cron jobs). Idempotent: an assignment is only ever
processed once — see OnboardingAssignment.scheduled_automation_ran_at.

Usage
-----
    python manage.py run_scheduled_onboarding
    python manage.py run_scheduled_onboarding --dry-run   # list only, no side effects
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Run the welcome-email/calendar-booking/Slack-invite automation for "
        "every onboarding assignment whose planned date (scheduled_for) has "
        "arrived and hasn't been run yet."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="List what would run without actually sending anything.",
        )

    def handle(self, *args, **options):
        from apps.onboarding.automation import run_onboarding_attach_automation
        from apps.onboarding.models import OnboardingAssignment

        dry_run: bool = options["dry_run"]
        today = timezone.localdate()

        due = (
            OnboardingAssignment.objects.select_related("profile__user", "flow", "assigned_by")
            .filter(
                scheduled_for__lte=today,
                scheduled_automation_ran_at__isnull=True,
                assigned_by__isnull=False,
            )
            .order_by("scheduled_for")
        )

        count = due.count()
        if count == 0:
            self.stdout.write("No due onboarding assignments to process.")
            return

        self.stdout.write(f"{count} due onboarding assignment(s) found.")

        processed = 0
        skipped = 0
        for assignment in due:
            profile = assignment.profile
            person = getattr(profile, "planner_person", None)
            if person is None:
                self.stderr.write(
                    self.style.WARNING(
                        f"  skip {profile.erp_employee_id}: no linked planner Person "
                        "(cannot resolve recipient/organizer)."
                    )
                )
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f"  would run: {person.name} ({profile.erp_employee_id}) — "
                    f"flow '{assignment.flow.slug}', scheduled_for={assignment.scheduled_for}"
                )
                continue

            self.stdout.write(f"  running: {person.name} ({profile.erp_employee_id}) …")
            result = run_onboarding_attach_automation(
                person=person, assignment=assignment, requested_by=assignment.assigned_by
            )
            processed += 1

            we = result.get("welcomeEmail") or {}
            si = result.get("slackInvite") or {}
            mt = result.get("meetings") or {}
            self.stdout.write(
                "    welcome email: "
                + ("sent" if we.get("sent") else f"FAILED ({we.get('error', '?')})")
            )
            self.stdout.write(
                "    slack invite: "
                + (
                    "sent"
                    if si.get("sent")
                    else f"skipped/failed ({si.get('reason') or si.get('error') or '?'})"
                )
            )
            booked = len(mt.get("booked", [])) if mt else 0
            failed = len(mt.get("failed", [])) if mt else 0
            self.stdout.write(f"    meetings: {booked} booked, {failed} failed")

        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"Dry run complete — {count} assignment(s) would run."))
        else:
            self.stdout.write(
                self.style.SUCCESS(f"Done — {processed} processed, {skipped} skipped.")
            )
