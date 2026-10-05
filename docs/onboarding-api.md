# Onboarding API

A headless REST API for creating new-hire onboarding flows and tracking
their progress. Designed to be called by:

- **ERP** — creates the employee when a hire is finalised in HR.
- **HR tooling / portal** — reads flow state and marks steps complete.

Onboardees themselves never log in to this system. They are stored as
inactive Django users (`is_active=False`) so they cannot reach the
check-in planner.

**Creating an employee never attaches a flow.** That's a deliberate,
separate action a manager takes in the browser UI (`POST
/api/onboarding/manage/employees/<erp_id>/assign-flow`) — see *Attaching a
flow (managers)* below. Neither `/provision` nor `POST /employees` on the
service API attaches a flow either, even though `/provision` still seeds
the default flow *template* if it's missing. This means the service/ERP
API currently has no way to attach a flow to an employee at all; a manager
always does it from `/onboarding/flows/`.

## Surfaces

| Surface | Base URL | Auth |
| --- | --- | --- |
| **Service API** (ERP, HR integrations) | `/api/onboarding/` | `X-API-Key` → `ONBOARDING_API_TOKEN` |
| **Manage API** (flow editor UI) | `/api/onboarding/manage/` | Django session + `manager`/`admin` group |
| **Browser UI** | `/onboarding/flows/` | Same session as manage API |
| **App hub** | `/home/` | Logged-in users; links to planner, onboarding, invites |

Logged-in managers use the **top navigation bar** on `/home/`, `/app/`,
`/onboarding/flows/`, and `/accounts/invites/` to switch between tools.

## Service API auth

Every endpoint requires header

```
X-API-Key: <ONBOARDING_API_TOKEN>
```

The token is a single shared secret read from the env var
`ONBOARDING_API_TOKEN`. Responses:

| Condition | Status |
| --- | --- |
| Token unset on the server | 503 |
| Header missing | 401 |
| Header wrong | 403 |
| Header correct | request proceeds |

Use a long random string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

CSRF is disabled on these endpoints (they're service-to-service).

## Service API endpoints

Base path: `/api/onboarding/` (all routes below are relative to this prefix).

### `POST /provision` (recommended for new hires)

One-call setup for external apps (ERP, HR portal): **ensures the default
flow template exists** (creates/updates it from the built-in baseline if
missing) and **creates the employee record**. It does **not** attach that
(or any) flow to the employee — a manager does that afterwards, separately,
from `/onboarding/flows/`.

Request body — same required fields as `POST /employees`. `flow_slug` is
**rejected with 400** if sent (there is no flow to pick — provisioning
never attaches one):

```json
{
  "erp_employee_id": "E1234",
  "email": "jane@blackcapitaltechnology.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "position": "Backend dev",
  "department": "Tech",
  "start_date": "2026-06-01"
}
```

Response (`201` first time, `200` idempotent replay on `erp_employee_id`):

```json
{
  "created": true,
  "default_flow_created": true,
  "default_flow_slug": "default",
  "employee": {
    "erp_employee_id": "E1234",
    "email": "jane@blackcapitaltechnology.com",
    "first_name": "Jane",
    "last_name": "Doe",
    "position": "Backend dev",
    "department": "Tech",
    "start_date": "2026-06-01"
  }
}
```

- `default_flow_created` — `true` only when this call inserted the default
  flow row (subsequent calls update steps in place via `seed_onboarding` logic).
- No `assignment` / `flow` / `steps` keys — nothing is assigned yet. Once a
  manager attaches a flow (see *Attaching a flow (managers)* below), those
  fields appear on `GET /employees/{erp_id}`.

This reuses the same service layer as `POST /employees`; use `/provision`
when you want the server to guarantee the default flow template exists
before a manager goes to attach it. `POST /employees` skips that guarantee.

### `POST /employees`

Create or upsert an employee **record only** — no flow is attached.
**Idempotent on `erp_employee_id`** — a replay returns the existing
employee with status `200`; a first-time call returns `201`.

Request body:
```json
{
  "erp_employee_id": "E1234",
  "email": "jane@blackcapitaltechnology.com",
  "first_name": "Jane",
  "last_name": "Doe",
  "position": "Backend dev",
  "department": "Tech",
  "start_date": "2026-06-01"
}
```

- `erp_employee_id` (required) — your ERP's stable identifier.
- `email` (required) — used to create the Django user (inactive).
- All other fields optional.
- `flow_slug` is **rejected with 400** — `{"detail": "flow_slug is not
  accepted when creating an employee. Create the employee first, then
  attach a flow via the assign-flow action."}`. Attaching a flow is a
  manager-only action in the browser UI (see below); it isn't available on
  this service API.

Response: the same shape as `GET /employees/{erp_id}` below — with
`"status": "no_flow"`, `"flow": null`, `"steps": []` until a manager
attaches a flow.

### `GET /employees`

Paginated list of all assignments. Query params:
- `page` (default 1)
- `page_size` (default 25, max 100)

Response:
```json
{
  "count": 12, "page": 1, "page_size": 25, "num_pages": 1,
  "results": [ { ...assignment payload... } ]
}
```

### `GET /employees/by-email` · `POST /employees/by-email`

Look up an employee's **current** onboarding assignment (latest flow per
profile) by their email address.

**GET** — query parameter:

```
GET /api/onboarding/employees/by-email?email=jane@blackcapitaltechnology.com
```

**POST** — JSON body (useful when the address is awkward in a query string):

```json
{ "email": "jane@blackcapitaltechnology.com" }
```

Email matching is case-insensitive.

**Response** when exactly one match: same payload as
`GET /employees/{erp_employee_id}` below.

**Response** when multiple onboarding profiles share the email (rare):

```json
{
  "email": "jane@blackcapitaltechnology.com",
  "count": 2,
  "results": [ { ...assignment payload... }, { ... } ]
}
```

Status codes:

- `200` — one or more assignments found
- `400` — missing or invalid `email`
- `404` — no onboarding profile / assignment for this email
- `401` / `403` — API key missing or wrong

### `GET /employees/{erp_employee_id}`

Employee state — shape depends on whether a manager has attached a flow
yet. Freshly created / no flow attached:

```json
{
  "erp_employee_id": "E1234",
  "email": "jane@blackcapitaltechnology.com",
  "first_name": "Jane", "last_name": "Doe",
  "position": "Backend dev", "department": "Tech", "start_date": "2026-06-01",
  "status": "no_flow",
  "assigned_at": null,
  "started_at": null,
  "completed_at": null,
  "flow": null,
  "steps": []
}
```

Once a manager attaches a flow (see *Attaching a flow (managers)* below),
the same endpoint returns the full assignment payload:

```json
{
  "erp_employee_id": "E1234",
  "email": "jane@blackcapitaltechnology.com",
  "first_name": "Jane", "last_name": "Doe",
  "position": "Backend dev", "department": "Tech", "start_date": "2026-06-01",
  "status": "in_progress",
  "assigned_at": "2026-05-12T09:00:00+00:00",
  "started_at": "2026-05-12T09:05:00+00:00",
  "completed_at": null,
  "flow": {"slug": "default", "name": "BCT onboarding", "description": "..."},
  "steps": [
    {
      "id": 7, "order": 1, "component_type": "info_link",
      "title": "Read handbook", "description": "...",
      "config": {"url": "https://...", "body": "...", "requires_read": true},
      "is_required": true,
      "status": "completed",
      "completion_data": {"read_at": "2026-05-12T09:05:00+00:00"},
      "completed_at": "2026-05-12T09:05:00+00:00",
      "completed_by": "hr-portal"
    },
    ...
  ]
}
```

Status codes:
- `200` — success
- `404` — no employee with this `erp_employee_id`

### `PATCH /employees/{erp_employee_id}/steps/{step_id}`

Update a single step's progress.

Request body:
```json
{
  "status": "completed",
  "completion_data": {"checked": true},
  "completed_by": "hr-portal"
}
```

- `status` (required): one of `pending` (re-open), `completed`, `skipped`.
- `completion_data` (required dict): validated against the step's component
  type — see *Component types* below.
- `completed_by` (optional): free-form tag of the source system. Stored
  for audit; not validated.

On `completed`/`skipped`, the assignment status is recomputed:
- First finished step flips assignment from `pending` → `in_progress`.
- All required steps finished flips it to `completed`.
- Re-opening (`pending`) reverts the assignment if it was `completed`.

Response:
```json
{
  "assignment_status": "in_progress",
  "step": {
    "id": 7, "order": 1, "title": "...", "component_type": "checkbox",
    "status": "completed",
    "completion_data": {"checked": true},
    "completed_at": "2026-05-12T09:05:00+00:00",
    "completed_by": "hr-portal"
  }
}
```

Status codes:
- `200` — success
- `400` — invalid payload or `completion_data` doesn't match the component schema
- `404` — unknown employee, or step doesn't belong to this employee's flow

### `GET /flows` and `GET /flows/{slug}`

Read flow templates (without an employee). Useful for tooling that
renders a step-by-step preview before an employee exists.

### Service API quick reference

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/provision` | Seed default flow template (if needed) + create employee (no flow attached) |
| POST | `/employees` | Create / upsert employee (no flow attached; `flow_slug` rejected) |
| GET | `/employees` | Paginated list of employees (with or without a flow) |
| GET/POST | `/employees/by-email` | Look up current assignment by email |
| GET | `/employees/<erp_id>` | Full assignment by ERP id |
| PATCH | `/employees/<erp_id>/steps/<step_id>` | Update step progress |
| GET | `/flows`, `/flows/<slug>` | Read flow templates |

## Component types

The set of step component types is **fixed in code** (`apps/onboarding/components.py`).
Each defines a config schema (stored on `FlowStep.config`) and a
completion schema (validated on PATCH).

### `info_link`
Config:
```json
{"body": "Optional intro text.", "url": "https://...", "requires_read": true}
```
Completion: `{"read_at": "2026-05-12T09:05:00+00:00"}` (optional). Empty
`{}` also accepted.

### `checkbox`
Config: `{"label": "Photo taken?"}`

Completion: `{"checked": true}` (required `bool`).

### `form`
Config:
```json
{
  "fields": [
    {"name": "tax_number", "label": "Tax #", "type": "text", "required": true},
    {"name": "country", "label": "Country", "type": "text", "required": true}
  ]
}
```
Field types: `text`, `longtext`, `email`, `number`, `date`, `boolean`.

Completion: `{"values": {"tax_number": "...", "country": "..."}}`.

### `calendar_meeting`
When a manager attaches a flow via the Manage API (see *Attaching a flow
(managers)* below), every `calendar_meeting` step is booked automatically
on Google Calendar — see `apps/onboarding/calendar_booking.py`. This PATCH
endpoint remains available as the manual/external completion path: if the
organizer hasn't connected Google (booking is skipped for that step only)
or HR tooling schedules the meeting itself and wants to record the result,
PATCH it here with the shape below.

Config:
```json
{"participants": ["leder", "buddy"], "duration_minutes": 30, "day_offset": 30, "day_unit": "calendar", "time_of_day": "10:00"}
```
`participants` = who the meeting is with besides the employee: email
addresses and/or `leder`, `buddy`, `assigning_manager`. The booking finds a
time all of them are free and invites them all. When
`ONBOARDING_SCHEDULER_EMAIL` is set (default
`scheduler@blackcapitaltechnology.com`) that mailbox organizes the event and
also sends the welcome email; it must sign in to the planner once. The older
single `with_email` key is still accepted.
`day_offset` (optional) = days after the employee's start date (start date is 0).
`day_unit`: `"calendar"` counts plain calendar days and rolls forward to the
next working day if that lands on a weekend or Danish holiday; `"business"`
counts working days only (the default when omitted). `time_of_day` is 24h
`HH:MM`, tried first on that day.
Completion:
```json
{
  "scheduled_at": "2026-06-01T10:00:00+02:00",
  "google_event_id": "abc123",
  "html_link": "https://calendar.google.com/event?eid=..."
}
```
`scheduled_at` (ISO datetime string) is required; the rest are optional.

## Manage API and browser UI (managers)

Managers and admins edit flows and onboardees in the browser (no API key).
Open **`/home/`** after login, then **Onboarding**, or go directly to
`/onboarding/flows/`.

- **UI:** `/onboarding/flows/` — **Flows** tab (templates + steps) and
  **Medarbejdere** tab (employee CRUD + flow assignment)
- **Auth:** Django session (Google login) + `manager` or `admin` group
- **API base:** `/api/onboarding/manage/` (same-origin, CSRF cookie)

| Method | Path | Action |
| --- | --- | --- |
| GET | `/api/onboarding/manage/component-types` | Component metadata + default configs |
| GET | `/api/onboarding/manage/flows` | List flows (includes inactive + assignment counts) |
| POST | `/api/onboarding/manage/flows` | Create flow |
| GET/PATCH/DELETE | `/api/onboarding/manage/flows/<slug>` | Read / update / delete or deactivate |
| POST | `/api/onboarding/manage/flows/<slug>/steps` | Add step |
| PATCH/DELETE | `/api/onboarding/manage/flows/<slug>/steps/<id>` | Update / delete step (409 if in use) |
| PUT | `/api/onboarding/manage/flows/<slug>/steps/reorder` | Body: `{ "step_ids": [3, 1, 2] }` |
| GET | `/api/onboarding/manage/employees` | List employees, with or without a flow attached |
| POST | `/api/onboarding/manage/employees` | Create employee (no flow attached; `flow_slug` rejected) |
| GET/PATCH/DELETE | `/api/onboarding/manage/employees/<erp_id>` | Read / update / delete |
| POST/DELETE | `/api/onboarding/manage/employees/<erp_id>/assign-flow` | **Attach / detach a flow** — see below |
| POST | `/api/onboarding/manage/employees/<erp_id>/book-calendar-meetings` | Manually retry booking for the active flow |
| GET | `/api/onboarding/manage/people` | All planner `Person` records + onboarding status (Medarbejdere tab data source) |
| GET/PUT/DELETE | `/api/onboarding/manage/flows/<slug>/welcome-email` | **Edit the welcome email template** — see below |
| POST | `/api/onboarding/manage/flows/<slug>/welcome-email/preview` | Render a welcome email without sending it |

**Manage vs service API differences:**

- Create employee: identical contract on both — neither accepts
  `flow_slug`; both create a profile-only record with no flow attached.
- Attaching a flow: **manage API only** (`assign-flow`, below). The
  service API has no equivalent endpoint.
- Update employee: PATCH never touches the flow — `flow_slug` is rejected
  with 400 on both APIs (`"flow_slug cannot be changed via PATCH. Use the
  assign-flow endpoint to attach a different flow."`).
- Delete employee: removes profile and inactive user; fails with `400` if the
  linked Django user is `is_active=True`.

Slug is immutable after create. Deleting a flow that has employee assignments
only sets `is_active=false`.

### Attaching a flow (managers)

```
POST /api/onboarding/manage/employees/<erp_id>/assign-flow
Body: {
  "flow_slug": "default",
  "buddy_name": "Rasmus",       // optional
  "buddy_email": "rasmus@blackcapitaltechnology.com"   // optional
}
```

This is the **one deliberate "attach a flow" action** in the system.
Creating an employee never does this as a side effect — see the note at
the top of this document. In the browser UI it's the "Tildel flow" button
on a `no_flow` employee — which also shows a **live preview** of the
actual welcome email before you confirm (see *Editing the welcome email*
below), so you can fill in the buddy and see the real result before it
sends. `buddy_name`/`buddy_email` are only recorded the first time (same
as `assigned_by`) and are available in the welcome email as the
`{{ buddy_name }}`/`{{ buddy_email }}` merge tags.

**Two hard pre-flight checks run before anything is created.** Either one
blocks the request with `400` and creates nothing — no assignment, no
email, no booking, no Slack invite:

1. **The employee has no email address.**
   ```json
   {"detail": "This person has no email address on file. Add one on the planner Person record before attaching a flow — the welcome email and calendar invite both need it."}
   ```
   Fix: add an email to the planner `Person` record, then retry.

2. **The acting manager hasn't connected Google.**
   ```json
   {"detail": "<manager email> haven't connected Google Calendar yet. Sign in with Google once (top nav) before attaching a flow — the welcome email and any 'assigning_manager' meetings are sent/booked from your account."}
   ```
   Fix: the manager signs in with Google once (top nav), then retries.

Once both checks pass, on a **brand-new** assignment (first time this
employee is attached to this flow) the following all run automatically,
in this order:

1. The acting manager is recorded as `assigned_by` (used as the welcome
   email sender and to resolve `"assigning_manager"` meeting organizers).
2. The combined welcome + calendar-share-request email is sent once.
3. Every `calendar_meeting` step in the flow is booked on Google Calendar
   (best-effort, per-step isolated — see the `calendar_meeting` component
   above).
4. The employee is invited to Slack — invited to the configured onboarding
   channel(s) and sent a short welcome DM (best-effort; no-ops with a clear
   `"not_configured"` result until `SLACK_BOT_TOKEN` is set — see *Slack
   invite setup* below).

Steps 2–4 are all best-effort: a failure in any one of them is reported
back in the response but does **not** roll back the assignment or block
the other steps. Re-attaching an already-attached flow (idempotent replay)
skips steps 2 and 4 — already done — but re-runs step 3 for whatever is
still unbooked (this is also what the "Book møder" retry button does
explicitly, via `POST .../book-calendar-meetings`).

Response (`201` first attach, `200` idempotent replay) — the usual
employee-state payload plus an `automation` object:

```json
{
  "erp_employee_id": "E1234",
  "status": "in_progress",
  "flow": {"slug": "default", "name": "BCT onboarding"},
  "steps": [ ... ],
  "automation": {
    "welcomeEmail": {"sent": true},
    "meetings": {"booked": [ ... ], "already_exists": [], "no_slot": [], "error": [] },
    "slackInvite": {"sent": false, "reason": "not_configured"}
  }
}
```

`automation.welcomeEmail` and `automation.slackInvite` are `null` on a
replay (not re-run); `automation.meetings` is present whenever the
assignment isn't already `completed`.

```
DELETE /api/onboarding/manage/employees/<erp_id>/assign-flow
```

Removes the most recent `pending`/`in_progress` assignment and its step
progress. Refuses (`409`) to delete a `completed` assignment.

### Slack invite setup

The Slack step above no-ops with `{"sent": false, "reason":
"not_configured"}` until two settings are filled in — nothing else needs
to change once you have them. Full walkthrough (app creation, required bot
scopes, where to find a channel ID, and an important limitation on
inviting brand-new hires who don't have a Slack account yet) lives in the
module docstring at `apps/onboarding/slack_invite.py`. Summary:

| Setting | Value |
| --- | --- |
| `SLACK_BOT_TOKEN` | Bot User OAuth Token from a Slack app, starts with `xoxb-` |
| `SLACK_ONBOARDING_CHANNEL_IDS` | Comma-separated Slack **channel IDs** (not names) new hires get invited to |

Set both in `backend/.env` locally (or Render's env vars for
staging/production) and restart — no code change needed.

### Editing the welcome email ("Velkomstmail" tab)

Managers edit the actual welcome email — subject and full HTML — from a
third tab at `/onboarding/flows/` called **Velkomstmail**: pick a flow,
edit the HTML source (a real code editor, not a WYSIWYG — you're editing
the same HTML you'd hand a designer), and a live preview updates on the
right as you type. Behind the scenes:

**Storage — one template per flow, with a fallback.** Each `OnboardingFlow`
can have its own `WelcomeEmailTemplate` (subject + `html_body`). A flow
with no template of its own uses whichever *other* flow's template is
marked "Brug som standard-skabelon" (`is_default_fallback`) — at most one
template in the whole system can hold that flag; saving a new default
unsets the previous one, the same way `OnboardingFlow.is_default` works.
If literally nothing is configured anywhere yet (a fresh install), the
system falls back to a hardcoded starter template — the real email BCT
used to onboard a new hire, shipped with this feature — so sending never
breaks just because nobody has visited this tab yet.

```
GET /api/onboarding/manage/flows/<slug>/welcome-email
```
Returns the *effective* template for this flow whether or not it has one
of its own:
```json
{
  "flow_slug": "default",
  "source": "own",                  // "own" | "fallback" | "starter"
  "has_own_template": true,
  "is_default_fallback": false,
  "fallback_flow_slug": null,       // set when source == "fallback"
  "subject": "Velkommen til Black Capital Technology, {{ employee_first_name }}!",
  "html_body": "<!doctype html>...",
  "updated_at": "2026-08-10T09:00:00+00:00",
  "updated_by": "mgr@blackcapitaltechnology.com"
}
```

```
PUT /api/onboarding/manage/flows/<slug>/welcome-email
Body: {"subject": "...", "html_body": "...", "is_default_fallback": false}
```
Creates or overwrites this flow's own template. Bad `{% %}`/`{{ }}` syntax
is rejected with `400` **before** anything is saved (see *Merge tags*
below) — same shape as any other validation error on this API.

```
DELETE /api/onboarding/manage/flows/<slug>/welcome-email
```
Deletes this flow's own template (`404` if it doesn't have one) — it then
falls back to whatever `GET` would show next (another flow's default, or
the starter). Doesn't touch any other flow's template.

```
POST /api/onboarding/manage/flows/<slug>/welcome-email/preview
Body (all optional): {
  "subject": "...", "html_body": "...",   // preview unsaved draft content
  "erp_id": "E1234",                       // render with a real employee
  "buddy_name": "...", "buddy_email": "..."
}
```
With no body: previews the currently *saved* effective template against
placeholder sample data ("Anna Andersen"). With `subject`/`html_body`
given (both required together): previews that exact unsaved draft
instead — this is what the editor calls on every keystroke, debounced, so
the preview always matches the textarea, never what's on disk. With
`erp_id`: renders with that employee's real name/email/position instead
of the placeholder. Returns `{"subject": "...", "html": "...", "plain":
"...", "source": "..."}` (`source` omitted when previewing draft content).

**Merge tags.** Rendering goes through Django's own template engine — not
a flat find/replace — so `{% if %}`/`{% for %}` work too, and any
plain-text value (like a manager-typed buddy name) is HTML-escaped
automatically. Available tags:

| Tag | Value |
| --- | --- |
| `{{ employee_name }}` | Full name |
| `{{ employee_first_name }}` | First name |
| `{{ employee_email }}` | Email |
| `{{ manager_name }}` | Name of the manager attaching the flow |
| `{{ manager_email }}` | Email of the manager attaching the flow |
| `{{ buddy_name }}` | Empty if not filled in — guard with `{% if buddy_name %}` |
| `{{ buddy_email }}` | Empty if not filled in |
| `{{ flow_name }}` | The onboarding flow's name |
| `{{ position }}` / `{{ department }}` | From the employee's profile |
| `{{ start_date }}` | May be empty |
| `{{ todo_steps }}` / `{{ meeting_steps }}` | The flow's non-meeting / `calendar_meeting` steps, each with `.title`/`.description` (`meeting_steps` also `.duration_minutes`) — for a template that wants to list the actual flow steps instead of (or alongside) static copy |

The plain-text part of the email (for clients that don't render HTML) is
derived automatically from the HTML — there's no separate plain-text
field to keep in sync.

## Django admin (alternative)

Manager/admin users can also use Django admin at `/admin/onboarding/`.
Step configs are JSON; the admin form runs the component validator.

Seed the default flow with example steps:
```
python backend/manage.py seed_onboarding
```

## Example calls

```bash
TOKEN=...  # match ONBOARDING_API_TOKEN
BASE=https://checkin-planner-prod.onrender.com/api/onboarding

# 1. ERP provisions a new hire (creates the employee + guarantees the default
#    flow template exists — does NOT attach a flow; that's a manager's call)
curl -X POST "$BASE/provision" \
  -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "erp_employee_id":"E1234",
    "email":"jane@blackcapitaltechnology.com",
    "first_name":"Jane","last_name":"Doe",
    "position":"Backend dev","department":"Tech",
    "start_date":"2026-06-01"
  }'

# Or POST /employees for the same "create only" record without seeding the
# default flow template:
curl -X POST "$BASE/employees" \
  -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "erp_employee_id":"E1234",
    "email":"jane@blackcapitaltechnology.com",
    "first_name":"Jane","last_name":"Doe",
    "position":"Backend dev","department":"Tech",
    "start_date":"2026-06-01"
  }'

# 2. A manager attaches a flow from the browser UI (/onboarding/flows/,
#    "Tildel flow" button) — session-authenticated, not callable with the
#    service API key above. This is what actually sends the welcome email,
#    books the calendar_meeting steps, and invites the employee to Slack:
#    POST /api/onboarding/manage/employees/E1234/assign-flow
#    Body: {"flow_slug": "default"}

# 3. HR portal fetches the flow + progress (by ERP id or email), once a
#    manager has attached a flow — "flow": null / "steps": [] until then
curl "$BASE/employees/E1234" -H "X-API-Key: $TOKEN"
curl "$BASE/employees/by-email?email=jane@blackcapitaltechnology.com" -H "X-API-Key: $TOKEN"

# 4. HR portal marks "photo taken" complete (step must belong to the
#    employee's already-attached flow)
curl -X PATCH "$BASE/employees/E1234/steps/8" \
  -H "X-API-Key: $TOKEN" -H "Content-Type: application/json" \
  -d '{"status":"completed","completion_data":{"checked":true},"completed_by":"hr-portal"}'
```

## Operational notes

- The Django user created for the onboardee is `is_active=False` with an
  unusable password. They cannot sign in to anything in this project.
- Editing a flow template (`OnboardingFlow` / `FlowStep`) does NOT
  retro-apply to in-flight assignments — existing `StepProgress` rows
  keep pointing at their original step. Pick "add new step at end" if
  you need to extend an in-flight onboarding.
- The shared API token is a single value in `ONBOARDING_API_TOKEN`. For
  per-client tokens or scopes, this can later be replaced by a small
  `ServiceClient` model (one row per integration) without changing the
  endpoint shapes.
- Attaching a flow (`assign-flow`) hard-blocks with `400` — creating
  nothing — if the employee has no email, or if the acting manager hasn't
  connected Google. Both are prerequisites for what the attach action does
  next (welcome email, calendar booking), so they're checked upfront rather
  than reported as a partial failure afterwards.
- The Slack invite step is real, working code that no-ops until
  `SLACK_BOT_TOKEN` is configured — see *Slack invite setup* above. Even
  once configured, Slack's public API can only add an employee to a
  channel/DM if they **already have a Slack account** in the workspace;
  brand-new hires without one yet get `"no_slack_account"`, which is
  expected, not an error.
- The welcome email's *content* is fully editable per flow (see *Editing
  the welcome email* above) — but the automation around it (send once,
  book meetings, invite to Slack, the two pre-flight blocks) is not
  configurable; editing the template only changes what's inside the email,
  not when or whether it's sent.
