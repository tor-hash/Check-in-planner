"""Server-side Google API integrations.

This package replaces the previous client-only flow. Managers consent once
via the standard OAuth login; their refresh_token is stored on
``UserSocialAuth.extra_data`` and used by these services to mint short-lived
access tokens for FreeBusy lookups and Calendar event creation.

Modules:
    - ``credentials`` — load + refresh google.oauth2 credentials per manager
    - ``freebusy``    — query free/busy windows for a list of attendees
    - ``events``      — create a Calendar event with the manager + attendee
"""
