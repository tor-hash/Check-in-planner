"""Ask employees to share Google Calendar free/busy with their manager."""
from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

from .credentials import GoogleCredentialsUnavailable, credentials_for_user

logger = logging.getLogger(__name__)

SHARE_HELP_URL = "https://support.google.com/calendar/answer/37082"


def build_share_email_bodies(
    *,
    employee_name: str,
    manager_name: str,
    manager_email: str,
) -> tuple[str, str, str]:
    """Return (subject, plain_text, html)."""
    greeting = employee_name.strip() or "there"
    manager_label = manager_name.strip() or manager_email
    subject = f"Del din kalender med {manager_label} — check-in planlægning"
    plain = f"""Hej {greeting},

{manager_label} ({manager_email}) bruger BCT Check-in Planner til at booke 1:1 check-ins.
For at finde ledige tider skal din Google Kalender deles med {manager_email}.

Sådan gør du:
1. Åbn Google Kalender: https://calendar.google.com/
2. Find din primære kalender i venstre side → ⋮ → Indstillinger og deling
3. Under "Del med bestemte personer" → Tilføj person → {manager_email}
4. Vælg tilladelsen "Se kun ledig/optaget (skjul detaljer)" / "See only free/busy"

Guide: {SHARE_HELP_URL}

Tak — du behøver kun gøre dette én gang.

— BCT Check-in Planner (sendt på vegne af {manager_label})
"""
    html = f"""<p>Hej {greeting},</p>
<p><strong>{manager_label}</strong> ({manager_email}) bruger <em>BCT Check-in Planner</em> til at booke 1:1 check-ins.
For at finde ledige tider skal din Google Kalender deles med <strong>{manager_email}</strong>.</p>
<ol>
  <li>Åbn <a href="https://calendar.google.com/">Google Kalender</a></li>
  <li>Find din primære kalender → ⋮ → <em>Indstillinger og deling</em></li>
  <li><em>Del med bestemte personer</em> → Tilføj <strong>{manager_email}</strong></li>
  <li>Vælg <strong>Se kun ledig/optaget (skjul detaljer)</strong></li>
</ol>
<p><a href="{SHARE_HELP_URL}">Googles vejledning til kalenderdeling</a></p>
<p>Tak — du behøver kun gøre dette én gang.</p>
<p style="color:#666;font-size:12px;">Sendt via BCT Check-in Planner på vegne af {manager_label}</p>
"""
    return subject, plain, html


def send_calendar_share_email(
    *,
    from_user,
    to_email: str,
    employee_name: str,
    manager_name: str | None = None,
) -> None:
    """Send a share-request email from the manager's Gmail account."""
    manager_email = (getattr(from_user, "email", None) or "").strip()
    if not manager_email:
        raise GoogleCredentialsUnavailable("Manager has no email on file.")
    to_email = to_email.strip()
    if not to_email:
        raise ValueError("Employee has no email address.")

    subject, plain, _html = build_share_email_bodies(
        employee_name=employee_name,
        manager_name=manager_name or manager_email,
        manager_email=manager_email,
    )

    message = MIMEText(plain, "plain", "utf-8")
    message["to"] = to_email
    message["from"] = manager_email
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise GoogleCredentialsUnavailable("google-api-python-client is not installed.") from exc

    creds = credentials_for_user(from_user)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    try:
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except Exception:
        logger.exception(
            "Gmail send failed from=%s to=%s",
            manager_email,
            to_email,
        )
        raise
