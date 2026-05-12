"""One-shot import of journal entries from the legacy Google Sheet.

Run this once on production after deploying the Django journal endpoints,
before flipping ``USE_GOOGLE_SHEET_JOURNAL=False`` and removing the Sheet
write paths in the frontend.

Behavior:
    - Reads rows from the configured Sheet tab.
    - For each row: if a JournalEntry with that entry_id already exists,
      skip it. Otherwise create it.
    - Resolves person/manager via legacy_id (the Sheet's personId / managerId
      columns).
    - Reports counts at the end. Use --dry-run to inspect first.

Required environment:
    GOOGLE_OAUTH2_KEY, GOOGLE_OAUTH2_SECRET (already required for login)
    JOURNAL_SHEET_ID            spreadsheet id (default: legacy id from frontend)
    JOURNAL_SHEET_TAB           tab name (default: Entries)

The acting user (--user) must have already signed in via Google OAuth so we
can use their refresh_token to read the Sheet. Pass --user <email>.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.planner.models import JournalEntry, ManagerProfile, Person

logger = logging.getLogger(__name__)

DEFAULT_SHEET_ID = "1--rEDjYldyi7F1qRGyZWhj4pi2ADd9tG9BKazjyeZk8"
DEFAULT_SHEET_TAB = "Entries"
EXPECTED_HEADER = [
    "id", "personId", "managerId", "date",
    "trivsel", "faglig", "personlig", "udfordringer", "maal", "noter", "opfolgning",
    "files", "createdAt", "updatedAt", "deletedAt", "obs",
]


class Command(BaseCommand):
    help = "Import legacy Google Sheet journal entries into JournalEntry rows."

    def add_arguments(self, parser):
        parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
        parser.add_argument("--tab", default=DEFAULT_SHEET_TAB)
        parser.add_argument(
            "--user",
            required=True,
            help="Email of a Django user with a connected Google account whose "
                 "refresh_token will be used to read the Sheet.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List rows that would be imported but don't write to the DB.",
        )

    def handle(self, *args, **options):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise CommandError(
                "google-api-python-client is not installed. Run pip install -r requirements.txt"
            ) from exc

        from apps.planner.google.credentials import (
            GoogleCredentialsUnavailable,
            credentials_for_user,
        )

        User = get_user_model()
        user = User.objects.filter(email__iexact=options["user"]).first()
        if not user:
            raise CommandError(f"No Django user with email {options['user']!r}")
        try:
            creds = credentials_for_user(user)
        except GoogleCredentialsUnavailable as exc:
            raise CommandError(str(exc)) from exc

        service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        sheet_id = options["sheet_id"]
        tab = options["tab"]
        rng = f"{tab}!A1:Z"

        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=rng
        ).execute()
        values = result.get("values") or []
        if not values:
            self.stdout.write(self.style.WARNING("Sheet is empty — nothing to import."))
            return

        header = values[0]
        rows = values[1:]
        self.stdout.write(self.style.NOTICE(f"Read {len(rows)} rows from {sheet_id}/{tab}"))

        idx = {name: i for i, name in enumerate(header)}
        for required in ("id", "personId", "date"):
            if required not in idx:
                raise CommandError(f"Sheet header missing required column '{required}'")

        created = skipped = errored = 0
        for row in rows:
            try:
                ok = self._import_row(row, idx, dry_run=options["dry_run"])
                created += int(ok == "created")
                skipped += int(ok == "skipped")
            except Exception as exc:
                errored += 1
                self.stderr.write(self.style.ERROR(f"Row failed: {exc} -- row={row!r}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. created={created} skipped={skipped} errored={errored} "
                f"(dry_run={options['dry_run']})"
            )
        )

    def _import_row(self, row: list[str], idx: dict[str, int], *, dry_run: bool) -> str:
        def cell(name: str) -> str:
            return (row[idx[name]] if name in idx and idx[name] < len(row) else "") or ""

        entry_id = cell("id").strip()
        if not entry_id:
            return "skipped"
        if JournalEntry.objects.filter(entry_id=entry_id).exists():
            return "skipped"

        person = Person.objects.filter(legacy_id=cell("personId").strip()).first()
        if not person:
            self.stderr.write(self.style.WARNING(f"Skipping {entry_id}: person not found"))
            return "skipped"
        manager = ManagerProfile.objects.filter(legacy_id=cell("managerId").strip()).first()

        try:
            files = json.loads(cell("files") or "[]")
            if not isinstance(files, list):
                files = []
        except json.JSONDecodeError:
            files = []

        try:
            entry_date = date.fromisoformat(cell("date").strip())
        except ValueError:
            self.stderr.write(self.style.WARNING(f"Skipping {entry_id}: invalid date"))
            return "skipped"

        if dry_run:
            self.stdout.write(f"[dry] would create entry {entry_id} for {person.legacy_id}")
            return "created"

        JournalEntry.objects.create(
            entry_id=entry_id,
            person=person,
            manager=manager,
            date=entry_date,
            trivsel=cell("trivsel"),
            faglig=cell("faglig"),
            personlig=cell("personlig"),
            udfordringer=cell("udfordringer"),
            maal=cell("maal"),
            noter=cell("noter"),
            opfolgning=cell("opfolgning"),
            obs=cell("obs"),
            files=files,
        )
        return "created"
