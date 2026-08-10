"""Invite a new onboarding employee to Slack.

Runs automatically, alongside the welcome email and calendar booking, the
moment a manager attaches an onboarding flow to an employee (see
``manage_api.assign_flow``). Best-effort and per-step isolated, in the same
spirit as ``calendar_booking.py``: this module never raises out of its
public entry point — ``send_onboarding_slack_invite`` always returns a
structured outcome dict that ``assign_flow`` puts straight into the
response's ``automation.slackInvite`` field. A Slack failure never blocks
the attach, exactly like the welcome email and meeting booking.

===========================================================================
SETUP GUIDE — for whoever wires up the real Slack app credentials
===========================================================================
This module already makes real Slack Web API calls; it just no-ops with a
clear "not configured" result until ``SLACK_BOT_TOKEN`` is set. Nothing
else in the codebase needs to change once you have a token — just fill in
the two settings below (in ``backend/.env`` locally, and in Render's env
vars for staging/production; see ``config/settings.py``):

    SLACK_BOT_TOKEN             — Bot User OAuth Token, starts with "xoxb-"
    SLACK_ONBOARDING_CHANNEL_IDS — comma-separated Slack channel IDs
                                    (not names) new hires get invited to

Steps to get a token:

1. Go to https://api.slack.com/apps and create a new app "from scratch"
   for the BCT workspace (or reuse an existing internal-tools app).
2. Under **OAuth & Permissions → Scopes → Bot Token Scopes**, add:
     - ``users:read.email``  — look up an existing Slack account by email
     - ``channels:manage``   — invite the user into public channels
     - ``groups:write``      — only needed if you also invite to private channels
     - ``chat:write``        — post the welcome message
     - ``im:write``          — open a DM to post the welcome message into
3. **Install to Workspace**, then copy the "Bot User OAuth Token" from the
   same page (starts with ``xoxb-``). That's ``SLACK_BOT_TOKEN``.
4. Find the channel ID(s) you want new hires auto-joined to: open the
   channel in Slack → channel name → scroll to the bottom of the "About"
   panel → copy the Channel ID (looks like ``C0123ABCDEF``). That's
   ``SLACK_ONBOARDING_CHANNEL_IDS`` (comma-separate if more than one).
5. Set both env vars and redeploy / restart the dev server. No code change
   needed — the next flow attach will actually call Slack.

IMPORTANT LIMITATION — read before relying on this for every new hire:
Slack's public Web API does **not** let a bot token invite an arbitrary
*email address* into the workspace itself on standard/Business plans —
that's restricted to an admin acting interactively in the Slack UI (or the
SCIM API, which needs Business+/Enterprise). So this can only act on an
employee who **already has a Slack account** in the workspace — e.g.
auto-provisioned via SSO/domain join, or someone manually invited them
already. When ``users.lookupByEmail`` finds no match, that's reported as
outcome ``"no_slack_account"`` — an expected, common case for a brand-new
hire, not a bug. If BCT is on Enterprise Grid and wants a true
"invite-to-workspace by email" step, swap ``_lookup_user_by_email`` for a
call to ``admin.users.invite`` (scope ``admin.users:write``) and adjust
the flow in ``send_onboarding_slack_invite`` accordingly.
===========================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_SLACK_API_BASE = "https://slack.com/api"
_TIMEOUT_SECONDS = 10


class SlackApiError(RuntimeError):
    """Raised internally when Slack's API rejects a call."""


@dataclass
class SlackInviteResult:
    sent: bool = False
    reason: str = ""  # "not_configured" | "no_slack_account" | "error" | ""
    error: str = ""
    slack_user_id: str = ""
    channels_joined: list[str] = field(default_factory=list)
    dm_sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"sent": self.sent}
        if self.reason:
            d["reason"] = self.reason
        if self.error:
            d["error"] = self.error
        if self.slack_user_id:
            d["slackUserId"] = self.slack_user_id
        if self.channels_joined:
            d["channelsJoined"] = self.channels_joined
        if self.sent:
            d["dmSent"] = self.dm_sent
        return d


def _slack_post(method: str, payload: dict) -> dict:
    token = getattr(settings, "SLACK_BOT_TOKEN", "")
    response = requests.post(
        f"{_SLACK_API_BASE}/{method}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    body = response.json()
    if not body.get("ok"):
        raise SlackApiError(f"Slack API {method} failed: {body.get('error', 'unknown_error')}")
    return body


def _lookup_user_by_email(email: str) -> str | None:
    """Return the Slack user id for ``email``, or None if no account exists."""
    try:
        body = _slack_post("users.lookupByEmail", {"email": email})
    except SlackApiError as exc:
        if "users_not_found" in str(exc):
            return None
        raise
    return body["user"]["id"]


def _invite_to_channels(user_id: str, channel_ids: list[str]) -> list[str]:
    """Invite ``user_id`` to each channel. Returns channel ids now joined.

    Per-channel isolated: one channel failing (e.g. bot not in that
    channel) doesn't stop the others from being attempted.
    """
    joined: list[str] = []
    for channel_id in channel_ids:
        try:
            _slack_post("conversations.invite", {"channel": channel_id, "users": user_id})
            joined.append(channel_id)
        except SlackApiError as exc:
            if "already_in_channel" in str(exc):
                joined.append(channel_id)
                continue
            logger.warning(
                "slack_invite: could not invite %s to channel %s: %s",
                user_id, channel_id, exc,
            )
    return joined


def _send_welcome_dm(
    user_id: str, *, employee_name: str, manager_name: str, flow_name: str
) -> None:
    dm = _slack_post("conversations.open", {"users": user_id})
    channel_id = dm["channel"]["id"]
    greeting = employee_name.strip() or "there"
    text = (
        f"Velkommen til Black Capital Technology, {greeting}! :tada:\n"
        f"{manager_name} har sat din onboarding i gang ({flow_name}). "
        f"Du får en velkomstmail med alle detaljerne separat."
    )
    _slack_post("chat.postMessage", {"channel": channel_id, "text": text})


def send_onboarding_slack_invite(*, person, assignment, requested_by) -> SlackInviteResult:
    """Best-effort Slack invite for a fresh onboarding-flow attach.

    Looks the employee up by email, invites them to the configured
    onboarding channels, and posts a short welcome DM. Never raises —
    always returns a ``SlackInviteResult`` describing what happened, so
    ``manage_api.assign_flow`` can put it straight into the response
    without a try/except of its own (mirrors ``calendar_booking``'s
    contract, not ``welcome_email``'s raise-and-catch one, since Slack has
    more "this isn't a failure, just not applicable yet" outcomes than
    either of those).
    """
    result = SlackInviteResult()

    token = getattr(settings, "SLACK_BOT_TOKEN", "")
    if not token:
        result.reason = "not_configured"
        logger.info(
            "slack_invite: skipped for %s — SLACK_BOT_TOKEN not set", person.legacy_id
        )
        return result

    email = (person.email or "").strip()
    if not email:
        result.reason = "error"
        result.error = "Person has no email address."
        return result

    try:
        user_id = _lookup_user_by_email(email)
    except Exception as exc:
        result.reason = "error"
        result.error = str(exc)
        logger.warning("slack_invite: lookup failed for %s: %s", email, exc)
        return result

    if user_id is None:
        result.reason = "no_slack_account"
        logger.info(
            "slack_invite: %s has no Slack account yet (email=%s)",
            person.legacy_id, email,
        )
        return result

    result.slack_user_id = user_id

    channel_ids = list(getattr(settings, "SLACK_ONBOARDING_CHANNEL_IDS", []) or [])
    if channel_ids:
        result.channels_joined = _invite_to_channels(user_id, channel_ids)

    try:
        manager_name = (
            requested_by.get_full_name()
            or getattr(requested_by, "email", "")
            or "Din leder"
        )
        _send_welcome_dm(
            user_id,
            employee_name=person.name or "",
            manager_name=manager_name,
            flow_name=assignment.flow.name,
        )
        result.dm_sent = True
    except Exception as exc:
        # Channel invites (if any) already went through — don't null those
        # out just because the DM failed.
        logger.warning("slack_invite: welcome DM failed for %s: %s", email, exc)

    result.sent = True
    return result
