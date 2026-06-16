"""Management command: sync Google Calendar RSVP statuses for scheduled meetings.

Intended to be called every 4 hours by a Render Cron Job.

Usage
-----
    python manage.py sync_meeting_statuses
    python manage.py sync_meeting_statuses --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Poll Google Calendar to detect declined meetings and send notifications."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would change without modifying the database.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]

        from apps.planner.services.decline_sync import sync_meeting_statuses

        self.stdout.write(
            self.style.NOTICE(
                f"{'[dry-run] ' if dry_run else ''}Syncing meeting RSVP statuses…"
            )
        )

        summary = sync_meeting_statuses(dry_run=dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done.  checked={summary['checked']}  "
                f"declined={summary['declined']}  "
                f"already_done={summary['already_done']}  "
                f"no_event_id={summary['no_event_id']}  "
                f"no_user={summary['no_user']}  "
                f"error={summary['error']}"
            )
        )
