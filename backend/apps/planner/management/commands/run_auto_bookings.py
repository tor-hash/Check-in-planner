"""Management command: auto-book check-in meetings for all eligible managers.

Intended to be called by a monthly Render Cron Job.  Idempotent: existing
non-cancelled bookings for the same (manager, person, window) are skipped.

Usage
-----
    python manage.py run_auto_bookings
    python manage.py run_auto_bookings --windows 3   # book 3 windows ahead
    python manage.py run_auto_bookings --dry-run      # plan only, no DB/Google writes
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Auto-book check-in meetings for all active managers (runs monthly)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--windows",
            type=int,
            default=2,
            metavar="N",
            help="Number of upcoming session windows to book for (default: 2).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Compute the plan without creating any meetings or notifications.",
        )

    def handle(self, *args, **options):
        windows_ahead: int = options["windows"]
        dry_run: bool = options["dry_run"]

        if windows_ahead < 1 or windows_ahead > 12:
            raise CommandError("--windows must be between 1 and 12.")

        from apps.planner.services.auto_booking import run_auto_bookings

        self.stdout.write(
            self.style.NOTICE(
                f"{'[dry-run] ' if dry_run else ''}Running auto-bookings "
                f"({windows_ahead} window(s) ahead)…"
            )
        )

        summary = run_auto_bookings(windows_ahead=windows_ahead, dry_run=dry_run)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done.  booked={summary['booked']}  "
                f"already_exists={summary['already_exists']}  "
                f"no_slot={summary['no_slot']}  "
                f"error={summary['error']}  "
                f"skipped_no_user={summary['skipped_no_user']}"
            )
        )
