"""Google Calendar FreeBusy v3 wrapper.

Returns busy intervals for one or more attendee emails as plain dicts so the
caller doesn't have to depend on google-api-python-client types.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .credentials import credentials_for_user

logger = logging.getLogger(__name__)


# Google's FreeBusy.items list cap is 50 calendars per request.
_MAX_ITEMS_PER_REQUEST = 50


@dataclass
class BusyInterval:
    start: datetime
    end: datetime

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


def _build_calendar_service(user):
    from googleapiclient.discovery import build  # local import - heavy

    creds = credentials_for_user(user)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _chunked(items: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def query_freebusy(
    *,
    requesting_user,
    emails: list[str],
    time_min: datetime,
    time_max: datetime,
    timezone: str = "Europe/Copenhagen",
) -> dict[str, list[BusyInterval]]:
    """Return ``{email: [BusyInterval, ...]}`` for the supplied window.

    Calls the Google Calendar FreeBusy API once per 50-email chunk using the
    requesting manager's credentials. Emails that the manager cannot read
    return an empty list (Google reports them as ``errors`` per calendar).
    """
    if not emails:
        return {}
    if time_min.tzinfo is None:
        time_min = time_min.replace(tzinfo=UTC)
    if time_max.tzinfo is None:
        time_max = time_max.replace(tzinfo=UTC)
    if time_max <= time_min:
        raise ValueError("time_max must be greater than time_min.")

    unique_emails = list(dict.fromkeys(e for e in emails if e))
    service = _build_calendar_service(requesting_user)
    out: dict[str, list[BusyInterval]] = {email: [] for email in unique_emails}

    for chunk in _chunked(unique_emails, _MAX_ITEMS_PER_REQUEST):
        body = {
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "timeZone": timezone,
            "items": [{"id": email} for email in chunk],
        }
        try:
            response = service.freebusy().query(body=body).execute()
        except Exception:
            logger.exception("Calendar freeBusy.query failed (chunk size=%d)", len(chunk))
            raise
        calendars = response.get("calendars", {})
        for email in chunk:
            entry = calendars.get(email, {})
            for block in entry.get("busy", []) or []:
                start = _parse_iso(block.get("start"))
                end = _parse_iso(block.get("end"))
                if start and end:
                    out[email].append(BusyInterval(start=start, end=end))
    return out


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        candidate = value[:-1] + "+00:00" if isinstance(value, str) and value.endswith("Z") else value
        return datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        logger.warning("Could not parse ISO timestamp from FreeBusy: %r", value)
        return None
