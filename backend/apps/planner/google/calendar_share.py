"""Ask employees to share Google Calendar free/busy with their manager.

``_send_gmail`` is the shared low-level plumbing (MIME + Gmail API send)
used both by the standalone calendar-share-request feature in this module
and by the onboarding app's combined welcome email
(``apps.onboarding.welcome_email``) — factored out so neither has to
duplicate the OAuth/MIME handling.
"""
from __future__ import annotations

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .credentials import GoogleCredentialsUnavailable, credentials_for_user

logger = logging.getLogger(__name__)

SHARE_HELP_URL = "https://support.google.com/calendar/answer/37082"


def _send_gmail(
    *,
    from_user,
    to_email: str,
    subject: str,
    plain_text: str,
    html: str | None = None,
) -> None:
    """Send an email from ``from_user``'s Gmail account.

    Sends ``plain_text`` only unless ``html`` is given, in which case a
    ``multipart/alternative`` message is sent with both parts. Raises
    ``GoogleCredentialsUnavailable`` if ``from_user`` hasn't connected
    Google, ``ValueError`` for a missing recipient address, or whatever the
    Gmail API raises on send failure.
    """
    from_email = (getattr(from_user, "email", None) or "").strip()
    if not from_email:
        raise GoogleCredentialsUnavailable("Sender has no email on file.")
    to_email = to_email.strip()
    if not to_email:
        raise ValueError("Recipient has no email address.")

    if html:
        message = MIMEMultipart("alternative")
        message.attach(MIMEText(plain_text, "plain", "utf-8"))
        message.attach(MIMEText(html, "html", "utf-8"))
    else:
        message = MIMEText(plain_text, "plain", "utf-8")
    message["to"] = to_email
    message["from"] = from_email
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
        logger.exception("Gmail send failed from=%s to=%s", from_email, to_email)
        raise


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

    subject, plain, _html = build_share_email_bodies(
        employee_name=employee_name,
        manager_name=manager_name or manager_email,
        manager_email=manager_email,
    )

    # Plain-text only, matching this feature's existing behaviour (the
    # html body above is built for parity/tests but intentionally unused
    # here) — unrelated to the onboarding welcome email, which does send
    # a multipart/html message via the same _send_gmail helper.
    _send_gmail(from_user=from_user, to_email=to_email, subject=subject, plain_text=plain)
