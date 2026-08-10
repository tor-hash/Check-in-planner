"""Management command: add Google Meet links to already-booked check-ins.

One-off / re-runnable maintenance command for meetings that were booked
before conference data was requested at event-creation time. Never touches
meeting times, attendees, or status -- only patches the underlying Google
Calendar event's conferenceData.

Usage
-----
    python manage.py backfill_meet_links
    python manage.py backfill_meet_links --dry-run
    python manage.py backfill_meet_links --notify-attendees
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Add Google Meet links to already-booked check-ins that don't have one yet."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would be patched without calling Google or writing to the DB.",
        )
        parser.add_argument(
            "--notify-attendees",
            action="store_true",
            default=False,
            help=(
                "Send attendees a calendar update notification about the patched event "
                "(default: silent, since only the Meet link is being added)."
            ),
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        send_updates = "all" if options["notify_attendees"] else "none"

        from apps.planner.services.meet_backfill import backfill_meet_links

        self.stdout.write(
            self.style.NOTICE(
                f"{'[dry-run] ' if dry_run else ''}Backfilling Google Meet links "
                f"onto existing check-ins…"
            )
        )

        summary = backfill_meet_links(dry_run=dry_run, send_updates=send_updates)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done.  updated={summary['updated']}  "
                f"already_has_link={summary['already_has_link']}  "
                f"skipped_no_event_id={summary['skipped_no_event_id']}  "
                f"skipped_no_user={summary['skipped_no_user']}  "
                f"not_resolved={summary['not_resolved']}  "
                f"error={summary['error']}"
            )
        )
        if summary["skipped_no_user"] > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠  {summary['skipped_no_user']} meeting(s) skipped because the "
                    f"manager has no linked Google account."
                )
            )
        if summary["error"] > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠  {summary['error']} meeting(s) failed -- check logs for detail. "
                    f"Safe to re-run this command; it only touches meetings still missing a link."
                )
            )
