"""Combined welcome + calendar-share-request email for a new onboarding flow.

Sent once, automatically, the moment a manager attaches a flow to an
employee. Reuses the low-level Gmail-send plumbing in
``apps.planner.google.calendar_share`` (``_send_gmail``) — the same
mechanism the standalone, non-onboarding calendar-share-request feature
uses — without touching that feature's own email content or behaviour.

This does not resend automatically: ``send_onboarding_welcome_email``
should only be called when ``OnboardingAssignment.welcome_email_sent_at``
is still unset (the caller in ``manage_api.py`` is responsible for that
check, so re-attaching an existing assignment never re-sends it).

===========================================================================
EDITABLE TEMPLATE — how content is resolved and rendered
===========================================================================
The actual subject/HTML lives in ``WelcomeEmailTemplate`` — a library of
named templates, each in one language (Dansk/Norsk), edited on the
"Velkomstmail" tab at ``/onboarding/flows/`` (``manage_api.welcome_emails_*``).
The manager picks one in the "Tildel flow" dialog; it's stored on
``OnboardingAssignment.welcome_email_template``.

``resolve_welcome_email_template(template_id=..., language=...)`` — in order:
  1. The explicitly chosen template (if it still exists).
  2. The default template for ``language`` (``is_default=True``).
  3. Any template in ``language``.
  4. The hardcoded starter content in ``welcome_email_defaults.py`` (Danish)
     — always available, so the system works before anyone has saved one.

``build_merge_context(...)`` builds the dict of merge tags available to the
subject/HTML (``{{ employee_first_name }}``, ``{{ buddy_name }}``, etc. —
see that function's docstring for the full list). Rendering goes through
Django's own template engine (``render_merge_tags`` below): safe by
default — no arbitrary code execution, and plain-text values like
``buddy_name`` are HTML-escaped automatically — and gives managers real
``{% if %}`` / ``{% for %}`` control if they want it, not just flat
substitution.
"""
from __future__ import annotations

import logging
import re

from django.core.exceptions import ValidationError
from django.template import TemplateSyntaxError, engines
from django.utils import timezone
from django.utils.html import strip_tags

from apps.planner.google.calendar_share import _send_gmail
from apps.planner.google.credentials import GoogleCredentialsUnavailable
from apps.planner.models import CalendarShareRequest

from .welcome_email_defaults import STARTER_HTML_BODY, STARTER_SUBJECT

logger = logging.getLogger(__name__)

_STEP_KIND_LABELS = {
    "info_link": "Læs",
    "checkbox": "Bekræft",
    "form": "Udfyld",
}

MERGE_TAGS = [
    ("employee_name", "Medarbejderens fulde navn"),
    ("employee_first_name", "Medarbejderens fornavn"),
    ("employee_email", "Medarbejderens e-mail"),
    ("manager_name", "Navnet på den, der tildelte/planlagde flowet"),
    ("manager_email", "E-mailen på den, der tildelte/planlagde flowet"),
    ("leder_name", "Navnet på medarbejderens leder (den de refererer til)"),
    ("leder_email", "E-mailen på medarbejderens leder"),
    ("buddy_name", "Buddyens navn"),
    ("buddy_email", "Buddyens e-mail"),
    ("flow_name", "Navnet på onboarding-flowet"),
    ("position", "Medarbejderens stilling"),
    ("department", "Medarbejderens afdeling"),
    ("start_date", "Medarbejderens startdato (kan være tomt)"),
    ("todo_steps", "Liste af ikke-møde-trin i flowet, hver med .title/.description/.kind_label"),
    ("meeting_steps", "Liste af calendar_meeting-trin, hver med .title/.description/.duration_minutes"),
]


class _StarterTemplate:
    """Duck-types a ``WelcomeEmailTemplate`` row without touching the DB."""

    pk = None
    id = None
    name = "Indbygget start-skabelon"
    language = "da"
    is_default = False
    updated_at = None
    updated_by = None
    updated_by_id = None

    def __init__(self, subject: str, html_body: str):
        self.subject = subject
        self.html_body = html_body


def starter_template() -> _StarterTemplate:
    return _StarterTemplate(STARTER_SUBJECT, STARTER_HTML_BODY)


def resolve_welcome_email_template(*, template_id=None, language: str = "da"):
    """Return ``(template, source)`` — see the module docstring for the order.

    ``source`` is ``"chosen"``, ``"default"``, ``"language"`` or ``"starter"``.
    """
    from .models import WelcomeEmailTemplate

    if template_id:
        chosen = WelcomeEmailTemplate.objects.filter(pk=template_id).first()
        if chosen is not None:
            return chosen, "chosen"
    in_language = WelcomeEmailTemplate.objects.filter(language=language)
    default = in_language.filter(is_default=True).first()
    if default is not None:
        return default, "default"
    first = in_language.order_by("name").first()
    if first is not None:
        return first, "language"
    if language != "da":
        logger.warning(
            "welcome_email: no template in language %r — falling back to the "
            "built-in (Danish) starter template.",
            language,
        )
    return starter_template(), "starter"


def build_merge_context(
    *,
    person,
    flow,
    requested_by,
    buddy_name: str = "",
    buddy_email: str = "",
    leder_name: str = "",
    leder_email: str = "",
    profile=None,
    country: str = "DK",
) -> dict:
    """Build the merge-tag context for ``flow``'s welcome email.

    ``person`` is the planner ``Person`` (name/email/etc.). ``profile`` is
    the ``OnboardingProfile`` if one exists yet (position/department/start
    date) — optional since preview can run before an employee has one.
    ``requested_by`` is the manager attaching (or previewing) the flow —
    note this may differ from ``leder_name``/``leder_email`` (the employee's
    actual reports-to manager), since anyone with manager access can attach
    a flow.
    """
    steps = list(flow.steps.all().order_by("order"))
    todo_steps = [s for s in steps if s.component_type != "calendar_meeting"]
    meeting_steps = [s for s in steps if s.component_type == "calendar_meeting"]

    name = (getattr(person, "name", "") or "").strip()
    first_name = name.split()[0] if name else ""
    manager_name = (
        requested_by.get_full_name()
        or getattr(requested_by, "email", "")
        or "Din leder"
    )
    manager_email = (getattr(requested_by, "email", None) or "").strip()

    return {
        "employee_name": name,
        "employee_first_name": first_name,
        "employee_email": getattr(person, "email", "") or "",
        "manager_name": manager_name,
        "manager_email": manager_email,
        "buddy_name": (buddy_name or "").strip(),
        "buddy_email": (buddy_email or "").strip(),
        "leder_name": (leder_name or "").strip(),
        "leder_email": (leder_email or "").strip(),
        "flow_name": flow.name,
        "position": getattr(profile, "position", "") or "",
        "department": getattr(profile, "department", "") or "",
        "start_date": getattr(profile, "start_date", None),
        "todo_steps": [
            {
                "title": s.title_for(country),
                "description": s.description_for(country),
                "kind_label": _STEP_KIND_LABELS.get(s.component_type, ""),
            }
            for s in todo_steps
        ],
        "meeting_steps": [
            {
                "title": s.title_for(country),
                "description": s.description_for(country),
                "duration_minutes": (s.config or {}).get("duration_minutes", 30),
            }
            for s in meeting_steps
        ],
    }


def render_merge_tags(template_string: str, context: dict) -> str:
    """Render ``template_string`` (subject or HTML body) against ``context``.

    Uses Django's own template engine — deliberately: it's already a
    project dependency, it does not allow arbitrary code execution (unlike
    e.g. Jinja2's default config), and it autoescapes plain string values
    by default, so a buddy name someone typed in doesn't need any special
    handling to be safe inside the HTML body. Raises
    ``django.template.TemplateSyntaxError`` on bad ``{% %}``/``{{ }}``
    syntax — callers that accept manager-edited templates (``manage_api``)
    should catch that and turn it into a 400.
    """
    django_engine = engines["django"]
    template = django_engine.from_string(template_string)
    return template.render(context)


def validate_template_syntax(*, subject: str, html_body: str) -> None:
    """Raise ``ValidationError`` if either string has bad template syntax."""
    dummy_context = {
        "employee_name": "Anna Andersen",
        "employee_first_name": "Anna",
        "employee_email": "anna@example.com",
        "manager_name": "Manager Navn",
        "manager_email": "manager@example.com",
        "buddy_name": "",
        "buddy_email": "",
        "leder_name": "",
        "leder_email": "",
        "flow_name": "Preview",
        "position": "",
        "department": "",
        "start_date": None,
        "todo_steps": [],
        "meeting_steps": [],
    }
    for label, value in (("Emnelinje", subject), ("HTML-indhold", html_body)):
        try:
            render_merge_tags(value, dummy_context)
        except TemplateSyntaxError as exc:
            raise ValidationError(f"{label}: {exc}") from exc


_BLOCK_TAG_RE = re.compile(r"(?i)</?(p|div|tr|li|h[1-6])[^>]*>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")


def html_to_plain(html: str) -> str:
    """Best-effort plain-text derivation of a rendered HTML email.

    Managers only edit the HTML; we don't maintain a separate plain-text
    template. This turns block-level boundaries into newlines before
    stripping tags, then collapses runs of blank lines, so multipart
    clients get something reasonably readable instead of one long
    tag-stripped run-on paragraph.
    """
    text = _BR_RE.sub("\n", html)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = strip_tags(text)
    text = text.replace("&nbsp;", " ")

    lines = [line.rstrip() for line in text.splitlines()]
    collapsed: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        collapsed.append(line)
    return "\n".join(collapsed).strip()


def render_welcome_email(*, template, context: dict) -> tuple[str, str, str]:
    """Render ``template`` (a ``WelcomeEmailTemplate`` or the starter) against
    ``context``. Returns ``(subject, plain_text, html)``."""
    subject = render_merge_tags(template.subject, context)
    html = render_merge_tags(template.html_body, context)
    return subject, html_to_plain(html), html


def send_onboarding_welcome_email(*, person, assignment, requested_by) -> CalendarShareRequest:
    """Send the combined welcome/calendar-share email for a fresh assignment.

    ``person`` is the planner ``Person`` record for the employee (used for
    the ``CalendarShareRequest`` audit row and the recipient address).
    ``assignment`` supplies the flow, buddy fields, and step list.
    ``requested_by`` is the manager who assigned the flow. The email is
    sent from the scheduler mailbox (``ONBOARDING_SCHEDULER_EMAIL``) when
    one is configured, otherwise from ``requested_by``'s own Gmail.

    Records a ``CalendarShareRequest`` for audit purposes (same model the
    standalone calendar-share feature uses) and raises ``ValidationError``
    on failure — mirrors ``apps.planner.services.calendar_share.send_share_request``.
    Does not check ``welcome_email_sent_at`` itself; callers decide whether
    to call this at all (see module docstring).
    """
    if not person.email:
        raise ValidationError("Person has no email address.")

    context = build_merge_context(
        person=person,
        flow=assignment.flow,
        requested_by=requested_by,
        buddy_name=assignment.buddy_name,
        buddy_email=assignment.buddy_email,
        leder_name=assignment.leder_name,
        leder_email=assignment.leder_email,
        profile=assignment.profile,
        country=assignment.country,
    )
    from .countries import language_for_country

    template, _source = resolve_welcome_email_template(
        template_id=assignment.welcome_email_template_id,
        language=language_for_country(assignment.country),
    )
    subject, plain, html = render_welcome_email(template=template, context=context)

    record = CalendarShareRequest(
        person=person,
        requested_by=requested_by,
        channel=CalendarShareRequest.CHANNEL_EMAIL,
    )
    # Sent from the shared scheduler mailbox when one is configured, with
    # Reply-To pointing at the leder so the employee's replies reach a
    # person. Falls back to the assigning manager's own Gmail otherwise.
    from apps.onboarding.calendar_booking import OrganizerResolutionError, scheduler_user

    try:
        sender = scheduler_user() or requested_by
    except OrganizerResolutionError as exc:
        record.success = False
        record.error_message = str(exc)[:500]
        record.save()
        raise ValidationError(str(exc)) from exc
    reply_to = (assignment.leder_email or getattr(requested_by, "email", "") or "").strip()

    try:
        _send_gmail(
            from_user=sender,
            to_email=person.email,
            subject=subject,
            plain_text=plain,
            html=html,
            reply_to=reply_to or None,
        )
    except GoogleCredentialsUnavailable as exc:
        record.success = False
        record.error_message = str(exc)
        record.save()
        raise ValidationError(str(exc)) from exc
    except Exception as exc:
        record.success = False
        record.error_message = str(exc)[:500]
        record.save()
        raise ValidationError(f"Could not send email: {exc}") from exc

    record.success = True
    record.save()

    assignment.welcome_email_sent_at = timezone.now()
    assignment.save(update_fields=["welcome_email_sent_at", "updated_at"])

    return record
