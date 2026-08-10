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
The actual subject/HTML a manager sees and edits lives in
``WelcomeEmailTemplate`` (one row per ``OnboardingFlow``, editable from the
"Velkomstmail" tab at ``/onboarding/flows/`` — see ``manage_api.py``'s
``flow_welcome_email`` / ``flow_welcome_email_preview`` views). This module
just resolves *which* template applies to a given flow and renders it:

``resolve_welcome_email_template(flow)`` — in order:
  1. This flow's own ``WelcomeEmailTemplate``, if it has one.
  2. Whichever template in the system (any flow) is marked
     ``is_default_fallback=True``, if any.
  3. The hardcoded starter content in ``welcome_email_defaults.py`` — the
     real BCT welcome email this feature shipped with. Always available,
     so the system works even before any manager has touched this feature.

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
    ("manager_name", "Navnet på den leder, der tildeler flowet"),
    ("manager_email", "E-mailen på den leder, der tildeler flowet"),
    ("buddy_name", "Buddyens navn (tomt hvis ikke udfyldt — brug {% if buddy_name %})"),
    ("buddy_email", "Buddyens e-mail (tomt hvis ikke udfyldt)"),
    ("flow_name", "Navnet på onboarding-flowet"),
    ("position", "Medarbejderens stilling"),
    ("department", "Medarbejderens afdeling"),
    ("start_date", "Medarbejderens startdato (kan være tomt)"),
    ("todo_steps", "Liste af ikke-møde-trin i flowet, hver med .title/.description/.kind_label"),
    ("meeting_steps", "Liste af calendar_meeting-trin, hver med .title/.description/.duration_minutes"),
]


class _StarterTemplate:
    """Duck-types a ``WelcomeEmailTemplate`` row without touching the DB."""

    flow = None
    is_default_fallback = False

    def __init__(self, subject: str, html_body: str):
        self.subject = subject
        self.html_body = html_body


def resolve_welcome_email_template(flow):
    """Return ``(template, source, fallback_flow_slug)`` for ``flow``.

    ``source`` is one of ``"own"``, ``"fallback"``, ``"starter"`` — see the
    module docstring for the resolution order. ``fallback_flow_slug`` is
    only set when ``source == "fallback"`` (the slug of the flow whose
    template is being borrowed).
    """
    from .models import WelcomeEmailTemplate

    own = WelcomeEmailTemplate.objects.filter(flow=flow).first()
    if own is not None:
        return own, "own", None

    fallback = WelcomeEmailTemplate.objects.filter(is_default_fallback=True).first()
    if fallback is not None:
        return fallback, "fallback", fallback.flow.slug

    return _StarterTemplate(STARTER_SUBJECT, STARTER_HTML_BODY), "starter", None


def build_merge_context(
    *,
    person,
    flow,
    requested_by,
    buddy_name: str = "",
    buddy_email: str = "",
    profile=None,
) -> dict:
    """Build the merge-tag context for ``flow``'s welcome email.

    ``person`` is the planner ``Person`` (name/email/etc.). ``profile`` is
    the ``OnboardingProfile`` if one exists yet (position/department/start
    date) — optional since preview can run before an employee has one.
    ``requested_by`` is the manager attaching (or previewing) the flow.
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
        "flow_name": flow.name,
        "position": getattr(profile, "position", "") or "",
        "department": getattr(profile, "department", "") or "",
        "start_date": getattr(profile, "start_date", None),
        "todo_steps": [
            {
                "title": s.title,
                "description": s.description,
                "kind_label": _STEP_KIND_LABELS.get(s.component_type, ""),
            }
            for s in todo_steps
        ],
        "meeting_steps": [
            {
                "title": s.title,
                "description": s.description,
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


def render_welcome_email(*, flow, context: dict) -> tuple[str, str, str, str]:
    """Resolve + render the welcome email for ``flow``.

    Returns ``(subject, plain_text, html, source)`` — ``source`` is
    whichever of ``"own"``/``"fallback"``/``"starter"``
    ``resolve_welcome_email_template`` used, handy for callers that want to
    surface that in a preview.
    """
    template, source, _fallback_slug = resolve_welcome_email_template(flow)
    subject = render_merge_tags(template.subject, context)
    html = render_merge_tags(template.html_body, context)
    plain = html_to_plain(html)
    return subject, plain, html, source


def send_onboarding_welcome_email(*, person, assignment, requested_by) -> CalendarShareRequest:
    """Send the combined welcome/calendar-share email for a fresh assignment.

    ``person`` is the planner ``Person`` record for the employee (used for
    the ``CalendarShareRequest`` audit row and the recipient address).
    ``assignment`` supplies the flow, buddy fields, and step list.
    ``requested_by`` is the manager whose Gmail sends the email.

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
        profile=assignment.profile,
    )
    subject, plain, html, _source = render_welcome_email(flow=assignment.flow, context=context)

    record = CalendarShareRequest(
        person=person,
        requested_by=requested_by,
        channel=CalendarShareRequest.CHANNEL_EMAIL,
    )
    try:
        _send_gmail(
            from_user=requested_by,
            to_email=person.email,
            subject=subject,
            plain_text=plain,
            html=html,
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
